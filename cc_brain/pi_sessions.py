"""Pi session source: ~/.pi/agent/sessions/<encoded-cwd>/<ts>_<id>.jsonl → rolling summary → consolidation."""

import json
import logging
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("cc-brain")

PI_SESSIONS_DIR = Path.home() / ".pi" / "agent" / "sessions"
MAX_DELTA_CHARS = 60000
QUIET_SECONDS = 120
MAX_STALE_SECONDS = 900

SUMMARY_PROMPT = """You are a session summarizer for a developer's coding-agent sessions.
Given the previous summary (if any) and new conversation turns, produce an updated Markdown summary.
Rewrite it completely each time to reflect the full session state.

Use this exact structure:

# <project-name>
**Project:** <project path>
**Session:** <session-id>
**Started:** <start timestamp>
**Last updated:** <current timestamp>

## Goal
What the user is trying to accomplish (1-2 sentences)

## Progress
- Completed steps (most recent last)

## Key Decisions
- Important choices made and their rationale

## Current State
What's happening now / what's next (1-2 sentences)

## Files Changed
- Files created or modified
"""


def is_session_file(path):
    p = Path(path)
    return p.suffix == ".jsonl" and p.parent.parent == PI_SESSIONS_DIR


def _header(path):
    try:
        with open(path) as f:
            obj = json.loads(f.readline())
        return obj if obj.get("type") == "session" else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _text(content):
    if isinstance(content, str):
        return content.strip()
    parts = []
    for b in content or []:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            parts.append(b.get("text", "").strip())
        elif t in ("toolCall", "tool_use"):
            args = b.get("arguments", b.get("input", ""))
            parts.append(f"[Tool: {b.get('name', '?')}] {str(args)[:200]}")
    return "\n".join(p for p in parts if p)


def _has_text(content):
    if isinstance(content, str):
        return bool(content.strip())
    return any(isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip() for b in content or [])


def _delta(path, offset):
    turns = []
    with open(path) as f:
        f.seek(offset)
        for line in f:
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if obj.get("type") != "message":
                continue
            msg = obj.get("message", {})
            role = msg.get("role")
            if role not in ("user", "assistant") or not _has_text(msg.get("content")):
                continue
            text = _text(msg.get("content"))
            if not text:
                continue
            ts = str(obj.get("timestamp", ""))[11:16] or "??:??"
            turns.append(f"[{ts}] {'User' if role == 'user' else 'Assistant'}: {text}")
        new_offset = f.tell()

    combined = "\n\n".join(turns)
    if len(combined) > MAX_DELTA_CHARS:
        kept, total = [], 0
        for turn in reversed(turns):
            if total + len(turn) > MAX_DELTA_CHARS and kept:
                break
            kept.append(turn)
            total += len(turn)
        combined = "(earlier turns omitted)\n\n" + "\n\n".join(reversed(kept))
    return combined, new_offset


def _summary_path(config, header, path):
    cwd = header.get("cwd", "")
    project = Path(cwd).name if cwd else "pi"
    try:
        ts = int(datetime.fromisoformat(header["timestamp"].replace("Z", "+00:00")).timestamp() * 1000)
    except (KeyError, ValueError, AttributeError):
        ts = int(Path(path).stat().st_mtime * 1000)
    return Path(config["summary_dir"]) / f"p-{project}-{ts}.md"


class PiSessionTracker:
    """Marks sessions dirty on file events; summarizes them once they go quiet."""

    def __init__(self, config, call_api, consolidate):
        self._config = config
        self._call_api = call_api
        self._consolidate = consolidate
        self._state_file = Path(config["state_dir"]) / "pi_offsets.json"
        try:
            self._offsets = json.loads(self._state_file.read_text())
        except (OSError, json.JSONDecodeError):
            self._offsets = {}
        self._dirty = {}

    def mark(self, path):
        self._dirty.setdefault(str(path), time.time())

    def process(self):
        now = time.time()
        for path, first_seen in list(self._dirty.items()):
            try:
                mtime = Path(path).stat().st_mtime
            except OSError:
                self._dirty.pop(path)
                continue
            if now - mtime < QUIET_SECONDS and now - first_seen < MAX_STALE_SECONDS:
                continue
            self._dirty.pop(path)
            try:
                self._summarize(path)
            except Exception:
                logger.exception("Pi summary failed for %s", path)

    def _summarize(self, path):
        offset = self._offsets.get(path, 0)
        if Path(path).stat().st_size <= offset:
            return
        delta, new_offset = _delta(path, offset)
        if not delta:
            self._save(path, new_offset)
            return

        header = _header(path)
        cwd = header.get("cwd", "")
        if not cwd or Path(cwd) == Path.home() or cwd.startswith("/private/tmp"):
            self._save(path, new_offset)
            return

        summary_path = _summary_path(self._config, header, path)
        previous = summary_path.read_text() if summary_path.exists() else "None — new session"
        user = (
            f"Previous summary:\n{previous}\n\nSession info:\n- Project: {cwd}\n"
            f"- Session ID: {header.get('id', '?')}\n- Started: {header.get('timestamp', '?')[:16]}\n"
            f"- Now: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\nNew conversation turns:\n{delta}"
        )
        result = self._call_api(
            self._config,
            [{"role": "system", "content": SUMMARY_PROMPT}, {"role": "user", "content": user}],
            task="summarization",
        )
        if not result:
            return  # offset not advanced → retried on next change

        summary_path.write_text(result.strip() + "\n")
        self._save(path, new_offset)
        logger.info("Updated Pi summary: %s", summary_path.name)
        self._consolidate(self._config, {"cwd": cwd}, summary_path, self._call_api)

    def _save(self, path, offset):
        self._offsets[path] = offset
        self._state_file.write_text(json.dumps(self._offsets))
