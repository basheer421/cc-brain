"""Lossless one-shot migration: llm-wiki pages (v2) -> facts in brain.db (v3).

Every top-level bullet (with its continuation lines) becomes one fact. Section prose and
fenced code that is not part of a bullet becomes a `note` fact so nothing is lost.
"""

import re
import time
from datetime import datetime
from pathlib import Path

_STAMP = re.compile(r"\s*_\(last: (\d{4}-\d{2}-\d{2})\)_\s*$")
_TAG = re.compile(r"^\[(tool-quirk|correction|insight|failure|convention|preference|pitfall)\]\s*", re.I)

FAILURE_KINDS = {
    "pitfalls": "pitfall", "pitfall": "pitfall", "failure": "pitfall",
    "tool-quirk": "pitfall", "tool-quirks": "pitfall",
    "correction": "correction", "corrections": "correction",
    "insight": "fact", "convention": "decision", "preference": "preference",
    "uncategorized": "note",
}
SECTION_KINDS = [
    (re.compile(r"pitfall|quirk|gotcha|failure|lesson", re.I), "pitfall"),
    (re.compile(r"decision|why", re.I), "decision"),
    (re.compile(r"command|workflow|procedure|how to|runbook|testing", re.I), "procedure"),
    (re.compile(r"preference|style", re.I), "preference"),
    (re.compile(r"correction", re.I), "correction"),
]
IMPORTANCE = {"correction": 3, "preference": 3, "pitfall": 2, "decision": 2}


def _page_items(text):
    """Yield (section, text, is_bullet) from a markdown page."""
    section = ""
    cur, cur_bullet = [], False
    in_fence = False

    def flush():
        body = "\n".join(cur).strip()
        if body and not body.startswith("Migrated from") and not body.startswith(">"):
            yield section, body, cur_bullet

    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            cur.append(line)
            continue
        if in_fence:
            cur.append(line)
            continue
        if line.startswith("# "):
            continue
        if re.match(r"^#{2,4} ", line):
            yield from flush()
            cur, cur_bullet = [], False
            section = line.lstrip("#").strip()
            continue
        if re.match(r"^[-*+] ", line):
            yield from flush()
            cur, cur_bullet = [line[2:]], True
            continue
        if not line.strip():
            if not cur_bullet:
                yield from flush()
                cur = []
            continue
        cur.append(line)
    yield from flush()


def plan(wiki_dir):
    """Return list of fact dicts from wiki pages (projects/, failures/, identity/)."""
    wiki_dir = Path(wiki_dir)
    facts = []
    for sub in ("projects", "failures", "identity"):
        for md in sorted((wiki_dir / sub).glob("*.md")):
            stem = md.stem
            if sub == "projects":
                project = re.sub(r"-memory$", "", stem)
                project = "global" if project in ("unknown", "code") else project
            else:
                project = "global"
            for section, body, _ in _page_items(md.read_text(errors="replace")):
                ts = None
                m = _STAMP.search(body)
                if m:
                    ts = datetime.strptime(m.group(1), "%Y-%m-%d").timestamp()
                    body = _STAMP.sub("", body)
                body = _TAG.sub("", body.strip())
                if not body:
                    continue
                if sub == "failures":
                    kind = FAILURE_KINDS.get(stem, "pitfall")
                elif sub == "identity":
                    kind = "person" if stem == "user-profile" else "preference"
                else:
                    kind = next((k for rx, k in SECTION_KINDS if rx.search(section)), "fact")
                facts.append({
                    "text": body, "kind": kind, "project": project,
                    "entities": section[:80], "source": f"wiki:{sub}/{md.name}",
                    "importance": IMPORTANCE.get(kind, 2),
                    "ts": ts or md.stat().st_mtime,
                })
    return facts


def apply(brain, facts):
    counts = {"ADD": 0, "NOOP": 0, "SKIP": 0}
    t0 = time.time()
    for f in facts:
        _, op = brain.add_fact(f["text"], kind=f["kind"], project=f["project"], entities=f["entities"],
                               source=f["source"], importance=f["importance"], ts=f["ts"], embed=False)
        counts[op] = counts.get(op, 0) + 1
    counts["seconds"] = round(time.time() - t0, 1)
    return counts
