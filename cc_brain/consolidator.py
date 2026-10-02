"""Knowledge consolidator — extracts durable knowledge from session summaries into llm-wiki.

Replaces wiki.py with a broader scope: extracts project facts, skills,
failures, and identity updates from each session summary.
"""

import json
import logging
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("cc-brain")

STATE_PATH = Path.home() / ".cc-brain" / "state" / "consolidator.json"
PAGE_SIZE_WARN = 10_000

# Optional org banner for new project pages, e.g. "infra facts belong in the org docs repo":
# config["org_banner"] = {"match": "/code/acme/", "text": "> **Acme project** — ..."}

EXTRACT_SYSTEM_PROMPT = """You are a knowledge extractor for a developer's personal wiki.

Given a session summary, extract NEW durable knowledge into structured JSON.
Only extract things that are genuinely reusable and not already covered by the
existing wiki pages provided.

Return JSON (no markdown fencing):
{
  "extractions": [
    {
      "target": "projects/brain.md",
      "section": "## Commands",
      "action": "append",
      "content": "- `pytest -x --timeout=60` — run brain tests with 60s timeout"
    }
  ]
}

If nothing new to extract, return: { "extractions": [] }

Actions:
- append: add content to the end of the specified ## section
- replace_section: replace the entire ## section with new content
- create_section: add a new ## section to the file
- create_file: create a new wiki page (provide full page content)

Categories and their target files:
- PROJECT FACTS (commands, config, architecture) → projects/<name>.md
- SKILLS (reusable step-by-step procedures) → skills/<topic>.md
- FAILURES (what didn't work, corrections, tool quirks) → failures/pitfalls.md, failures/corrections.md, or failures/tool-quirks.md
- IDENTITY (user preferences, environment changes) → identity/preferences.md or identity/environment.md

Rules:
- Be terse. Commands exact, in fenced code blocks.
- Only extract DURABLE knowledge — skip task progress, in-flight work, one-off values.
- Skills must be reusable procedures, not project-specific notes.
- Failures must include what went wrong AND why, so it's avoidable next time.
- Identity updates only on real changes (new tool installed, preference stated)."""

MERGE_SYSTEM_PROMPT = """You are merging a suggested knowledge update into an existing wiki page.

Given the current page content and a suggestion, output the UPDATED page.
Rules:
- MERGE with existing content: keep existing facts unless the suggestion contradicts them.
- If contradicted, replace and note the change.
- Keep the page structure (headings, sections) intact.
- Be terse. Commands in fenced code blocks.
- Output ONLY the full updated Markdown page (no preamble, no fencing).
- If the suggestion adds NOTHING beyond what the page already has, output exactly: NO_CHANGE"""


_LAST_STAMP = re.compile(r"\s*_\(last: [^)]*\)_\s*$")


def _norm(line):
    """Normalize a Markdown line for duplicate detection."""
    line = _LAST_STAMP.sub("", line.strip())
    line = re.sub(r"^[-*+]\s+", "", line)
    return re.sub(r"\s+", " ", line).strip().lower()


def _bullet_keys(text):
    """Normalized bullet lines outside code fences."""
    keys, in_fence = set(), False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if not in_fence and re.match(r"^\s*[-*+]\s+", line):
            keys.add(_norm(line))
    return keys


def _drop_known_bullets(content, existing_text):
    """Remove bullets from content already present in the page. Returns '' if nothing new."""
    known = _bullet_keys(existing_text)
    out, in_fence, skipping = [], False, False
    for line in content.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and re.match(r"^[-*+]\s+", line):
            skipping = _norm(line) in known
        elif not in_fence and not line.startswith((" ", "\t")):
            skipping = False
        if not skipping:
            out.append(line)
    kept = "\n".join(out).strip("\n")
    if not re.sub(r"```\w*|\s", "", kept):
        return ""
    if kept and kept.strip() in existing_text:
        return ""
    return kept


