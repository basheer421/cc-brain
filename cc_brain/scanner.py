import json
import os
from pathlib import Path


SESSIONS_DIR = Path.home() / ".claude" / "sessions"
PROJECTS_DIR = Path.home() / ".claude" / "projects"


def _is_process_alive(pid):
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def _encode_cwd(cwd):
    return cwd.replace("/", "-")


def discover_active_sessions():
    """Scan ~/.claude/sessions/*.json for sessions with a live PID.
    Returns dict of {session_id: {cwd, name, jsonl_path, project_dir}}."""
    sessions = {}
    if not SESSIONS_DIR.exists():
        return sessions

    for f in SESSIONS_DIR.glob("*.json"):
        try:
            with open(f) as fh:
                data = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue

        pid = data.get("pid")
        session_id = data.get("sessionId")
        cwd = data.get("cwd", "")

        if not pid or not session_id or not _is_process_alive(pid):
            continue

        encoded_cwd = _encode_cwd(cwd)
        project_dir = PROJECTS_DIR / encoded_cwd
        jsonl_path = project_dir / f"{session_id}.jsonl"

        if not jsonl_path.exists():
            continue

        sessions[session_id] = {
            "cwd": cwd,
            "name": data.get("name", Path(cwd).name),
            "jsonl_path": str(jsonl_path),
            "project_dir": str(project_dir),
            "pid": pid,
            "started_at": data.get("startedAt"),
        }

    return sessions
