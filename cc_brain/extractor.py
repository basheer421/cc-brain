import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

STATE_FILE = Path.home() / ".cc-brain" / "state" / "offsets.json"

_offsets_cache = None


def _load_offsets():
    global _offsets_cache
    if _offsets_cache is not None:
        return _offsets_cache
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                _offsets_cache = json.load(f)
                return _offsets_cache
        except (json.JSONDecodeError, OSError):
            pass
    _offsets_cache = {}
    return _offsets_cache


def _save_offsets():
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Atomic write — write to temp file then rename
    fd, tmp = tempfile.mkstemp(dir=STATE_FILE.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(_offsets_cache, f)
        os.replace(tmp, STATE_FILE)
    except Exception:
        os.unlink(tmp)
        raise


def save_offset(session_id, offset):
    _load_offsets()
    _offsets_cache[session_id] = offset
    _save_offsets()


def get_offset(session_id):
    return _load_offsets().get(session_id, 0)


def _format_timestamp(ts):
    try:
        if isinstance(ts, (int, float)) and ts > 1_000_000_000_000:
            return datetime.fromtimestamp(ts / 1000).strftime("%H:%M")
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts).strftime("%H:%M")
        if isinstance(ts, str):
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).strftime("%H:%M")
    except (ValueError, TypeError, OSError):
        pass
    return "??:??"


def _extract_text_smart(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        return "\n".join(
            b.get("text", "").strip()
            for b in content
            if isinstance(b, dict) and b.get("type") == "text"
        )
    return ""


def _extract_text_full(content):
    if isinstance(content, str):
        return content.strip()
    if not isinstance(content, list):
        return ""
    parts = []
    for b in content:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            parts.append(b.get("text", "").strip())
        elif t == "tool_use":
            parts.append(f"[Tool: {b.get('name', '?')}] {str(b.get('input', ''))[:200]}")
        elif t == "tool_result":
            rc = b.get("content", "")
            if isinstance(rc, str):
                parts.append(f"[Result] {rc[:500]}")
            elif isinstance(rc, list):
                for item in rc:
                    if isinstance(item, dict) and item.get("type") == "text":
                        parts.append(f"[Result] {item.get('text', '')[:500]}")
    return "\n".join(parts)


_SKIP_TYPES = frozenset({
    "last-prompt", "mode", "permission-mode", "ai-title", "hook_success",
    "file-history-snapshot", "command_permissions", "auto_mode",
    "skill_listing", "deferred_tools_delta", "agent_listing_delta",
    "mcp_instructions_delta", "plan_mode_exit", "task_reminder",
    "hook_additional_context",
})

MAX_DELTA_CHARS = 8000


def extract_delta(jsonl_path, session_id, mode="smart"):
    """Read new lines since last offset. Returns (text, new_offset) or (None, old_offset)."""
    offset = get_offset(session_id)
    path = Path(jsonl_path)

    if not path.exists():
        return None, offset

    try:
        if path.stat().st_size <= offset:
            return None, offset
    except OSError:
        return None, offset

    extract_fn = _extract_text_smart if mode == "smart" else _extract_text_full
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

            obj_type = obj.get("type")
            if obj_type in _SKIP_TYPES or obj_type not in ("user", "assistant"):
                continue

            msg = obj.get("message", {})
            content = msg.get("content", "")

            if obj_type == "user" and isinstance(content, list):
                if all(
                    isinstance(b, dict) and b.get("type") in ("tool_result", "tool_reference")
                    for b in content if isinstance(b, dict)
                ):
                    continue

            text = extract_fn(content)
            if not text or text.startswith("<command-message>"):
                continue

            ts = _format_timestamp(obj.get("timestamp", 0))
            role = "User" if obj_type == "user" else "Assistant"
            turns.append(f"[{ts}] {role}: {text}")

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
