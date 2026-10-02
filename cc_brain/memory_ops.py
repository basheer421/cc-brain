"""Write path (Mem0-style memory ops) and the `sleep` consolidation pass.

consolidate(): session summary -> candidate facts -> ADD / UPDATE / SUPERSEDE / NOOP against the
               nearest existing facts. Dedup happens on write instead of by later compaction.
sleep():       offline pass — merge clusters of near-duplicate facts, shorten long facts
               (original text kept in facts.original).
"""

import json
import logging
import re
import time
from pathlib import Path

import numpy as np

from .brain import KINDS, Brain, fact_doc
from .consolidator import _load_state, _parse_json, _save_state
from .embed import from_blob
from .episodes import project_slug

logger = logging.getLogger("cc-brain")

OPS_PROMPT = f"""You maintain a developer's long-term memory as a list of atomic facts.

Input: a coding-session summary and the EXISTING facts most related to it (with ids).
Output JSON only: {{"ops": [ ... ]}} where each op is one of:
  {{"op": "ADD", "text": "...", "kind": "<kind>", "importance": 1|2|3}}
  {{"op": "UPDATE", "id": <existing id>, "text": "..."}}      # same fact, refined/extended
  {{"op": "SUPERSEDE", "id": <existing id>, "text": "..."}}   # the old fact is no longer true
  {{"op": "NOOP", "id": <existing id>}}                       # session re-confirmed this fact

kinds: {", ".join(KINDS)}
importance: 3 = user correction / costly pitfall / hard rule, 2 = normal, 1 = minor.

Rules:
- Only DURABLE knowledge that will matter in a future session: decisions + why, pitfalls + fix,
  tool quirks, user corrections and preferences, stable facts (hosts, paths, versions, who-owns-what).
- Skip progress narration, one-off values, in-flight state, anything the summary marks as tentative.
- One claim per fact, <= 200 chars, imperative or declarative ("X needs Y because Z"). Names/IDs exact.
- Never ADD something an existing fact already says — use NOOP or UPDATE.
- If the session shows an existing fact is now false (status changed, decision reversed), SUPERSEDE it.
- No secrets (tokens, passwords, keys).
- Most sessions yield 0-5 ops. Empty is fine: {{"ops": []}}"""

MERGE_PROMPT = """These facts from a developer's memory overlap (listed oldest first). Merge them into the
smallest set of atomic facts that loses NO information: every command, flag, path, ID, number and name
must survive verbatim. Prefer more facts over dropping detail. Each fact <= 300 chars. Newest wins on
conflict. Do not add dates. Output JSON only: {"facts": ["...", "..."]}"""

SHORTEN_PROMPT = """Rewrite each fact to <= 200 chars as a one-line rule or claim: keep every name, ID,
path, command, number and the WHY; drop narration ("the user said...", dates of discovery, story).
Output JSON only: {"facts": {"<id>": "<short text>", ...}}"""


def _summary_query(text):
    secs = re.split(r"^## ", text, flags=re.M)
    keep = [s for s in secs if s.startswith(("Goal", "Key Decisions", "Current State"))]
    return " ".join(keep)[:1500] or text[:1500]


