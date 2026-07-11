import logging
import time
from datetime import datetime
from pathlib import Path

import requests

logger = logging.getLogger("cc-brain")

_session = requests.Session()

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


def _format_started(sa):
    try:
        if isinstance(sa, (int, float)):
            return datetime.fromtimestamp(sa / 1000).strftime("%Y-%m-%d %H:%M")
        if isinstance(sa, str):
            return sa[:16].replace("T", " ")
    except (ValueError, TypeError, OSError):
        pass
    return "unknown"


def _call_api(config, messages):
    api_key = config.get("openrouter_api_key")
    if not api_key:
        logger.error("No OpenRouter API key configured")
        return None

    _session.headers.update({
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/cc-brain",
        "X-Title": "cc-brain",
    })

    payload = {
        "model": config.get("model", "deepseek/deepseek-v4-flash"),
        "messages": messages,
        "max_tokens": 2000,
        "temperature": 0.3,
    }

    for attempt in range(2):
        try:
            resp = _session.post(
                "https://openrouter.ai/api/v1/chat/completions",
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.error("OpenRouter API error (attempt %d): %s", attempt + 1, e)
            if attempt == 0:
                time.sleep(5)

    return None


def _build_filename(session_info):
    project_name = Path(session_info.get("cwd", "unknown")).name
    sa = session_info.get("started_at")
    if isinstance(sa, (int, float)):
        ts = int(sa)
    elif isinstance(sa, str):
        try:
            ts = int(datetime.fromisoformat(sa.replace("Z", "+00:00")).timestamp() * 1000)
        except (ValueError, TypeError):
            ts = 0
    else:
        ts = 0
    return f"{project_name}-{ts}.md"


_filename_cache = {}


def update_summary(config, session_id, session_info, delta_text):
    """Read existing summary, call LLM, write updated summary. Returns True on success."""
    summary_dir = Path(config["summary_dir"])

    if session_id not in _filename_cache:
        _filename_cache[session_id] = _build_filename(session_info)
    filename = _filename_cache[session_id]
    summary_path = summary_dir / filename

    previous = summary_path.read_text() if summary_path.exists() else None

    user_parts = []
    if previous:
        user_parts.append(f"Previous summary:\n{previous}")
    else:
        user_parts.append("Previous summary:\nNone — new session")

    user_parts.append(f"\nSession info:")
    user_parts.append(f"- Project: {session_info.get('cwd', 'unknown')}")
    user_parts.append(f"- Session ID: {session_id}")
    if sa := session_info.get("started_at"):
        user_parts.append(f"- Started: {_format_started(sa)}")
    user_parts.append(f"\nNew conversation turns:\n{delta_text}")

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]

    result = _call_api(config, messages)
    if result is None:
        return False

    summary_path.write_text(result)
    logger.info("Updated summary: %s", filename)
    return True


def get_summary_filename(session_id):
    return _filename_cache.get(session_id)
