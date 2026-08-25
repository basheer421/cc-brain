"""Hermes session source — event-driven via ~/.cc-brain/triggers/.

A Hermes shell hook (post_llm_call → ~/.hermes/agent-hooks/ccbrain-notify.sh)
touches ~/.cc-brain/triggers/hermes-<session_id> after every agent turn.
cc-brain watches that directory with watchdog and reads only the named
session's new messages from ~/.hermes/state.db (SQLite, read-only).

Offsets are the last seen message id per session, stored in the shared
offsets.json under keys "hermes:<session_id>". Summary filenames get an
"h-" prefix so Hermes sessions are distinguishable from Claude Code ones.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from cc_brain.extractor import get_offset, MAX_DELTA_CHARS

logger = logging.getLogger("cc-brain")

STATE_DB = Path.home() / ".hermes" / "state.db"
TRIGGERS_DIR = Path.home() / ".cc-brain" / "triggers"


def _connect():
    # Read-only: never write to Hermes's live database.
    return sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=5)


def _format_ts(ts):
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%H:%M")
    except (ValueError, TypeError, OSError):
        return "??:??"


def extract_hermes_delta(session_id):
    """Read new user/assistant messages for one Hermes session.
    Returns (offset_key, session_info, delta_text, new_offset) or None."""
    if not STATE_DB.exists():
        return None

    try:
        conn = _connect()
    except sqlite3.Error as e:
        logger.error("Cannot open Hermes state.db: %s", e)
        return None

    try:
        conn.row_factory = sqlite3.Row
        s = conn.execute(
            "SELECT id, source, display_name, cwd, started_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if s is None:
            return None

        key = f"hermes:{s['id']}"
        offset = get_offset(key)

        rows = conn.execute(
            """
            SELECT id, role, content, timestamp FROM messages
            WHERE session_id = ? AND id > ?
              AND role IN ('user', 'assistant')
              AND content IS NOT NULL AND content != ''
            ORDER BY id
            """,
            (s["id"], offset),
        ).fetchall()

        if not rows:
            return None

        turns = []
        for r in rows:
            text = (r["content"] or "").strip()
            if not text or text.startswith("[System:"):
                continue
            role = "User" if r["role"] == "user" else "Assistant"
            turns.append(f"[{_format_ts(r['timestamp'])}] {role}: {text}")

        new_offset = rows[-1]["id"]
        if not turns:
            # Only system/noise messages — advance offset silently.
            return (key, None, None, new_offset)

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

        cwd = s["cwd"] or ""
        name = s["display_name"] or (Path(cwd).name if cwd else "hermes")
        started_ms = int(float(s["started_at"]) * 1000) if s["started_at"] else 0

        info = {
            "cwd": cwd or f"hermes/{s['source'] or 'unknown'}",
            "name": name,
            "started_at": started_ms,
            "filename_prefix": "h-",
        }
        return (key, info, combined, new_offset)
    except sqlite3.Error as e:
        logger.error("Hermes state.db query failed: %s", e)
        return None
    finally:
        conn.close()
