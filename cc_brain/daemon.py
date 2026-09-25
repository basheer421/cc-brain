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

from .config import load_config, get_llm_config
from .consolidator import consolidate, process_suggestion
from .pi_sessions import PI_SESSIONS_DIR, PiSessionTracker, is_session_file
from .queue import list_pending, remove
from .search import WikiSearch

logger = logging.getLogger("cc-brain")

HERMES_SESSION_DIR = Path.home() / ".hermes" / "sessions"


def _call_api(config, messages, task="default"):
    """Call LLM via OpenRouter-compatible API."""
    import requests

    llm = get_llm_config(config, task)
    url = llm.get("api_base_url", "").rstrip("/")
    if not url:
        logger.warning("No api_base_url configured for task=%s", task)
        return None

    headers = {"Content-Type": "application/json"}
    if key := llm.get("api_key"):
        headers["Authorization"] = f"Bearer {key}"
    headers.update(llm.get("extra_headers", {}))

    body = {
        "model": llm.get("model", "qwen3.8-27b"),
        "messages": messages,
        "max_tokens": llm.get("max_tokens", 4000),
    }
    body.update(llm.get("extra_body", {}))

    try:
        resp = requests.post(f"{url}/chat/completions", json=body, headers=headers, timeout=120)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error("LLM call failed (task=%s): %s", task, e)
        return None


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
    def __init__(self, config, search, pi_tracker):
        self._config = config
        self._search = search
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
            result = consolidate(self._config, session_info, p, _call_api)
            if result:
                logger.info("Consolidated %d pages from %s", len(result), key)
        except Exception:
            logger.exception("Consolidation failed for %s", key)


def _process_queue(config, search):
    """Process any pending suggestions."""
    pending = list_pending(config["queue_dir"])
    for item in pending:
        filepath = item.pop("_file", None)
        if not filepath:
            continue
        try:
            ok = process_suggestion(config, item, _call_api)
            if ok:
                remove(filepath)
                # Update search index for changed pages
                target = item.get("target", "")
                if target and target != "auto":
                    search.update_page(target)
        except Exception:
            logger.exception("Failed to process suggestion %s", item.get("id", "?"))


def run_daemon(config_path=None):
    """Run the cc-brain daemon."""
    config = load_config(config_path)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler(config["error_log"]),
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

    # Build search index
    wiki_dir = config.get("wiki_dir", str(Path.home() / "llm-wiki"))
    search = WikiSearch(config["search_db"], wiki_dir)
    count = search.rebuild()
    logger.info("Search index: %d pages", count)

    # Set up watchers
    observer = Observer()
    pi_tracker = PiSessionTracker(config, _call_api, consolidate)
    handler = SessionHandler(config, search, pi_tracker)

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
            _process_queue(config, search)
            time.sleep(30)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
        search.close()
        cleanup()