def consolidate(config, session_info, summary_path, call_api, brain=None, force=False):
    """Summary -> memory ops. Returns list of (op, id)."""
    cwd = session_info.get("cwd", "") or ""
    if not cwd or cwd.startswith("hermes/") or Path(cwd) == Path.home():
        return []
    project = project_slug(cwd)
    state = _load_state()
    rate_key = f"v3:{project}"
    now = time.time()
    if not force and now - state.get(rate_key, 0) < config.get("consolidation_min_interval_s", 900):
        return []
    summary_path = Path(summary_path)
    if not summary_path.exists():
        return []
    summary = summary_path.read_text(errors="replace")
    state[rate_key] = now
    _save_state(state)

    brain = brain or Brain(config["brain_db"], config)
    source = f"session:{summary_path.name}"
    related = brain.recall(_summary_query(summary), project=project, limit=30, touch=False, raw=True)
    related_ids = {r["id"] for r in related}
    # the daemon re-consolidates a session each time its summary grows: always show what it already produced
    for r in brain.conn.execute("SELECT * FROM facts WHERE source = ? AND superseded_by IS NULL", (source,)):
        if r["id"] not in related_ids:
            related.append(r)
            related_ids.add(r["id"])
    existing = "\n".join(f"#{r['id']} [{r['kind']}/{r['project']}] {r['text'][:400]}" for r in related)

    user = (f"Project: {project} ({cwd})\n\nEXISTING facts:\n{existing or '(none)'}\n\n"
            f"SESSION SUMMARY:\n{summary}")
    data, meta = None, {}
    for attempt in range(2):  # reasoning models can burn the token budget; retry once asking for fewer ops
        meta = {}
        sys_prompt = OPS_PROMPT if attempt == 0 else OPS_PROMPT + "\nBe brief: at most 5 ops, think briefly."
        result = call_api(config, [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user}],
                          task="consolidation", json_mode=True, meta=meta)
        data = _parse_json(result) if result else None
        if data or not meta.get("truncated"):
            break
    if not data:
        logger.warning("memory ops: no usable output for %s (truncated=%s)", summary_path.name, meta.get("truncated"))
        return []

    applied = []
    for op in data.get("ops", [])[:12]:
        kind = op.get("op", "").upper()
        text = (op.get("text") or "").strip()
        fid = op.get("id")
        try:
            fid = int(fid) if fid is not None else None
        except (TypeError, ValueError):
            fid = None
        if kind in ("UPDATE", "SUPERSEDE", "NOOP") and fid not in related_ids:
            kind = "ADD" if text else "SKIP"  # model referenced an id it wasn't shown
        if kind == "ADD" and text:
            twin = _paraphrase_of(brain, text, project)
            if twin:  # semantic near-duplicate the model failed to recognise
                brain.touch(twin)
                applied.append(("NOOP", twin))
                continue
            new_id, res = brain.add_fact(text, kind=op.get("kind", "fact"), project=project,
                                         importance=op.get("importance", 2), source=source)
            applied.append((res, new_id))
        elif kind == "UPDATE" and text:
            brain.update_fact(fid, text)
            applied.append(("UPDATE", fid))
        elif kind == "SUPERSEDE" and text:
            applied.append(("SUPERSEDE", brain.supersede(fid, text, source=source)))
        elif kind == "NOOP":
            brain.touch(fid)
            applied.append(("NOOP", fid))
    logger.info("memory ops for %s: %s", summary_path.name, applied)
    return applied


PARAPHRASE_SIM = 0.85  # measured: paraphrases ~0.89, related-but-distinct facts <= 0.71


def _paraphrase_of(brain, text, project):
    arr = brain.embedder.documents([fact_doc(text, project)])  # doc-vs-doc, same as stored embeddings
    if arr is None:
        return None
    vec = arr[0]
    for row, sim in brain._dense_rows("facts", vec, limit=3):
        if sim >= PARAPHRASE_SIM and row["project"] in (project, "global"):
            return row["id"]
    return None


# --------------------------------------------------------------------------- sleep


_TERM = re.compile(r"`([^`]{2,80})`|((?:~|\.{0,2})/[\w./-]+)|(--?[a-z][\w-]+)|\b([\w.-]*\d[\w.-]*)\b")


def key_terms(text):
    """Things a rewrite must not lose: backticked spans, paths, flags, tokens containing digits."""
    out = set()
    for m in _TERM.finditer(text or ""):
        t = next(g for g in m.groups() if g)
        if len(t) >= 2:
            out.add(t.lower())
    return out


def coverage(originals, rewritten):
    terms = set().union(*(key_terms(t) for t in originals))
    if not terms:
        return 1.0
    hay = " ".join(rewritten).lower()
    return sum(t in hay for t in terms) / len(terms)


