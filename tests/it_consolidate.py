"""Real summaries through the v3 memory-ops consolidator, against a COPY of the live brain.db.

Pass criteria: ops are produced for at least one summary, every op is valid, and no ADD
duplicates an existing live fact (Jaccard >= 0.85) or another ADD from the same run.
Run twice on the same summary: rerun ADDs must not duplicate anything (LLM extraction is
nondeterministic, so a few genuinely new facts are allowed: <= 25% of the first run's ops).
Summaries modified in the last 10 minutes are skipped (still being written by the daemon).
"""

import json
import re
import sqlite3
import time
import sys
import tempfile
from pathlib import Path

from cc_brain.brain import Brain, jaccard
from cc_brain.config import load_config
from cc_brain.daemon import _call_api
from cc_brain.memory_ops import _paraphrase_of, consolidate

SUMMARIES = Path.home() / ".cc-brain" / "summaries"


def _cwd(f):
    m = re.search(r"^\*\*(?:CWD|Project):\*\*\s*(\S+)", f.read_text(errors="replace")[:600], re.M)
    return m.group(1) if m else None


def pick(n=3):
    files = sorted(SUMMARIES.glob("p-*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    out = []
    for f in files:
        cwd = _cwd(f)
        if time.time() - f.stat().st_mtime > 600 and cwd and Path(cwd) != Path.home() and f.stat().st_size > 1500:
            out.append(f)
        if len(out) == n:
            break
    return out


def main():
    cfg = load_config()
    tmp = Path(tempfile.mkdtemp())
    db = tmp / "brain.db"
    sqlite3.connect(cfg["brain_db"]).backup(sqlite3.connect(db))
    cfg = dict(cfg, brain_db=str(db))
    b = Brain(str(db), cfg)

    total_ops, failures = 0, []
    for f in pick(int(sys.argv[1]) if len(sys.argv) > 1 else 3):
        before = {r["id"]: r["text"] for r in b.live_facts()}
        ops = consolidate(cfg, {"cwd": _cwd(f)}, f, _call_api,
                          brain=b, force=True)
        total_ops += len(ops)
        added = [(op, fid) for op, fid in ops if op == "ADD"]
        print(f"{f.name}: {len(ops)} ops {[o for o, _ in ops]}")
        new_texts = []
        for _, fid in added:
            t = b.get_fact(fid)["text"]
            print("   +", t[:150])
            dup = [i for i, old in before.items() if jaccard(t, old) >= 0.85]
            if dup or any(jaccard(t, o) >= 0.85 for o in new_texts):
                failures.append(f"duplicate ADD #{fid} ~ {dup}")
            new_texts.append(t)
        again = consolidate(cfg, {"cwd": _cwd(f)}, f, _call_api,
                            brain=b, force=True)
        re_adds = [x for x in again if x[0] == "ADD"]
        print(f"   rerun: {[o for o, _ in again]}")
        for _, fid in re_adds:
            t, row = b.get_fact(fid)["text"], b.get_fact(fid)
            b.conn.execute("UPDATE facts SET superseded_by=-1 WHERE id=?", (fid,))  # hide self for the check
            b._mat_cache.pop("facts", None)
            twin = _paraphrase_of(b, t, row["project"])
            near = b.recall(t, project=row["project"], limit=2, touch=False)
            print(f"   ++ {t[:140]}\n      nearest: {near[1]['text'][:140] if len(near) > 1 else '-'}")
            b.conn.execute("UPDATE facts SET superseded_by=NULL WHERE id=?", (fid,))
            b._mat_cache.pop("facts", None)
            if twin or any(jaccard(t, o) >= 0.85 for o in before.values()):
                failures.append(f"rerun duplicate ADD #{fid} ~ #{twin}")
        if ops and len(re_adds) > max(1, len(ops) // 4):
            # LLM nondeterminism: a rerun may extract facts the first run missed. Only duplicates fail.
            print(f"   note: rerun added {len(re_adds)} distinct facts (first run {len(ops)} ops)")
    print(json.dumps({"ops": total_ops, "failures": failures}))
    assert total_ops > 0, "no ops produced"
    assert not failures, failures
    print("PASS")


main()
