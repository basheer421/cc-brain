"""Deterministic wiki compaction — merge duplicate ## sections, drop duplicate bullets.

No LLM: an LLM rewrite of a large page truncates it. This only removes exact
(normalized) repeats, so it can never lose unique content.
"""

import re
from pathlib import Path

from .consolidator import _norm

_BULLET = re.compile(r"^[-*+]\s+")


def _split_sections(text):
    """-> (preamble, [(heading, body_lines)]) splitting on top-level '## ' outside fences."""
    preamble, sections, cur, in_fence = [], [], None, False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
        if not in_fence and line.startswith("## "):
            cur = (line.rstrip(), [])
            sections.append(cur)
            continue
        (cur[1] if cur else preamble).append(line)
    return preamble, sections


def _dedup_bullets(lines, seen):
    """Drop top-level bullets (with their indented continuation) already in `seen`."""
    out, in_fence, skipping = [], False, False
    for line in lines:
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            if not skipping:
                out.append(line)
            continue
        if not in_fence and _BULLET.match(line):
            key = _norm(line)
            skipping = key in seen
            seen.add(key)
        elif not in_fence and line.strip() and not line.startswith((" ", "\t")):
            skipping = False
        if not skipping:
            out.append(line)
    return out


def _trim(lines):
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return lines


def compact_text(text):
    preamble, sections = _split_sections(text)
    merged, order = {}, []
    for heading, body in sections:
        key = _norm(heading)
        if key not in merged:
            merged[key] = [heading, []]
            order.append(key)
        merged[key][1].extend([""] + body)

    seen = set()
    parts = ["\n".join(_trim(_dedup_bullets(preamble, seen)))]
    for key in order:
        heading, body = merged[key]
        body = _trim(_dedup_bullets(body, seen))
        parts.append(heading + ("\n\n" + "\n".join(body) if body else ""))
    out = "\n\n".join(p for p in parts if p.strip())
    return re.sub(r"\n{3,}", "\n\n", out).rstrip("\n") + "\n"


def compact_wiki(wiki_dir, write=False):
    """Returns [(rel_path, before_bytes, after_bytes)] for pages that would change."""
    wiki_dir = Path(wiki_dir)
    changes = []
    for page in sorted(wiki_dir.rglob("*.md")):
        rel = page.relative_to(wiki_dir)
        if rel.parts[0].startswith(".") or rel.name == "changelog.md":
            continue
        before = page.read_text()
        after = compact_text(before)
        if after != before:
            changes.append((str(rel), len(before), len(after)))
            if write:
                page.write_text(after)
    return changes