def _clusters(brain, threshold=0.9, project=None):
    """Connected components of live facts whose embeddings are >= threshold similar (same project)."""
    rows = [r for r in brain.live_facts(project) if r["embedding"] is not None]
    if len(rows) < 2:
        return []
    mat = np.vstack([from_blob(r["embedding"]) for r in rows])
    sims = mat @ mat.T
    np.fill_diagonal(sims, 0)
    parent = list(range(len(rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    ii, jj = np.where(np.triu(sims) >= threshold)
    for i, j in zip(ii, jj):
        if rows[i]["project"] == rows[j]["project"]:
            parent[find(i)] = find(j)
    groups = {}
    for i in range(len(rows)):
        groups.setdefault(find(i), []).append(rows[i])
    return [g for g in groups.values() if 1 < len(g) <= 8]


def sleep(config, call_api, brain=None, merge=True, shorten=True, max_calls=200, threshold=0.9,
          shorten_over=320, dry_run=False):
    brain = brain or Brain(config["brain_db"], config)
    stats = {"clusters": 0, "merged_away": 0, "shortened": 0, "calls": 0}
    brain.embed_missing("facts")

    if merge:
        clusters = _clusters(brain, threshold)
        stats["clusters"] = len(clusters)
        for group in clusters:
            if stats["calls"] >= max_calls:
                break
            if dry_run:
                continue
            group.sort(key=lambda r: r["updated"])
            listing = "\n".join(f"- {r['text']}" for r in group)
            stats["calls"] += 1
            data = _parse_json(call_api(config, [
                {"role": "system", "content": MERGE_PROMPT}, {"role": "user", "content": listing}],
                task="consolidation", json_mode=True) or "")
            merged = [t.strip() for t in (data or {}).get("facts", []) if isinstance(t, str) and t.strip()]
            if not merged or len(merged) >= len(group):
                continue
            if coverage([r["text"] for r in group], merged) < 0.9:
                stats["rejected_lossy"] = stats.get("rejected_lossy", 0) + 1
                continue
            keeper = group[-1]
            kind = next((r["kind"] for r in group if r["kind"] == "correction"), keeper["kind"])
            importance = max(r["importance"] for r in group)
            new_ids = [brain.add_fact(t, kind=kind, project=keeper["project"], entities=keeper["entities"],
                                      importance=importance, source="sleep:merge", dedup=False)[0] for t in merged]
            for r in group:
                brain.conn.execute("UPDATE facts SET superseded_by=?, updated=? WHERE id=?",
                                   (new_ids[0], time.time(), r["id"]))
                brain.conn.execute("DELETE FROM facts_fts WHERE rowid=?", (r["id"],))
            brain.conn.commit()
            brain._mat_cache.pop("facts", None)
            stats["merged_away"] += len(group) - len(merged)

    if shorten:
        long_rows = [r for r in brain.live_facts() if len(r["text"]) > shorten_over and not r["original"]]
        stats["long"] = len(long_rows)
        for i in range(0, len(long_rows), 15):
            if stats["calls"] >= max_calls or dry_run:
                break
            batch = long_rows[i:i + 15]
            listing = json.dumps({str(r["id"]): r["text"] for r in batch}, ensure_ascii=False)
            stats["calls"] += 1
            data = _parse_json(call_api(config, [
                {"role": "system", "content": SHORTEN_PROMPT}, {"role": "user", "content": listing}],
                task="consolidation", json_mode=True) or "")
            out = (data or {}).get("facts", {})
            for r in batch:
                new = out.get(str(r["id"]))
                if (isinstance(new, str) and 20 < len(new.strip()) < len(r["text"])
                        and coverage([r["text"]], [new]) >= 0.85):
                    brain.update_fact(r["id"], new.strip(), keep_original=True)
                    stats["shortened"] += 1
    return stats
