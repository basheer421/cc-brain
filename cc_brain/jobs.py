"""Durable retry queue for background LLM work that failed (provider down, Mac asleep, chain exhausted).

Jobs survive daemon restarts (state_dir/llm_jobs.json). The daemon drains at most one due job per
loop tick, so a backlog that piled up during sleep is replayed slowly instead of in a burst.
  {"type": "summarize", "path": <pi session .jsonl>}
  {"type": "ops", "summary": <summary .md>, "cwd": <project cwd>}
"""

import json
import logging
import time
from pathlib import Path

logger = logging.getLogger("cc-brain")

BASE_BACKOFF_S = 300   # 5 min, doubling per failed attempt
MAX_BACKOFF_S = 3600
MAX_ATTEMPTS = 12


def _path(config):
    return Path(config["state_dir"]).expanduser() / "llm_jobs.json"


def _load(config):
    try:
        return json.loads(_path(config).read_text())
    except (OSError, json.JSONDecodeError):
        return []


def _store(config, jobs):
    p = _path(config)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(jobs, indent=1))
    tmp.replace(p)


def _key(job):
    return (job["type"], job.get("path") or job.get("summary"))


def enqueue(config, job, delay=BASE_BACKOFF_S):
    """Add a job (deduplicated by type+target); keeps the earliest pending entry's attempt count."""
    jobs = _load(config)
    if any(_key(j) == _key(job) for j in jobs):
        return
    jobs.append({**job, "attempts": 0, "next_at": time.time() + delay, "queued_at": time.time()})
    _store(config, jobs)
    logger.info("retry queue: +%s %s (%d pending)", job["type"], Path(_key(job)[1]).name, len(jobs))


def pending(config):
    return len(_load(config))


def run_one(config, handlers):
    """Run the oldest due job. handlers[type](job) -> True on success. Returns True if a job ran."""
    jobs = _load(config)
    now = time.time()
    due = [j for j in jobs if j["next_at"] <= now]
    if not due:
        return False
    job = min(due, key=lambda j: j["next_at"])
    jobs.remove(job)
    _store(config, jobs)  # remove first: a handler that re-enqueues itself must not collide
    try:
        ok = handlers[job["type"]](job)
    except Exception:
        logger.exception("retry queue: %s failed", job["type"])
        ok = False
    if ok:
        logger.info("retry queue: done %s %s", job["type"], Path(_key(job)[1]).name)
        return True
    job["attempts"] += 1
    if job["attempts"] >= MAX_ATTEMPTS:
        logger.error("retry queue: giving up on %s %s after %d attempts", job["type"], _key(job)[1], job["attempts"])
        return True
    job["next_at"] = now + min(BASE_BACKOFF_S * 2 ** job["attempts"], MAX_BACKOFF_S)
    jobs = _load(config)
    jobs.append(job)
    _store(config, jobs)
    return True
