"""Pi session source — file-watch on ~/.pi/agent/sessions/.

Pi stores sessions as JSONL files at:
    ~/.pi/agent/sessions/<encoded-cwd>/<timestamp_id>.jsonl

Message format differs from Claude Code:
    {"type": "message", "message": {"role": "user"|"assistant"|"toolResult", "content": [...]}}

Subagent runs live in subdirs (e.g. <uuid>/run-0/session.jsonl) and forks in
forks/ — we only watch top-level (maxdepth 2) session files to avoid noise.

Offsets use "pi:<session_id>" keys. Summary filenames get a "p-" prefix.
"""

import json
import logging
from datetime import datetime
from pathlib import Path

from cc_brain.extractor import get_offset, MAX_DELTA_CHARS

logger = logging.getLogger("cc-brain")

PI_SESSIONS_DIR = Path.home() / ".pi" / "agent" / "sessions"

_SKIP_ROLES = frozenset({"toolResult", "toolUse"})

STALE_THRESHOLD = 3600  # ignore sessions not written to in the last hour


def _format_timestamp(ts):
    try:
        if isinstance(ts, str):
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M")
        if isinstance(ts, (int, float)) and ts > 1_000_000_000_000:
            return datetime.fromtimestamp(ts / 1000).strftime("%H:%M")
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts).strftime("%H:%M")
    except (ValueError, TypeError, OSError):
        pass
    return "??:??"


def _extract_text(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text":
                parts.append(b.get("text", "").strip())
            elif t == "tool_use":
                parts.append(f"[Tool: {b.get('name', '?')}] {str(b.get('input', ''))[:200]}")
        return "\n".join(parts)
    return ""


def _decode_cwd(encoded):
    """Reverse the --path--component-- encoding back to /path/component."""
    if encoded.startswith("--") and encoded.endswith("--"):
        encoded = encoded[2:-2]
    elif encoded.startswith("--"):
        encoded = encoded[2:]
    return "/" + encoded.replace("-", "/")


def _read_session_header(jsonl_path):
    """Read the first line to get session metadata."""
    try:
        with open(jsonl_path) as f:
            first = f.readline().strip()
            if first:
                obj = json.loads(first)
                if obj.get("type") == "session":
                    return obj
    except (json.JSONDecodeError, OSError):
        pass
    return None


def discover_pi_sessions():
    """Find recently-active Pi sessions (top-level JSONLs only).
    Returns dict of {offset_key: {cwd, name, jsonl_path, started_at, filename_prefix}}."""
    sessions = {}
    if not PI_SESSIONS_DIR.exists():
        return sessions

    import time
    now = time.time()

    for cwd_dir in PI_SESSIONS_DIR.iterdir():
        if not cwd_dir.is_dir():
            continue
        for jsonl in cwd_dir.glob("*.jsonl"):
            try:
                mtime = jsonl.stat().st_mtime
                if now - mtime > STALE_THRESHOLD:
                    continue
            except OSError:
                continue

            header = _read_session_header(jsonl)
            cwd = header.get("cwd", "") if header else _decode_cwd(cwd_dir.name)
            session_id = header.get("id", jsonl.stem) if header else jsonl.stem

            key = f"pi:{session_id}"
            sessions[key] = {
                "cwd": cwd,
                "name": Path(cwd).name if cwd else "pi",
                "jsonl_path": str(jsonl),
                "started_at": header.get("timestamp", "") if header else "",
                "filename_prefix": "p-",
            }

    return sessions


def extract_pi_delta(jsonl_path, offset_key):
    """Read new lines from a Pi session JSONL since last offset.
    Returns (delta_text, new_offset) or (None, old_offset)."""
    offset = get_offset(offset_key)
    path = Path(jsonl_path)

    if not path.exists():
        return None, offset

    try:
        if path.stat().st_size <= offset:
            return None, offset
    except OSError:
        return None, offset

    turns = []

    with open(path, "r") as f:
        f.seek(offset)
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            if obj.get("type") != "message":
                continue

            msg = obj.get("message", {})
            role = msg.get("role", "")

            if role in _SKIP_ROLES:
                continue
            if role not in ("user", "assistant"):
                continue

            content = msg.get("content", "")

            # Skip user turns that are purely tool results
            if role == "user" and isinstance(content, list):
                if all(
                    isinstance(b, dict) and b.get("type") in ("tool_result", "tool_reference")
                    for b in content if isinstance(b, dict)
                ):
                    continue

            text = _extract_text(content)
            if not text:
                continue

            # Skip thinking-only assistant turns
            if role == "assistant" and isinstance(content, list):
                has_text = any(
                    isinstance(b, dict) and b.get("type") == "text" and b.get("text", "").strip()
                    for b in content
                )
                if not has_text:
                    continue

            ts = _format_timestamp(obj.get("timestamp", ""))
            label = "User" if role == "user" else "Assistant"
            turns.append(f"[{ts}] {label}: {text}")

        new_offset = f.tell()

    if not turns:
        return None, offset

    combined = "\n\n".join(turns)
    if len(combined) > MAX_DELTA_CHARS:
        truncated = []
        total = 0
        for turn in reversed(turns):
            if total + len(turn) > MAX_DELTA_CHARS and truncated:
                break
            truncated.append(turn)
            total += len(turn)
        truncated.reverse()
        combined = "(earlier turns omitted)\n\n" + "\n\n".join(truncated)

    return combined, new_offset
