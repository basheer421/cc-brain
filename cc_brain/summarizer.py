import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger("cc-brain")

SYSTEM_PROMPT = """You are a session summarizer for a developer's Claude Code sessions.
Given the previous summary (if any) and new conversation turns, produce an updated Markdown summary.
The summary is a living document — rewrite it completely each time to reflect the full session state.

Use this exact structure:

# <project-name>
**Project:** <project path>
**Session:** <session-id>
**Started:** <start timestamp>
**Last updated:** <current timestamp>

## Goal
What the user is trying to accomplish (1-2 sentences, refined as it becomes clearer)

## Progress
- Completed steps as bullet points (most recent last)

## Key Decisions
- Important choices made and their rationale

## Current State
What's happening right now / what's next (1-2 sentences)

## Files Changed
- List of files created or modified (if mentioned in conversation)
"""


def summarize(config, session_info, delta_text, previous_summary=None):
    """Call OpenRouter to produce an updated summary. Returns the markdown string or None on failure."""
    api_key = config.get("openrouter_api_key")
    if not api_key:
        logger.error("No OpenRouter API key configured")
        return None

    model = config.get("model", "deepseek/deepseek-v4-flash")

    user_msg = []
    if previous_summary:
        user_msg.append(f"Previous summary:\n{previous_summary}")
    else:
        user_msg.append("Previous summary:\nNone — new session")

    user_msg.append(f"\nSession info:\n- Project: {session_info.get('cwd', 'unknown')}")
    user_msg.append(f"- Session ID: {session_info.get('session_id', 'unknown')}")
    if session_info.get("started_at"):
        from datetime import datetime
        try:
            sa = session_info["started_at"]
            if isinstance(sa, (int, float)):
                started = datetime.fromtimestamp(sa / 1000).strftime("%Y-%m-%d %H:%M")
            elif isinstance(sa, str):
                started = sa[:16].replace("T", " ")
            else:
                started = "unknown"
        except (ValueError, TypeError, OSError):
            started = "unknown"
        user_msg.append(f"- Started: {started}")

    user_msg.append(f"\nNew conversation turns:\n{delta_text}")

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": "\n".join(user_msg)},
        ],
        "max_tokens": 2000,
        "temperature": 0.3,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/cc-brain",
        "X-Title": "cc-brain",
    }

    for attempt in range(2):
        try:
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content.strip()
        except Exception as e:
            logger.error("OpenRouter API error (attempt %d): %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(5)

    return None


def _summary_filename(session_id, session_info):
    """Generate readable filename: <project-dir-name>-<started_at_ms>.md"""
    project_name = Path(session_info.get("cwd", "unknown")).name
    started = session_info.get("started_at")
    if isinstance(started, (int, float)):
        ts = int(started)
    elif isinstance(started, str):
        from datetime import datetime
        try:
            dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            ts = int(dt.timestamp() * 1000)
        except (ValueError, TypeError):
            ts = 0
    else:
        ts = 0
    return f"{project_name}-{ts}.md"


# Maps session_id -> filename so we update the same file across calls
_filename_cache = {}


def update_summary(config, session_id, session_info, delta_text):
    """Read existing summary, call LLM, write updated summary. Returns True on success."""
    summary_dir = Path(config["summary_dir"])

    if session_id not in _filename_cache:
        filename = _summary_filename(session_id, session_info)
        _filename_cache[session_id] = filename
    summary_path = summary_dir / _filename_cache[session_id]

    previous = None
    if summary_path.exists():
        previous = summary_path.read_text()

    info = dict(session_info)
    info["session_id"] = session_id

    result = summarize(config, info, delta_text, previous)
    if result is None:
        return False

    summary_path.write_text(result)
    logger.info("Updated summary: %s", _filename_cache[session_id])
    return True
