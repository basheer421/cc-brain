"""Hermes session source — polls ~/.hermes/state.db (SQLite) for new messages.

Unlike Claude Code (JSONL files watched via watchdog), Hermes stores sessions
in SQLite. This module is polled on a timer from app.py. Offsets are the last
seen message id per session, stored in the shared offsets.json under keys
"hermes:<session_id>". Summary filenames get an "h-" prefix so Hermes sessions
are distinguishable from Claude Code ones in the summaries folder.
"""

import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from cc_brain.extractor import get_offset, MAX_DELTA_CHARS

logger = logging.getLogger("cc-brain")

STATE_DB = Path.home() / ".hermes" / "state.db"

# Only look at sessions with activity in the last N hours to keep polls cheap.
ACTIVE_WINDOW_HOURS = 48


def _connect():
    # Read-only: never write to Hermes's live database.
    return sqlite3.connect(f"file:{STATE_DB}?mode=ro", uri=True, timeout=5)


def _format_ts(ts):
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%H:%M")
    except (ValueError, TypeError, OSError):
        return "??:??"


def extract_hermes_deltas():
    """Return list of (offset_key, session_info, delta_text, new_offset)
    for every Hermes session with new user/assistant messages."""
    if not STATE_DB.exists():
        return []

    results = []
    try:
        conn = _connect()
    except sqlite3.Error as e:
        logger.error("Cannot open Hermes state.db: %s", e)
        return []

    try:
        conn.row_factory = sqlite3.Row
        sessions = conn.execute(
            """
            SELECT s.id, s.source, s.display_name, s.cwd, s.started_at
            FROM sessions s
            WHERE s.parent_session_id IS NULL
              AND EXISTS (
                SELECT 1 FROM messages m
                WHERE m.session_id = s.id
                  AND m.timestamp > strftime('%s','now') - ?*3600
              )
            ORDER BY s.started_at DESC
            LIMIT 50
            """,
            (ACTIVE_WINDOW_HOURS,),
        ).fetchall()

        for s in sessions:
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
                continue

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
                results.append((key, None, None, new_offset))
                continue

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
            results.append((key, info, combined, new_offset))
    except sqlite3.Error as e:
        logger.error("Hermes state.db query failed: %s", e)
    finally:
        conn.close()

    return results