def _find_heading(text, section):
    """(start, end) of the heading line matching `section` (whole line, case/space-insensitive)."""
    want = _norm(section)
    for m in re.finditer(r"^#{2,3} .*$", text, re.MULTILINE):
        if _norm(m.group(0)) == want:
            return m.start(), m.end()
    return None


def _parse_json(result):
    """Parse LLM JSON output, tolerating fences and leading/trailing prose."""
    result = (result or "").strip()
    try:
        return json.loads(result)
    except json.JSONDecodeError:
        pass
    start = result.find("{")
    while start != -1:
        try:
            obj, _ = json.JSONDecoder().raw_decode(result[start:])
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
        start = result.find("{", start + 1)
    return None


def _load_state():
    try:
        return json.loads(STATE_PATH.read_text())
    except (OSError, ValueError):
        return {}


def _save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))


def _git(wiki_dir, *args):
    try:
        result = subprocess.run(
            ["git", *args], cwd=wiki_dir, capture_output=True, timeout=30, check=False
        )
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("wiki git %s failed: %s", args, e)
        return False


def _wiki_is_clean(wiki_dir):
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=wiki_dir, capture_output=True, timeout=10, text=True, check=False,
        )
        return result.returncode == 0 and not result.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return True


def _apply_extraction(wiki_dir, extraction):
    target = extraction.get("target", "")
    action = extraction.get("action", "append")
    section = extraction.get("section", "")
    content = extraction.get("content", "")

    if not target or not content:
        return False

    page_path = Path(wiki_dir) / target

    if action == "create_file":
        if page_path.exists():
            logger.warning("create_file but %s already exists, skipping", target)
            return False
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(content if content.endswith("\n") else content + "\n")
        return True

    if not page_path.exists():
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(f"# {Path(target).stem.replace('-', ' ').title()}\n\n{section}\n{content}\n")
        return True

    text = page_path.read_text()

    if action in ("append", "create_section") or not section:
        content = _drop_known_bullets(content, text)
        if not content:
            logger.info("Skipped duplicate extraction for %s", target)
            return False

    pos = _find_heading(text, section) if section else None
    if pos is not None:
        section = text[pos[0]:pos[1]]  # use the page's own heading spelling

    if action == "append" and section:
        if pos is not None:
            next_section = text.find("\n## ", pos[1])
            if next_section == -1:
                text = text.rstrip("\n") + "\n" + content + "\n"
            else:
                text = text[:next_section].rstrip("\n") + "\n" + content + "\n" + text[next_section:]
        else:
            text = text.rstrip("\n") + "\n\n" + section + "\n" + content + "\n"

    elif action == "replace_section" and section:
        if pos is not None:
            start = pos[0]
            next_section = text.find("\n## ", pos[1])
            if next_section == -1:
                text = text[:start] + section + "\n" + content + "\n"
            else:
                text = text[:start] + section + "\n" + content + "\n" + text[next_section:]
        else:
            text = text.rstrip("\n") + "\n\n" + section + "\n" + content + "\n"

    elif action == "create_section" and section:
        if pos is None:
            text = text.rstrip("\n") + "\n\n" + section + "\n" + content + "\n"
        else:
            next_section = text.find("\n## ", pos[1])
            if next_section == -1:
                text = text.rstrip("\n") + "\n" + content + "\n"
            else:
                text = text[:next_section].rstrip("\n") + "\n" + content + "\n" + text[next_section:]

    else:
        text = text.rstrip("\n") + "\n" + content + "\n"

    page_path.write_text(text)
    if len(text) > PAGE_SIZE_WARN:
        logger.warning("%s is %d bytes — run `cc-brain compact`", target, len(text))
    return True


