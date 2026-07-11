import json
import os
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".cc-brain" / "config.json"

DEFAULTS = {
    "model": "deepseek/deepseek-v4-flash",
    "extraction_mode": "smart",
    "debounce_seconds": 3,
    "summary_dir": "~/.cc-brain/summaries",
    "error_log": "~/.cc-brain/logs/errors.log",
}


def load_config(path=None):
    path = Path(path) if path else DEFAULT_CONFIG_PATH
    config = dict(DEFAULTS)

    if path.exists():
        with open(path) as f:
            config.update(json.load(f))

    api_key = os.environ.get("OPENROUTER_API_KEY")
    if api_key:
        config["openrouter_api_key"] = api_key

    config["summary_dir"] = str(Path(config["summary_dir"]).expanduser())
    config["error_log"] = str(Path(config["error_log"]).expanduser())

    Path(config["summary_dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["error_log"]).parent.mkdir(parents=True, exist_ok=True)

    return config
