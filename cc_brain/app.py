import logging
import subprocess
import threading
from pathlib import Path

import rumps

from cc_brain.config import load_config
from cc_brain.extractor import extract_delta, save_offset
from cc_brain.scanner import discover_active_sessions
from cc_brain.summarizer import update_summary, get_summary_filename
from cc_brain.watcher import TranscriptWatcher

ICONS_DIR = Path(__file__).parent.parent / "icons"


def _setup_logging(config):
    error_log = config["error_log"]
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

        icon_path = ICONS_DIR / "brain-idle.png"
        super().__init__(
            "cc-brain",
            icon=str(icon_path) if icon_path.exists() else None,
            template=True,
            quit_button=None,
        )

        self._sessions = {}
        self._worker = None

        self._sessions_menu = rumps.MenuItem("Active Sessions")
        self._sessions_menu.add(rumps.MenuItem("  (no active sessions)"))

        mode = self.config.get("extraction_mode", "smart")
        self._mode_smart = rumps.MenuItem("Mode: Smart", callback=self._set_smart)
        self._mode_full = rumps.MenuItem("Mode: Full", callback=self._set_full)
        (self._mode_smart if mode == "smart" else self._mode_full).state = 1

        self.menu = [
            self._sessions_menu,
            None,
            rumps.MenuItem("Open Summaries Folder", callback=self._open_summaries),
            rumps.MenuItem("Open Error Log", callback=self._open_errors),
            None,
            self._mode_smart,
            self._mode_full,
            None,
            rumps.MenuItem("Quit cc-brain", callback=self._quit),
        ]

        if not self.config.get("openrouter_api_key"):
            self.logger.error("No OpenRouter API key found in config or environment")
            self._set_icon("error")

        self._watcher = TranscriptWatcher(
            callback=self._on_jsonl_changed,
            debounce_seconds=self.config.get("debounce_seconds", 3),
        )

    def _set_icon(self, state):
        icon_name = "brain-active.png" if state == "syncing" else "brain-idle.png"
        icon_file = ICONS_DIR / icon_name
        if icon_file.exists():
            self.icon = str(icon_file)

    def _open_summaries(self, _):
        subprocess.run(["open", self.config["summary_dir"]])

    def _open_errors(self, _):
        path = self.config["error_log"]
        if Path(path).exists():
            subprocess.run(["open", path])
        else:
            rumps.notification("cc-brain", "", "No error log file found yet.")

    def _set_smart(self, _):
        self.config["extraction_mode"] = "smart"
        self._mode_smart.state = 1
        self._mode_full.state = 0

    def _set_full(self, _):
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
            label = f"  {info.get('name', '?')} — {info.get('cwd', '')}"
            self._sessions_menu.add(rumps.MenuItem(label, callback=self._open_summary_cb(sid)))

    def _open_summary_cb(self, session_id):
        def cb(_):
            filename = get_summary_filename(session_id)
            if filename:
                path = Path(self.config["summary_dir"]) / filename
                if path.exists():
                    subprocess.run(["open", str(path)])
                    return
            rumps.notification("cc-brain", "", "No summary yet for this session.")
        return cb

    def _on_jsonl_changed(self, jsonl_path):
        """Called from watchdog thread. Dispatch to a worker thread so we don't block the watcher."""
        t = threading.Thread(target=self._process_delta, args=(jsonl_path,), daemon=True)
        t.start()

    def _process_delta(self, jsonl_path):
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

        self._set_icon("syncing")
        self.logger.info("Processing delta for %s (%d chars)", session_id, len(delta_text))

        if update_summary(self.config, session_id, info, delta_text):
            save_offset(session_id, new_offset)
            self._set_icon("idle")
        else:
            self._set_icon("error")

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
    CCBrainApp().run()


if __name__ == "__main__":
    main()
