import logging
import threading
from pathlib import Path

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

logger = logging.getLogger("cc-brain")


class DebouncedHandler(FileSystemEventHandler):
    def __init__(self, callback, debounce_seconds=3, suffix=".jsonl"):
        super().__init__()
        self._callback = callback
        self._debounce = debounce_seconds
        self._suffix = suffix
        self._timers = {}
        self._lock = threading.Lock()

    def on_modified(self, event):
        self._handle(event)

    def on_created(self, event):
        self._handle(event)

    def _handle(self, event):
        if event.is_directory:
            return
        if self._suffix and not event.src_path.endswith(self._suffix):
            return

        with self._lock:
            existing = self._timers.get(event.src_path)
            if existing:
                existing.cancel()

            timer = threading.Timer(self._debounce, self._fire, args=[event.src_path])
            self._timers[event.src_path] = timer
            timer.start()

    def _fire(self, path):
        with self._lock:
            self._timers.pop(path, None)
        try:
            self._callback(path)
        except Exception:
            logger.exception("Error in watcher callback for %s", path)


class TranscriptWatcher:
    def __init__(self, callback, debounce_seconds=3, hermes_callback=None):
        watch_path = Path.home() / ".claude" / "projects"
        self._observer = Observer()
        self._handler = DebouncedHandler(callback, debounce_seconds)
        self._watch_path = str(watch_path)
        self._hermes_handler = None
        self._hermes_path = None
        if hermes_callback:
            triggers = Path.home() / ".cc-brain" / "triggers"
            triggers.mkdir(parents=True, exist_ok=True)
            self._hermes_handler = DebouncedHandler(
                hermes_callback, debounce_seconds, suffix=""
            )
            self._hermes_path = str(triggers)

    def start(self):
        self._observer.schedule(self._handler, self._watch_path, recursive=True)
        if self._hermes_handler:
            self._observer.schedule(self._hermes_handler, self._hermes_path, recursive=False)
            logger.info("Watching %s for Hermes triggers", self._hermes_path)
        self._observer.daemon = True
        self._observer.start()
        logger.info("Watching %s for JSONL changes", self._watch_path)

    def stop(self):
        self._observer.stop()
        self._observer.join(timeout=5)
