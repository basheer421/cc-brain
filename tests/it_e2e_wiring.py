"""Daemon write path end-to-end on a COPY of brain.db: summary -> episode + facts -> recall/timeline.

The LLM is stubbed (fixed memory-ops reply) so this runs without OpenRouter credit; everything
else is real (Ollama embeddings, FTS, ranking, paraphrase gate). Pass --live to use the real LLM.
"""

import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

from cc_brain import daemon
from cc_brain.brain import Brain
from cc_brain.config import load_config

SUMMARY = """# Session: e2e probe
**Project:** cc-brain
**CWD:** {cwd}
**Last Updated:** {now}

## Goal
Verify the v3 write path with the walrus-indigo-42 probe.

## Progress
- Wired on_summary into the daemon.

## Key Decisions
- The walrus-indigo-42 probe host is called `probe-box-7` and listens on port 4471.
"""


CWD = str(Path.home() / "code" / "cc-brain")  # project slug "cc-brain"


def stub_api(config, messages, task="default", json_mode=False, meta=None):
    return json.dumps({"ops": [
        {"op": "ADD", "kind": "fact", "importance": 2,
         "text": "walrus-indigo-42 probe host is `probe-box-7`, listening on port 4471."},
        {"op": "ADD", "kind": "fact", "importance": 2,  # paraphrase: must be gated to NOOP
         "text": "The walrus-indigo-42 probe runs on host `probe-box-7` and listens on port 4471."},
    ]})


def main():
    cfg = load_config()
    tmp = Path(tempfile.mkdtemp())
    sqlite3.connect(cfg["brain_db"]).backup(sqlite3.connect(tmp / "brain.db"))
    cfg = dict(cfg, brain_db=str(tmp / "brain.db"), consolidation_min_interval_s=0)  # live state file rate-limits per project
    daemon._BRAIN = None
    summary = tmp / f"p-cc-brain-{int(time.time() * 1000)}.md"
    summary.write_text(SUMMARY.format(now=time.strftime("%Y-%m-%d %H:%M"), cwd=CWD))

    api = daemon._call_api if "--live" in sys.argv else stub_api
    ops = daemon.on_summary(cfg, {"cwd": CWD}, summary, api)
    print("ops:", ops)
    assert [o for o, _ in ops].count("ADD") == 1, ops

    b = Brain(cfg["brain_db"], cfg)
    hits = b.recall("which host does the walrus probe run on", project="cc-brain", touch=False)
    assert hits and "probe-box-7" in hits[0]["text"], hits[:2]
    print("recall top-1:", hits[0]["text"])
    tl = b.timeline(project="cc-brain", since=time.strftime("%Y-%m-%d"), query="walrus-indigo-42")
    assert any("walrus-indigo-42" in json.dumps(e) for e in tl), tl[:2]
    print("timeline: episode found for", summary.name)
    print("PASS")


main()
