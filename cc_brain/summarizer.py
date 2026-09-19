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


def _endpoints(config):
    """Ordered (base_url, api_key, model, extra_body) endpoints: primary, then fallback."""
    eps = []
    primary_key = config.get("api_key") or config.get("openrouter_api_key")
    if primary_key:
        eps.append((
            config.get("api_base_url", "https://openrouter.ai/api/v1"),
            primary_key,
            config.get("model", "deepseek/deepseek-v4-flash"),
            config.get("extra_body", {}),
        ))
    # Fallback: OpenRouter, used when the primary (e.g. local vLLM on the
    # tailnet) is unreachable — laptop off-network, server down, etc.
    or_key = config.get("openrouter_api_key")
    if or_key and config.get("api_base_url"):  # only if primary differs
        eps.append((
            "https://openrouter.ai/api/v1",
            or_key,
            config.get("fallback_model", "deepseek/deepseek-v4-flash"),
            {},
        ))
    return eps


def _call_api(config, messages):
    endpoints = _endpoints(config)
    if not endpoints:
        logger.error("No API key configured")
        return None

    for base_url, api_key, model, extra_body in endpoints:
        payload = {
            "model": model,
            "messages": messages,
            "max_tokens": config.get("max_tokens", 2000),
            "temperature": 0.3,
        }
        payload.update(extra_body)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/cc-brain",
            "X-Title": "cc-brain",
        }
        headers.update(config.get("extra_headers", {}))

        for attempt in range(2):
            try:
                resp = _session.post(
                    f"{base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=60,
                )
                resp.raise_for_status()
                msg = resp.json()["choices"][0]["message"]
                text = msg.get("content") or msg.get("reasoning_content") or ""
                return text.strip()
            except Exception as e:
                logger.error("API error %s (attempt %d): %s", base_url, attempt + 1, e)
                if attempt == 0:
                    time.sleep(5)
        logger.warning("Endpoint %s failed, trying fallback", base_url)

    return None


def _build_filename(session_info):
    project_name = Path(session_info.get("cwd", "unknown")).name
    prefix = session_info.get("filename_prefix", "")
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
    return f"{prefix}{project_name}-{ts}.md"


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
