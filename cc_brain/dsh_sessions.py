"""DeepSeek Harness (dsh) session source:
~/.dsh/sessions/<cwd-slug>/session-<uuid>/session.v4.jsonl.zstd → rolling summary → consolidation.

Same flow as pi_sessions, but the file is zstd-compressed and may be rewritten, so progress is tracked by
the last event `seq` read, not a byte offset."""

import json
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path

import zstandard

from .pi_sessions import MAX_DELTA_CHARS, PiSessionTracker

logger = logging.getLogger("cc-brain")

DSH_SESSIONS_DIR = Path.home() / ".dsh" / "sessions"
SESSION_FILE = "session.v4.jsonl.zstd"
MAX_TOOL_CHARS = 200
# The dsh auto-recall hook runs sandboxed (workspace-write: temp dirs only), so it logs to a temp file;
# the daemon appends those lines to the shared auto-recall log.
RECALL_LOG = Path.home() / ".cc-brain" / "logs" / "auto-recall.jsonl"
RECALL_FALLBACK = "cc-brain-dsh-recall/auto-recall.jsonl"


def is_session_file(path):
    p = Path(path)
    return p.name == SESSION_FILE and p.parent.parent.parent == DSH_SESSIONS_DIR


def cwd_from_folder(name, root=Path("/")):
    """`--Users-me-code-my-app--` → /Users/me/code/my-app. Dashes are ambiguous, so walk the filesystem and
    prefer the longest existing component; a part that no longer exists keeps its remaining dashes."""
    parts = name.strip("-").split("-")
    if not parts or parts == [""]:
        return None
    cur, i = root, 0
    while i < len(parts):
        for j in range(len(parts), i, -1):
            cand = cur / "-".join(parts[i:j])
            if cand.exists() or j == i + 1:
                break
        if not cand.exists():
            return str(cur / "-".join(parts[i:]))
        cur, i = cand, j
    return str(cur)


def _events(path):
    """Complete events of a (possibly still being written) session file."""
    raw = Path(path).read_bytes()
    reader = zstandard.ZstdDecompressor().stream_reader(raw, read_across_frames=True)
    data = b""
    try:
        while chunk := reader.read(1 << 20):
            data += chunk
    except zstandard.ZstdError:
        pass  # trailing frame still being written: keep what decoded
    lines = data.split(b"\n")
    if not data.endswith(b"\n"):
        lines = lines[:-1]  # last line incomplete
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _header(events):
    return next((e for e in events if e.get("type") == "session"), {})


def _texts(content):
    return [b.get("text", "").strip() for b in content or [] if isinstance(b, dict) and b.get("type") == "text"]


def _clip(text, n=MAX_TOOL_CHARS):
    text = " ".join(str(text).split())
    return text[:n] + "…" if len(text) > n else text


def _turn(event):
    """One event → one transcript line, or None. Injected context (reminders, time, instructions) is dropped."""
    t, d = event.get("type"), event.get("data") or {}
    if t == "user/message":
        if (d.get("source") or {}).get("kind") != "user":
            return None
        text = "\n".join(_texts(d.get("content")))
        return f"User: {text}" if text else None
    if t == "assistant/message":
        text = "\n".join(_texts((d.get("message") or {}).get("content")))
        return f"Assistant: {text}" if text else None
    if t == "tool/call":
        return f"[Tool: {d.get('name', '?')}] {_clip(d.get('arguments', ''))}"
    if t == "tool/result":
        msg = d.get("message") or {}
        text = "\n".join(_texts(msg.get("content")))
        return f"[Result{' ERROR' if msg.get('isError') or d.get('isError') else ''}] {_clip(text)}" if text else None
    return None


def _last_time(events):
    """When the session last moved: episodes are dated by this, not by when the daemon got to them (backfill)."""
    times = [e["time"] for e in events if isinstance(e.get("time"), int)]
    return datetime.fromtimestamp(max(times) / 1000) if times else datetime.now()


def _delta(events, after_seq):
    turns, last = [], after_seq
    for e in events:
        seq = e.get("seq")
        if not isinstance(seq, int) or seq <= after_seq:
            continue
        last = seq
        line = _turn(e)
        if line:
            ts = datetime.fromtimestamp(e["time"] / 1000).strftime("%H:%M") if e.get("time") else "??:??"
            turns.append(f"[{ts}] {line}")
    combined = "\n\n".join(turns)
    if len(combined) > MAX_DELTA_CHARS:
        kept, total = [], 0
        for turn in reversed(turns):
            if total + len(turn) > MAX_DELTA_CHARS and kept:
                break
            kept.append(turn)
            total += len(turn)
        combined = "(earlier turns omitted)\n\n" + "\n\n".join(reversed(kept))
    # only real conversation is worth a summary; tool chatter alone is not
    if not any("] User: " in t or "] Assistant: " in t for t in turns):
        combined = ""
    return combined, last


