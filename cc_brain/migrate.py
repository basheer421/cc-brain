"""One-time migration of pi-hermes-memory stores into llm-wiki pages (lossless, no LLM)."""

import re
from collections import defaultdict
from pathlib import Path

PI_MEMORY_DIR = Path.home() / ".pi" / "agent" / "pi-hermes-memory"
PI_PROJECTS_DIR = Path.home() / ".pi" / "agent" / "projects-memory"

_META = re.compile(r"\s*<!--(.*?)-->\s*$", re.S)
_CATEGORY = re.compile(r"^\[([a-z-]+)\]\s*")


def _entries(path):
    if not path.exists():
        return []
    out = []
    for raw in path.read_text().split("\n§\n"):
        text = raw.strip()
        if not text:
            continue
        date = ""
        if m := _META.search(text):
            if d := re.search(r"last=(\d{4}-\d{2}-\d{2})", m.group(1)):
                date = d.group(1)
            text = text[: m.start()].rstrip()
        out.append((text, date))
    return out


def _render(title, intro, entries):
    lines = [f"# {title}", "", intro, ""]
    for text, date in entries:
        body = text.replace("\n", "\n  ")
        lines.append(f"- {body}" + (f" _(last: {date})_" if date else ""))
    return "\n".join(lines) + "\n"


def plan(wiki_dir):
    """Return {relative_path: content} for every page to create."""
    src = "Migrated from pi-hermes-memory"
    pages = {}

    if e := _entries(PI_MEMORY_DIR / "USER.md"):
        pages["identity/user-profile.md"] = _render("User profile", f"{src} USER.md.", e)
    if e := _entries(PI_MEMORY_DIR / "MEMORY.md"):
        pages["identity/global-notes.md"] = _render("Global notes", f"{src} MEMORY.md (environment facts, conventions).", e)

    by_cat = defaultdict(list)
    for text, date in _entries(PI_MEMORY_DIR / "failures.md"):
        m = _CATEGORY.match(text)
        cat = m.group(1) if m else "uncategorized"
        by_cat[cat].append((text[m.end():] if m else text, date))
    for cat, e in sorted(by_cat.items()):
        pages[f"failures/{cat}.md"] = _render(cat.replace("-", " ").title(), f"{src} failures.md [{cat}].", e)

    if PI_PROJECTS_DIR.exists():
        for d in sorted(PI_PROJECTS_DIR.iterdir()):
            if d.is_dir() and (e := _entries(d / "MEMORY.md")):
                slug = re.sub(r"[^a-z0-9]+", "-", d.name.lower()).strip("-")
                pages[f"projects/{slug}-memory.md"] = _render(f"{d.name} — project memory", f"{src} projects-memory/{d.name}.", e)

    wiki = Path(wiki_dir)
    return {rel: body for rel, body in pages.items() if not (wiki / rel).exists()}


def apply(wiki_dir, pages):
    wiki = Path(wiki_dir)
    for rel, body in pages.items():
        p = wiki / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
