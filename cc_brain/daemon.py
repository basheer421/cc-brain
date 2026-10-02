"""Daemon: watches Pi/Hermes session dirs, triggers summarization + consolidation."""

import json
import logging
import os
import signal
import sys
import time
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

from .brain import Brain
from .config import load_config, get_llm_config
from .consolidator import _load_state, _save_state
from .memory_ops import consolidate as memory_ops, sleep
from .mcp_server import _kind_from_target, _project_from_target
from .pi_sessions import PI_SESSIONS_DIR, PiSessionTracker, is_session_file
from .queue import list_pending, remove
from .render import render

logger = logging.getLogger("cc-brain")

HERMES_SESSION_DIR = Path.home() / ".hermes" / "sessions"
MAINTENANCE_HOUR = 3        # local time; sleep + render run once per day after this hour
_BRAIN = None


def _brain(config):
    global _BRAIN
    if _BRAIN is None:
        _BRAIN = Brain(config["brain_db"], config)
    return _BRAIN


def on_summary(config, session_info, summary_path, call_api):
    """v3 write path for one (new or updated) session summary: episode index + memory ops."""
    brain = _brain(config)
    try:
        n = brain.ingest_summary(summary_path, embed=True)
        if n:
            logger.info("episodes: %d chunks from %s", n, Path(summary_path).name)
    except Exception:
        logger.exception("episode ingest failed for %s", summary_path)
    return memory_ops(config, session_info, summary_path, call_api, brain=brain)


def _maintenance(config):
    """Daily: merge near-duplicate facts, shorten long ones, re-render the wiki view."""
    state = _load_state()
    today = time.strftime("%Y-%m-%d")
    if state.get("v3:maintenance") == today or time.localtime().tm_hour < MAINTENANCE_HOUR:
        return
    state["v3:maintenance"] = today
    _save_state(state)
    brain = _brain(config)
    try:
        logger.info("sleep: %s", sleep(config, _call_api, brain=brain, max_calls=60))
        brain.index_docs(config.get("wiki_dir", str(Path.home() / "llm-wiki")))
        render(config, brain=brain)
    except Exception:
        logger.exception("daily maintenance failed")


def _call_api(config, messages, task="default", json_mode=False, meta=None):
    """Provider chain (agy -> Meridian -> OpenRouter); see llm.py. Never returns truncated text."""
    from .llm import call_api
    return call_api(config, messages, task=task, json_mode=json_mode, meta=meta)


def _find_summary(session_dir):
    """Find the summary file for a session."""
    for name in ("summary.md", "summary.txt", "session-summary.md"):
        p = session_dir / name
        if p.exists():
            return p
    return None


def _read_session_info(session_dir):
    """Read session metadata."""
    for name in ("session.json", "metadata.json"):
        p = session_dir / name
        if p.exists():
            try:
                return json.loads(p.read_text())
            except (json.JSONDecodeError, OSError):
                pass
    return {"cwd": str(session_dir)}


class SessionHandler(FileSystemEventHandler):
    def __init__(self, config, pi_tracker):
        self._config = config
        self._pi = pi_tracker
        self._processed = set()
        self._debounce = {}

    def on_created(self, event):
        self._handle(event.src_path)

    def on_modified(self, event):
        self._handle(event.src_path)

    def _handle(self, path):
        p = Path(path)
        if is_session_file(p):
            self._pi.mark(p)
            return
        if p.name not in ("summary.md", "summary.txt", "session-summary.md"):
            return

        session_dir = p.parent
        key = str(session_dir)

        now = time.time()
        if now - self._debounce.get(key, 0) < self._config.get("debounce_seconds", 3):
            return
        self._debounce[key] = now

        if key in self._processed:
            return
        self._processed.add(key)

        logger.info("New session summary: %s", p)
        session_info = _read_session_info(session_dir)

        try:
            result = on_summary(self._config, session_info, p, _call_api)
            if result:
                logger.info("memory ops: %d from %s", len(result), key)
        except Exception:
            logger.exception("Consolidation failed for %s", key)


def _process_queue(config):
    """Legacy queued suggestions (v2 wiki_suggest) become facts directly — no LLM."""
    brain = _brain(config)
    for item in list_pending(config["queue_dir"]):
        filepath = item.pop("_file", None)
        if not filepath:
            continue
        try:
            target, kind = item.get("target", ""), _kind_from_target(item.get("target"))
            if item.get("type") == "correction":
                kind = "correction"
            brain.add_fact(item.get("content", ""), kind=kind, project=_project_from_target(target),
                           importance=3 if kind == "correction" else 2, source=f"queue:{item.get('id', '')}")
            remove(filepath)
        except Exception:
            logger.exception("Failed to process suggestion %s", item.get("id", "?"))


def _error_file_handler(path):
    """errors.log gets WARNING+ only; full INFO stream goes to stdout (daemon.log)."""
    handler = logging.FileHandler(path)
    handler.setLevel(logging.WARNING)
    return handler


def run_daemon(config_path=None):
    """Run the cc-brain daemon."""
    config = load_config(config_path)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            _error_file_handler(config["error_log"]),
        ],
    )

    # PID file
    pid_path = Path(config["pid_file"])
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    if pid_path.exists():
        old_pid = int(pid_path.read_text().strip())
        try:
            os.kill(old_pid, 0)
            logger.error("Daemon already running (pid %d)", old_pid)
            sys.exit(1)
        except ProcessLookupError:
            pass
    pid_path.write_text(str(os.getpid()))

    def cleanup(*_):
        pid_path.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, cleanup)
    signal.signal(signal.SIGINT, cleanup)

    # Index hand-written skill docs; backfill any missing embeddings (no-op when Ollama is down)
    brain = _brain(config)
    wiki_dir = config.get("wiki_dir", str(Path.home() / "llm-wiki"))
    logger.info("docs: %d chunks; embedded facts=%d episodes=%d", brain.index_docs(wiki_dir),
                brain.embed_missing("facts"), brain.embed_missing("episodes"))

    # Set up watchers
    observer = Observer()
    pi_tracker = PiSessionTracker(config, _call_api, on_summary)
    handler = SessionHandler(config, pi_tracker)

    if PI_SESSIONS_DIR.exists():
        cutoff = time.time() - 3600
        for f in PI_SESSIONS_DIR.glob("*/*.jsonl"):
            if f.stat().st_mtime > cutoff:
                pi_tracker.mark(f)

    for d in (PI_SESSIONS_DIR, HERMES_SESSION_DIR):
        if d.exists():
            observer.schedule(handler, str(d), recursive=True)
            logger.info("Watching %s", d)

    observer.start()
    logger.info("cc-brain daemon started (pid %d)", os.getpid())

    try:
        while True:
            pi_tracker.process()
            _process_queue(config)
            _maintenance(config)
            time.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        brain.close()
        cleanup()