def _append_changelog(wiki_dir, today, targets):
    path = Path(wiki_dir) / "changelog.md"
    try:
        text = path.read_text() if path.exists() else "# Changelog\n"
        heading = f"## {today}"
        entries = "\n".join(f"- `{t}` updated (auto-consolidate)" for t in targets)
        if heading in text:
            head, _, tail = text.partition(heading)
            text = head + heading + "\n" + entries + tail
        else:
            first = text.find("\n## ")
            block = f"\n{heading}\n{entries}\n"
            if first == -1:
                text = text.rstrip("\n") + "\n" + block
            else:
                text = text[:first] + block + text[first:]
        path.write_text(text)
    except OSError as e:
        logger.warning("Changelog write failed: %s", e)


def consolidate(config, session_info, summary_path, call_api):
    """Extract knowledge from a session summary into llm-wiki."""
    wiki_dir = Path(config.get("wiki_dir", str(Path.home() / "llm-wiki")))
    if not wiki_dir.is_dir():
        return

    cwd = session_info.get("cwd", "") or ""
    home = str(Path.home())
    if not cwd or cwd.startswith("hermes/") or Path(cwd) == Path(home):
        return

    # Rate limiting
    state = _load_state()
    now = time.time()
    project = Path(cwd).name
    rate_key = f"project:{project}"
    min_interval = config.get("consolidation_min_interval_s", 900)
    if now - state.get(rate_key, 0) < min_interval:
        return

    summary_path = Path(summary_path)
    if not summary_path.exists():
        return
    summary_text = summary_path.read_text()

    # Mark attempt time before the call
    state[rate_key] = now
    _save_state(state)

    # Check if wiki has dirty state from manual edits
    if not _wiki_is_clean(wiki_dir):
        logger.warning("Wiki has uncommitted changes, skipping consolidation")
        return

    # Gather existing page contents for dedup context
    project_slug = re.sub(r"[^a-z0-9]+", "-", project.lower()).strip("-") or "unknown"
    banner = config.get("org_banner") or {}
    org_banner = banner.get("text", "").strip() + "\n" if banner.get("match") and banner["match"] in cwd else ""
    project_page = wiki_dir / "projects" / f"{project_slug}.md"
    existing_project = project_page.read_text() if project_page.exists() else "(no page yet)"

    # Include relevant wiki pages for context
    context_pages = [f"projects/{project_slug}.md:\n{existing_project}"]
    for subdir in ("skills", "failures", "identity"):
        d = wiki_dir / subdir
        if d.exists():
            for f in d.glob("*.md"):
                try:
                    content = f.read_text()
                    if len(content) < 20000:
                        rel = f"{subdir}/{f.name}"
                        context_pages.append(f"{rel}:\n{content}")
                except OSError:
                    pass

    context_block = "\n---\n".join(context_pages)
    if len(context_block) > 50000:
        context_block = context_block[:50000] + "\n...(truncated)"

    messages = [
        {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Project: {project}\nPath: {cwd}\n"
            f"Org project: {'yes' if org_banner else 'no'}\n\n"
            f"Existing wiki pages:\n{context_block}\n\n"
            f"Session summary:\n{summary_text}"
        )},
    ]

    result = call_api(config, messages, task="consolidation", json_mode=True)
    if result is None:
        return

    data = _parse_json(result)
    if data is None:
        logger.warning("Consolidator returned non-JSON (%d chars): %.200s", len(result), result)
        return

    extractions = data.get("extractions", [])
    if not extractions:
        logger.info("No new knowledge to extract for %s", project)
        return

    applied_targets = []
    for ext in extractions:
        target = ext.get("target", "")
        if not target:
            continue

        # Add the org banner for new project pages
        if org_banner and target.startswith("projects/") and ext.get("action") == "create_file":
            content = ext.get("content", "")
            if org_banner.strip() not in content:
                lines = content.split("\n")
                insert_at = 1 if lines and lines[0].startswith("#") else 0
                lines.insert(insert_at, "\n" + org_banner)
                ext["content"] = "\n".join(lines)

        if _apply_extraction(wiki_dir, ext):
            applied_targets.append(target)
            logger.info("Applied extraction to %s (%s)", target, ext.get("action", "?"))

    if applied_targets:
        today = datetime.now().strftime("%Y-%m-%d")
        _append_changelog(wiki_dir, today, applied_targets)
        _git(wiki_dir, "add", "-A")
        _git(wiki_dir, "commit", "-q", "-m",
             f"consolidate: {', '.join(set(applied_targets))} ({today})")
        logger.info("Consolidated %d extractions for %s", len(applied_targets), project)

    return applied_targets


