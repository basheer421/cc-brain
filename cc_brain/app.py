import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import rumps

from cc_brain.config import load_config
from cc_brain.extractor import extract_delta, save_offset
from cc_brain.scanner import discover_active_sessions
from cc_brain.summarizer import update_summary
from cc_brain.watcher import TranscriptWatcher

ICONS_DIR = Path(__file__).parent.parent / "icons"


def _setup_logging(config):
    error_log = config.get("error_log", str(Path.home() / ".cc-brain" / "logs" / "errors.log"))
    Path(error_log).parent.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("cc-brain")
    logger.setLevel(logging.INFO)

    fh = logging.FileHandler(error_log)
    fh.setLevel(logging.WARNING)
    fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(fh)

    sh = logging.StreamHandler()
    sh.setLevel(logging.INFO)
    sh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(sh)

    return logger


class CCBrainApp(rumps.App):
    def __init__(self):
        self.config = load_config()
        self.logger = _setup_logging(self.config)

        icon_path = str(ICONS_DIR / "brain-idle.png")
        if not Path(icon_path).exists():
            icon_path = None

        super().__init__(
            "cc-brain",
            icon=icon_path,
            template=True,
            quit_button=None,
        )

        self._sessions = {}
        self._processing_lock = threading.Lock()
        self._status = "idle"

        self._sessions_menu = rumps.MenuItem("Active Sessions")
        self._no_sessions = rumps.MenuItem("  (no active sessions)")
        self._sessions_menu.add(self._no_sessions)

        self._open_summaries = rumps.MenuItem("Open Summaries Folder", callback=self._open_summaries_folder)
        self._open_errors = rumps.MenuItem("Open Error Log", callback=self._open_error_log)

        mode = self.config.get("extraction_mode", "smart")
        self._mode_smart = rumps.MenuItem("Mode: Smart", callback=self._set_smart)
        self._mode_full = rumps.MenuItem("Mode: Full", callback=self._set_full)
        if mode == "smart":
            self._mode_smart.state = 1
        else:
            self._mode_full.state = 1

        self._quit_item = rumps.MenuItem("Quit cc-brain", callback=self._quit)

        self.menu = [
            self._sessions_menu,
            None,
            self._open_summaries,
            self._open_errors,
            None,
            self._mode_smart,
            self._mode_full,
            None,
            self._quit_item,
        ]

        if not self.config.get("openrouter_api_key"):
            self.logger.error("No OpenRouter API key found in config or environment")
            self._set_icon_state("error")

        self._watcher = TranscriptWatcher(
            callback=self._on_jsonl_changed,
            debounce_seconds=self.config.get("debounce_seconds", 3),
        )

    def _set_icon_state(self, state):
        self._status = state
        icon_map = {
            "idle": "brain-idle.png",
            "syncing": "brain-sync.png",
            "error": "brain-error.png",
        }
        icon_file = ICONS_DIR / icon_map.get(state, "brain-idle.png")
        if icon_file.exists():
            self.icon = str(icon_file)

    def _open_summaries_folder(self, _):
        summary_dir = self.config.get("summary_dir", str(Path.home() / ".cc-brain" / "summaries"))
        subprocess.run(["open", summary_dir])

    def _open_error_log(self, _):
        error_log = self.config.get("error_log", str(Path.home() / ".cc-brain" / "logs" / "errors.log"))
        if Path(error_log).exists():
            subprocess.run(["open", error_log])
        else:
            rumps.notification("cc-brain", "", "No error log file found yet.")

    def _set_smart(self, sender):
        self.config["extraction_mode"] = "smart"
        self._mode_smart.state = 1
        self._mode_full.state = 0

    def _set_full(self, sender):
        self.config["extraction_mode"] = "full"
        self._mode_smart.state = 0
        self._mode_full.state = 1

    def _quit(self, _):
        self._watcher.stop()
        rumps.quit_application()

    def _refresh_sessions_menu(self):
        self._sessions_menu.clear()
        if not self._sessions:
            self._sessions_menu.add(rumps.MenuItem("  (no active sessions)"))
            return

        for sid, info in self._sessions.items():
            label = f"  {info.get('name', 'unknown')} — {info.get('cwd', '')}"
            item = rumps.MenuItem(label, callback=self._make_open_summary(sid))
            self._sessions_menu.add(item)

    def _make_open_summary(self, session_id):
        def callback(_):
            summary_dir = self.config.get("summary_dir", str(Path.home() / ".cc-brain" / "summaries"))
            path = Path(summary_dir) / f"{session_id}.md"
            if path.exists():
                subprocess.run(["open", str(path)])
            else:
                rumps.notification("cc-brain", "", f"No summary yet for this session.")
        return callback

    def _on_jsonl_changed(self, jsonl_path):
        """Called by the watchdog handler (from a background thread) when a JSONL file changes."""
        with self._processing_lock:
            session_id = Path(jsonl_path).stem

            info = self._sessions.get(session_id)
            if not info:
                self._sessions = discover_active_sessions()
                self._refresh_sessions_menu()
                info = self._sessions.get(session_id)
                if not info:
                    return

            mode = self.config.get("extraction_mode", "smart")
            delta_text, new_offset = extract_delta(jsonl_path, session_id, mode=mode)

            if not delta_text:
                return

            self._set_icon_state("syncing")
            self.logger.info("Processing delta for session %s (%d chars)", session_id, len(delta_text))

            success = update_summary(self.config, session_id, info, delta_text)

            if success:
                save_offset(session_id, new_offset)
                self._set_icon_state("idle")
            else:
                self._set_icon_state("error")

    @rumps.timer(30)
    def _scan_sessions(self, _):
        try:
            self._sessions = discover_active_sessions()
            self._refresh_sessions_menu()
        except Exception:
            self.logger.exception("Error scanning sessions")

    def run(self, **kwargs):
        self._sessions = discover_active_sessions()
        self._refresh_sessions_menu()
        self._watcher.start()
        self.logger.info("cc-brain started, watching %d active sessions", len(self._sessions))
        super().run(**kwargs)


def main():
    app = CCBrainApp()
    app.run()


if __name__ == "__main__":
    main()