def _session_cwd(path, header):
    """Project comes from the session folder name; the header cwd (same value, exact) breaks dash ambiguity."""
    folder = Path(path).parent.parent.name
    cwd = header.get("cwd") or ""
    if cwd and folder == f"-{cwd.replace('/', '-')}--":
        return cwd
    return cwd_from_folder(folder) or cwd


def _summary_path(config, header, path, cwd):
    project = Path(cwd).name if cwd else "dsh"
    ts = header.get("createdAt") or int(Path(path).stat().st_mtime * 1000)
    return Path(config["summary_dir"]) / f"d-{project}-{ts}.md"


class DshSessionTracker(PiSessionTracker):
    """PiSessionTracker with a dsh reader: state is {path: last seq}."""

    def __init__(self, config, call_api, consolidate):
        super().__init__(config, call_api, consolidate)
        self._state_file = Path(config["state_dir"]) / "dsh_offsets.json"
        try:
            self._offsets = json.loads(self._state_file.read_text())
        except (OSError, json.JSONDecodeError):
            self._offsets = {}

    def mark_unseen(self):
        """Queue every session never summarized (first run backfill) or changed since."""
        n = 0
        for f in DSH_SESSIONS_DIR.glob(f"*/session-*/{SESSION_FILE}"):
            self.mark(f)
            n += 1
        return n

    def _summarize(self, path, retry=False):
        path = str(path)
        last_seq = self._offsets.get(path, 0)
        events = _events(path)
        delta, new_seq = _delta(events, last_seq)
        if new_seq == last_seq:
            return True
        header = _header(events)
        cwd = _session_cwd(path, header)
        if not delta or not cwd or Path(cwd) == Path.home() or cwd.startswith(("/private/tmp", "/tmp")):
            self._save(path, new_seq)
            return True

        summary_path = _summary_path(self._config, header, path, cwd)
        previous = summary_path.read_text() if summary_path.exists() else "None — new session"
        started = datetime.fromtimestamp(header["createdAt"] / 1000).strftime("%Y-%m-%d %H:%M") if header.get("createdAt") else "?"
        user = (
            f"Previous summary:\n{previous}\n\nSession info:\n- Project: {cwd}\n- Harness: DeepSeek Harness (dsh)\n"
            f"- Session ID: {header.get('id', Path(path).parent.name)}\n- Started: {started}\n"
            f"- Now: {_last_time(events).strftime('%Y-%m-%d %H:%M')}\n\nNew conversation turns:\n{delta}"
        )
        result = self._summarize_call(user)
        if not result:
            if not retry:
                from .jobs import enqueue
                enqueue(self._config, {"type": "summarize_dsh", "path": path})
            return False

        summary_path.write_text(result.strip() + "\n")
        self._save(path, new_seq)
        logger.info("Updated dsh summary: %s", summary_path.name)
        self._consolidate(self._config, {"cwd": cwd}, summary_path, self._call_api)
        return True


def _temp_dirs():
    dirs = {tempfile.gettempdir()}
    try:  # launchd may not set TMPDIR; dsh hooks use the per-user Darwin temp dir
        dirs.add(os.confstr("CS_DARWIN_USER_TEMP_DIR"))
    except (ValueError, OSError, AttributeError):
        pass
    return [Path(d) for d in dirs if d]


def merge_recall_log(config, target=RECALL_LOG):
    """Append new lines of the dsh hook's temp auto-recall log to the shared log. Returns lines merged."""
    state_file = Path(config["state_dir"]) / "dsh_recall_log.json"
    try:
        state = json.loads(state_file.read_text())
    except (OSError, json.JSONDecodeError):
        state = {}
    merged = 0
    for d in _temp_dirs():
        src = d / RECALL_FALLBACK
        try:
            size = src.stat().st_size
        except OSError:
            continue
        key = str(src)
        offset = state.get(key, 0)
        if size < offset:
            offset = 0  # truncated/recreated
        if size == offset:
            continue
        with src.open("rb") as f:
            f.seek(offset)
            chunk = f.read()
        complete = chunk[: chunk.rfind(b"\n") + 1]
        if complete:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("ab") as out:
                out.write(complete)
            merged += complete.count(b"\n")
        state[key] = offset + len(complete)
    if merged:
        state_file.write_text(json.dumps(state))
    return merged