def process_suggestion(config, suggestion, call_api):
    """Process a queued agent suggestion by merging it into the wiki."""
    wiki_dir = Path(config.get("wiki_dir", str(Path.home() / "llm-wiki")))
    target = suggestion.get("target", "")
    content = suggestion.get("content", "")
    suggest_type = suggestion.get("type", "add")

    if not target or not content:
        return False

    if not _wiki_is_clean(wiki_dir):
        logger.warning("Wiki dirty, deferring suggestion for %s", target)
        return False

    page_path = wiki_dir / target

    if target == "auto":
        # Let the LLM decide the target
        messages = [
            {"role": "system", "content": EXTRACT_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"A user agent suggests adding this knowledge:\n{content}\n\n"
                f"Type: {suggest_type}\n\n"
                "Determine the correct target file and return a single extraction."
            )},
        ]
        result = call_api(config, messages, task="consolidation", json_mode=True)
        if result is None:
            return False
        try:
            data = _parse_json(result)
            if data is None:
                raise json.JSONDecodeError("no JSON object", result, 0)
            extractions = data.get("extractions", [])
            if extractions:
                ext = extractions[0]
                if _apply_extraction(wiki_dir, ext):
                    _git(wiki_dir, "add", "-A")
                    today = datetime.now().strftime("%Y-%m-%d")
                    _git(wiki_dir, "commit", "-q", "-m",
                         f"suggest: {ext.get('target', target)} ({today})")
                    return True
        except (json.JSONDecodeError, KeyError):
            logger.warning("Auto-target suggestion returned bad JSON")
        return False

    # Known target — merge with LLM
    existing = page_path.read_text() if page_path.exists() else ""

    if not existing:
        page_path.parent.mkdir(parents=True, exist_ok=True)
        page_path.write_text(content if content.endswith("\n") else content + "\n")
    elif suggest_type == "add":
        # Append-only: an LLM rewrite of a large page truncates it.
        today = datetime.now().strftime("%Y-%m-%d")
        entry = "- " + content.strip().replace("\n", "\n  ") + f" _(last: {today})_\n"
        if _norm(entry.splitlines()[0]) in _bullet_keys(existing):
            logger.info("Suggestion for %s already present, skipping", target)
            return True
        page_path.write_text(existing.rstrip("\n") + "\n" + entry)
    else:
        messages = [
            {"role": "system", "content": MERGE_SYSTEM_PROMPT},
            {"role": "user", "content": (
                f"Current page ({target}):\n{existing}\n\n"
                f"Suggestion ({suggest_type}):\n{content}"
            )},
        ]
        result = call_api(config, messages, task="consolidation")
        if result is None:
            return False
        result = result.strip()
        if not result or result == "NO_CHANGE":
            logger.info("Suggestion adds nothing new to %s", target)
            return True
        if len(result) < 0.9 * len(existing):
            logger.warning("Merge for %s shrank page %d -> %d chars, rejected", target, len(existing), len(result))
            return True  # drop from queue; page untouched
        page_path.write_text(result if result.endswith("\n") else result + "\n")

    _git(wiki_dir, "add", "-A")
    today = datetime.now().strftime("%Y-%m-%d")
    _git(wiki_dir, "commit", "-q", "-m", f"suggest: {target} ({today})")
    logger.info("Applied suggestion to %s", target)
    return True
