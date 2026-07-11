import json
from datetime import datetime
from pathlib import Path


STATE_FILE = Path.home() / ".cc-brain" / "state" / "offsets.json"


def _load_offsets():
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _save_offsets(offsets):
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(offsets, f)


def save_offset(session_id, offset):
    offsets = _load_offsets()
    offsets[session_id] = offset
    _save_offsets(offsets)


def get_offset(session_id):
    return _load_offsets().get(session_id, 0)


def _format_timestamp(ts):
    try:
        if isinstance(ts, (int, float)) and ts > 1_000_000_000_000:
            dt = datetime.fromtimestamp(ts / 1000)
        elif isinstance(ts, (int, float)):
            dt = datetime.fromtimestamp(ts)
        elif isinstance(ts, str):
            ts = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(ts)
        else:
            return "??:??"
        return dt.strftime("%H:%M")
    except (ValueError, TypeError, OSError):
        return "??:??"


def _extract_text_from_content(content):
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(block.get("text", "").strip())
        return "\n".join(parts)
    return ""


def _extract_text_full(content):
    """Full mode: include tool_use names and tool_result summaries."""
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if not isinstance(block, dict):
                continue
            btype = block.get("type")
            if btype == "text":
                parts.append(block.get("text", "").strip())
            elif btype == "tool_use":
                name = block.get("name", "unknown_tool")
                inp = str(block.get("input", ""))[:200]
                parts.append(f"[Tool: {name}] {inp}")
            elif btype == "tool_result":
                result_content = block.get("content", "")
                if isinstance(result_content, str):
                    parts.append(f"[Result] {result_content[:500]}")
                elif isinstance(result_content, list):
                    for rc in result_content:
                        if isinstance(rc, dict) and rc.get("type") == "text":
                            parts.append(f"[Result] {rc.get('text', '')[:500]}")
        return "\n".join(parts)
    return ""


SKIP_TYPES = {
    "last-prompt", "mode", "permission-mode", "ai-title", "hook_success",
    "file-history-snapshot", "command_permissions", "auto_mode",
    "skill_listing", "deferred_tools_delta", "agent_listing_delta",
    "mcp_instructions_delta", "plan_mode_exit", "task_reminder",
    "hook_additional_context",
}


def extract_delta(jsonl_path, session_id, mode="smart"):
    """Read new lines from jsonl_path since last offset.
    Returns (formatted_text, new_offset) or (None, current_offset) if nothing new."""
    offset = get_offset(session_id)
    path = Path(jsonl_path)

    if not path.exists():
        return None, offset

    file_size = path.stat().st_size
    if file_size <= offset:
        return None, offset

    extract_fn = _extract_text_from_content if mode == "smart" else _extract_text_full

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
            if obj_type in SKIP_TYPES:
                continue

            if obj_type not in ("user", "assistant"):
                continue

            msg = obj.get("message", {})
            content = msg.get("content", "")
            text = extract_fn(content)

            if not text or text.startswith("<command-message>"):
                continue

            # Skip tool results from user messages (they're system responses)
            if obj_type == "user" and isinstance(content, list):
                has_only_tool_results = all(
                    isinstance(b, dict) and b.get("type") in ("tool_result", "tool_reference")
                    for b in content if isinstance(b, dict)
                )
                if has_only_tool_results:
                    continue

            ts = _format_timestamp(obj.get("timestamp", 0))
            role = "User" if obj_type == "user" else "Assistant"
            turns.append(f"[{ts}] {role}: {text}")

        new_offset = f.tell()

    if not turns:
        return None, offset

    combined = "\n\n".join(turns)

    # Cap at ~8000 chars (~2000 tokens) to keep API calls fast and cheap.
    # Keep the most recent turns if we exceed the cap.
    MAX_CHARS = 8000
    if len(combined) > MAX_CHARS:
        truncated_turns = []
        total = 0
        for turn in reversed(turns):
            if total + len(turn) > MAX_CHARS and truncated_turns:
                break
            truncated_turns.append(turn)
            total += len(turn)
        truncated_turns.reverse()
        combined = "(earlier turns omitted)\n\n" + "\n\n".join(truncated_turns)

    return combined, new_offset
