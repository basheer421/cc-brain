"""dsh session source end-to-end on synthetic sessions: zstd file -> summary -> episodes, re-run idempotence,
appended events, a half-written trailing frame, and the auto-recall log merge. LLM is stubbed; Brain is a temp DB.

    uv run python tests/it_dsh_sessions.py
"""

import json
import tempfile
from pathlib import Path

import zstandard

from cc_brain import dsh_sessions
from cc_brain.brain import Brain
from cc_brain.dsh_sessions import DshSessionTracker

tmp = Path(tempfile.mkdtemp())
project_dir = tmp / "code" / "my-app"  # a dash in the name: folder decoding must not split it
project_dir.mkdir(parents=True)
cwd = str(project_dir)
sessions = tmp / "sessions"
dsh_sessions.DSH_SESSIONS_DIR = sessions
folder = sessions / f"-{cwd.replace('/', '-')}--" / "session-0000"
folder.mkdir(parents=True)
sess = folder / dsh_sessions.SESSION_FILE
cfg = {"summary_dir": str(tmp / "summaries"), "state_dir": str(tmp)}
Path(cfg["summary_dir"]).mkdir()

seq = 0


def ev(type_, data):
    global seq
    seq += 1
    return {"type": type_, "seq": seq, "time": 1790000000000 + seq * 1000, "data": data}


def user(text, kind="user"):
    return ev("user/message", {"content": [{"type": "text", "text": text}], "source": {"kind": kind}, "role": "user"})


def assistant(text):
    return ev("assistant/message", {"message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})


def frame(events):
    return zstandard.ZstdCompressor().compress("".join(json.dumps(e) + "\n" for e in events).encode())


header = {"type": "session", "version": 4, "id": "session-0000", "createdAt": 1790000000000, "cwd": cwd}
batch1 = [header, user("<system-reminder>injected</system-reminder>", kind="instructions"),
          user("add a healthcheck endpoint"),
          ev("tool/call", {"name": "bash", "arguments": '{"command":"ls src"}'}),
          ev("tool/result", {"message": {"role": "tool", "content": [{"type": "text", "text": "main.go"}]}}),
          assistant("Added GET /healthz.")]
sess.write_bytes(frame(batch1))

prompts = []


def stub_api(config, messages, task="default", json_mode=False, meta=None):
    prompts.append(messages[-1]["content"])
    return (f"# my-app\n**Project:** {cwd}\n**Session:** session-0000\n**Started:** 2026-09-21 10:00\n"
            f"**Last updated:** 2026-09-21 10:{len(prompts):02d}\n\n## Goal\nHealthcheck endpoint.\n\n"
            f"## Progress\n" + "".join(f"- step {i}\n" for i in range(len(prompts))) +
            "\n## Current State\nDone.\n\n## Files Changed\n- src/main.go\n")


brain = Brain(str(tmp / "brain.db"), {}, embedder=type("NoEmbed", (), {"documents": lambda s, d: None,
                                                                         "query": lambda s, q: None})())


def consolidate(config, info, summary_path, call_api):
    consolidate.calls.append(info["cwd"])
    brain.ingest_summary(summary_path, embed=False)


consolidate.calls = []


def episodes():
    return brain.conn.execute("SELECT project, section, text FROM episodes ORDER BY id").fetchall()


def tracker():  # fresh instance = daemon restart; state must survive on disk
    return DshSessionTracker(cfg, stub_api, consolidate)


# 1. first run: one summary, episodes for the project from the folder name, injected context dropped
assert tracker().mark_unseen() == 1
tracker()._summarize(sess)
summaries = list(Path(cfg["summary_dir"]).glob("d-my-app-*.md"))
rows = episodes()
print(f"run1: llm_calls={len(prompts)} summaries={[s.name for s in summaries]} episodes={len(rows)} "
      f"projects={sorted({r['project'] for r in rows})}")
assert len(prompts) == 1 and len(summaries) == 1 and rows and {r["project"] for r in rows} == {"my-app"}
assert "User: add a healthcheck endpoint" in prompts[0] and "[Tool: bash]" in prompts[0] and "[Result] main.go" in prompts[0]
assert "injected" not in prompts[0] and "Harness: DeepSeek Harness" in prompts[0]
last_event = dsh_sessions.datetime.fromtimestamp(batch1[-1]["time"] / 1000).strftime("%Y-%m-%d %H:%M")
assert f"- Now: {last_event}" in prompts[0], "backfilled sessions must be dated by their last event"

# 2. re-run with nothing new (new tracker instance = after restart): no LLM call, no duplicate episodes
n_before = len(episodes())
tracker()._summarize(sess)
print(f"run2 (unchanged): llm_calls={len(prompts)} episodes={len(episodes())}")
assert len(prompts) == 1 and len(episodes()) == n_before

# 3. appended events (new frame) + a half-written trailing frame: only the new turns go to the LLM
batch2 = [user("now add a readiness probe"), assistant("Added GET /readyz.")]
partial = frame([user("this frame is still being written")])[:-6]
sess.write_bytes(frame(batch1) + frame(batch2) + partial)
tracker()._summarize(sess)
rows = episodes()
files = {r[0] for r in brain.conn.execute("SELECT DISTINCT file FROM episodes")}
print(f"run3 (appended): llm_calls={len(prompts)} episode_files={sorted(files)} episodes={len(rows)}")
assert len(prompts) == 2 and "readiness probe" in prompts[1] and "healthcheck endpoint" not in prompts[1]
assert "still being written" not in prompts[1] and len(files) == 1

# 4. folder-name decoding alone (no header) keeps the dash
decoded = dsh_sessions.cwd_from_folder(folder.parent.name)
print(f"folder decode: {decoded}")
assert decoded == cwd

# 5. auto-recall log merge: only complete lines, once
tdir = tmp / "t"
(tdir / "cc-brain-dsh-recall").mkdir(parents=True)
src = tdir / dsh_sessions.RECALL_FALLBACK
src.write_text('{"harness": "dsh", "n": 1}\n{"harness": "dsh", "n": 2}\n{"partial')
dsh_sessions._temp_dirs = lambda: [tdir]
target = tmp / "auto-recall.jsonl"
m1 = dsh_sessions.merge_recall_log(cfg, target)
m2 = dsh_sessions.merge_recall_log(cfg, target)
with src.open("a") as f:
    f.write('": 3}\n')
m3 = dsh_sessions.merge_recall_log(cfg, target)
lines = target.read_text().splitlines()
print(f"recall merge: {m1} then {m2} then {m3}; target lines={len(lines)}")
assert (m1, m2, m3) == (2, 0, 1) and len(lines) == 3 and all(json.loads(l) for l in lines)
print("PASS")
