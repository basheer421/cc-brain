"""Wiki distiller — stage 2 of cc-brain.

After a session summary updates, distill durable knowledge (commands,
pitfalls, decisions, config facts) into ~/llm-wiki/projects/<project>.md.
Rate-limited per project; auto-commits the wiki repo (local git only).

G137 repos (~/code/g137/*) still get a wiki page, but with a promotion
banner — durable infra facts belong in infra-docs via MR.
"""

import json
import logging
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("cc-brain")

STATE_PATH = Path.home() / ".cc-brain" / "state" / "wiki_distill.json"

NO_CHANGE = "NO_CHANGE"

G137_BANNER = (
    "> **G137 project** — durable *infra* facts belong in "
    "`~/code/g137/infra-docs` (promote via MR). This page holds "
    "session-level working knowledge only.\n"
)

DISTILL_SYSTEM_PROMPT = """You are a knowledge distiller for a developer's personal wiki.

You receive: (1) the current wiki page for a project (may be empty), and
(2) a living summary of a work session on that project.

Your job: output the UPDATED wiki page containing only DURABLE knowledge:
- exact commands that work (build, deploy, restart, test)
- pitfalls and gotchas discovered
- decisions made and their rationale
- stable config facts (paths, ports, service names)

Rules:
- Page structure: title, then `## Summary`, `## Commands`, `## Pitfalls`,
  `## Decisions` (omit empty sections). Keep any existing banner blockquote
  at the top unchanged.
- MERGE with the existing page: keep existing facts unless the session
  contradicts them; then replace and note the change.
- EXCLUDE: task progress, in-flight work, chat narration, one-off values,
  anything that will be stale in a week.
- Be terse. Commands exact, in fenced code blocks.
- If the session adds NOTHING durable beyond what the page already has,
  output exactly: NO_CHANGE
- Otherwise output ONLY the full updated Markdown page (no preamble)."""


def _load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))


def _slug(name):
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "unknown"


def _git(wiki_dir, *args):
    try:
        subprocess.run(
            ["git", *args], cwd=wiki_dir, capture_output=True, timeout=30, check=False
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("wiki git %s failed: %s", args, e)


def maybe_distill(config, session_id, session_info, summary_path, call_api):
    """Distill a session summary into the wiki. Rate-limited per project.

    call_api: callable(config, messages) -> str | None (shared with summarizer,
    already handles fallback endpoints).
    """
    wiki_dir = Path(config.get("wiki_dir", str(Path.home() / "llm-wiki"))).expanduser()
    if not wiki_dir.is_dir():
        return

    cwd = session_info.get("cwd", "") or ""
    project = Path(cwd).name if cwd else "unknown"
    if project in ("unknown", "") or cwd.startswith("hermes/"):
        return

    min_interval = config.get("wiki_distill_min_interval_s", 900)
    state = _load_state()
    now = time.time()
    key = _slug(project)
    if now - state.get(key, 0) < min_interval:
        return

    summary_path = Path(summary_path)
    if not summary_path.exists():
        return
    summary_text = summary_path.read_text()

    page_path = wiki_dir / "projects" / f"{key}.md"
    existing = page_path.read_text() if page_path.exists() else ""
    is_g137 = "/code/g137/" in cwd

    user_parts = [
        f"Project: {project}",
        f"Path: {cwd}",
        f"\nCurrent wiki page ({page_path.name}):\n{existing or '(none — new page)'}",
        f"\nSession summary:\n{summary_text}",
    ]
    messages = [
        {"role": "system", "content": DISTILL_SYSTEM_PROMPT},
        {"role": "user", "content": "\n".join(user_parts)},
    ]

    # Mark attempt time BEFORE the call so failures don't cause hot retry loops.
    state[key] = now
    _save_state(state)

    result = call_api(config, messages)
    if result is None:
        return
    result = result.strip()
    if not result or result == NO_CHANGE or result.startswith(NO_CHANGE):
        logger.info("wiki: no durable change for %s", key)
        return

    is_new = not page_path.exists()
    if is_g137 and G137_BANNER.strip() not in result:
        lines = result.split("\n")
        insert_at = 1 if lines and lines[0].startswith("#") else 0
        lines.insert(insert_at, "\n" + G137_BANNER)
        result = "\n".join(lines)

    page_path.parent.mkdir(parents=True, exist_ok=True)
    page_path.write_text(result if result.endswith("\n") else result + "\n")

    today = datetime.now().strftime("%Y-%m-%d")
    _append_changelog(wiki_dir, today, key, is_new)
    if is_new:
        _add_to_index(wiki_dir, key)

    _git(wiki_dir, "add", "-A")
    _git(wiki_dir, "commit", "-q", "-m", f"distill: {key} ({today})")
    logger.info("wiki: updated projects/%s.md%s", key, " (new)" if is_new else "")


def _append_changelog(wiki_dir, today, key, is_new):
    path = wiki_dir / "changelog.md"
    entry = f"- `projects/{key}.md` {'created' if is_new else 'updated'} (auto-distill)"
    try:
        text = path.read_text() if path.exists() else "# Changelog\n"
        heading = f"## {today}"
        if heading in text:
            head, _, tail = text.partition(heading)
            # Skip duplicate entry within today's section.
            if entry in tail.split("\n## ")[0]:
                return
            text = head + heading + "\n" + entry + tail
        else:
            # New day section goes above the first existing day heading.
            first = text.find("\n## ")
            block = f"\n{heading}\n{entry}\n"
            if first == -1:
                text = text.rstrip("\n") + "\n" + block
            else:
                text = text[:first] + block + text[first:]
        path.write_text(text)
    except OSError as e:
        logger.warning("wiki changelog write failed: %s", e)


def _add_to_index(wiki_dir, key):
    path = wiki_dir / "index.md"
    line = f"- [{key}](projects/{key}.md)"
    try:
        text = path.read_text() if path.exists() else "# LLM Wiki\n\n## Index\n"
        if f"projects/{key}.md" in text:
            return
        marker = "### Private projects"
        if marker in text:
            text = text.replace(marker, marker + "\n" + line, 1)
        else:
            text = text.rstrip("\n") + "\n" + line + "\n"
        path.write_text(text)
    except OSError as e:
        logger.warning("wiki index write failed: %s", e)
