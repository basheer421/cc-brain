"""Recall eval on real brain data: v2 page search vs v3 fact recall.

hit@5  : the answer is in one of the top-5 results
bytes  : what the agent has to read to get the answer
         v2 = sizes of the pages returned up to the hit (snippets don't carry answers)
         v3 = the returned facts (the answer is in the result itself)

Run:  python tests/eval_recall.py [--no-dense] [--v2]   (--v2: historical page-search baseline)
"""

import json
import re
import sys
from pathlib import Path

from cc_brain.brain import Brain
from cc_brain.config import load_config
from cc_brain.search import WikiSearch

# Real questions from your own memory live in tests/local/eval_cases.json (gitignored):
# [[query, project hint or null, answer regex], ...]. The example file shows the shape.
HERE = Path(__file__).parent
_cases = HERE / "local" / "eval_cases.json"
EVAL = [tuple(c) for c in json.loads((_cases if _cases.exists() else HERE / "eval_cases.example.json").read_text())]


def v2_eval(cfg):
    ws = WikiSearch(cfg["search_db"], cfg["wiki_dir"])
    if ws.page_count() == 0:
        ws.rebuild()
    wiki = Path(cfg["wiki_dir"])
    hits, total_bytes = 0, 0
    rows = []
    for q, _, rx in EVAL:
        res = ws.search(q, limit=5)
        read, hit = 0, False
        for r in res:
            page = wiki / r["path"]
            if not page.exists():  # v2 index predates `render`; pages it points at may be gone
                continue
            text = page.read_text(errors="replace")
            read += len(text.encode())
            if re.search(rx, text):
                hit = True
                break
        hits += hit
        total_bytes += read
        rows.append((hit, read))
    return hits, total_bytes, rows


def v3_eval(cfg, dense=True):
    b = Brain(cfg["brain_db"], cfg)
    if not dense:
        b.embedder.enabled = False
    hits, total_bytes, rows = 0, 0, []
    for q, proj, rx in EVAL:
        res = b.recall(q, project=proj, limit=5, touch=False)
        payload = json.dumps(res)
        hit = any(re.search(rx, r["text"]) for r in res)
        hits += hit
        total_bytes += len(payload.encode())
        rows.append((hit, len(payload.encode())))
    return hits, total_bytes, rows


if __name__ == "__main__":
    cfg = load_config()
    n = len(EVAL)
    v2 = v2_eval(cfg) if "--v2" in sys.argv else (0, 0, [(False, 0)] * n)
    bm = v3_eval(cfg, dense=False)
    hy = None if "--no-dense" in sys.argv else v3_eval(cfg, dense=True)
    print(f"{'query':58} v2   v3bm25  v3hybrid" + ("" if "--v2" in sys.argv else "   (v2 skipped)"))
    for i, (q, _, _) in enumerate(EVAL):
        cols = [v2[2][i], bm[2][i]] + ([hy[2][i]] if hy else [])
        print(f"{q[:58]:58} " + "  ".join(f"{'✔' if h else '✘'}{b // 1024:>4}K" for h, b in cols))
    print(f"\nhit@5   v2 {v2[0]}/{n}   v3-bm25 {bm[0]}/{n}" + (f"   v3-hybrid {hy[0]}/{n}" if hy else ""))
    print(f"bytes   v2 {v2[1] // 1024} KB   v3-bm25 {bm[1] // 1024} KB" + (f"   v3-hybrid {hy[1] // 1024} KB" if hy else ""))
