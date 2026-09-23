import json
import os
from pathlib import Path

CONFIG_PATH = Path.home() / ".cc-brain" / "config.json"

DEFAULTS = {
    "extraction_mode": "smart",
    "debounce_seconds": 3,
    "summary_dir": str(Path.home() / ".cc-brain" / "summaries"),
    "error_log": str(Path.home() / ".cc-brain" / "logs" / "errors.log"),
    "wiki_dir": str(Path.home() / "llm-wiki"),
    "queue_dir": str(Path.home() / ".cc-brain" / "queue"),
    "state_dir": str(Path.home() / ".cc-brain" / "state"),
    "search_db": str(Path.home() / ".cc-brain" / "search.db"),
    "pid_file": str(Path.home() / ".cc-brain" / "cc-brain.pid"),
    "consolidation_min_interval_s": 900,
    "skills_min_interval_s": 1800,
    "failures_min_interval_s": 1800,
    "identity_min_interval_s": 3600,
    "llm": {
        "default": {
            "api_base_url": "",
            "api_key": "",
            "model": "qwen3.8-27b",
            "max_tokens": 4000,
            "extra_headers": {},
            "extra_body": {},
        },
    },
}


def _deep_merge(base, override):
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def load_config(path=None):
    path = Path(path) if path else CONFIG_PATH
    config = dict(DEFAULTS)

    if path.exists():
        with open(path) as f:
            user_config = json.load(f)
        config = _deep_merge(config, user_config)

    if key := os.environ.get("OPENROUTER_API_KEY"):
        config.setdefault("openrouter_api_key", key)

    for d in ("summary_dir", "error_log", "wiki_dir", "queue_dir", "state_dir"):
        config[d] = str(Path(config[d]).expanduser())

    Path(config["summary_dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["error_log"]).parent.mkdir(parents=True, exist_ok=True)
    Path(config["queue_dir"]).mkdir(parents=True, exist_ok=True)
    Path(config["state_dir"]).mkdir(parents=True, exist_ok=True)

    return config


def get_llm_config(config, task="default"):
    """Get LLM config for a specific task, falling back to default."""
    llm = config.get("llm", {})
    default = llm.get("default", {})
    task_config = llm.get(task, {})
    merged = {**default, **task_config}

    # Legacy top-level keys for backward compat
    if not merged.get("api_base_url"):
        merged["api_base_url"] = config.get("api_base_url", "")
    if not merged.get("api_key"):
        merged["api_key"] = config.get("api_key", "") or config.get("openrouter_api_key", "")
    if not merged.get("model") or merged["model"] == DEFAULTS["llm"]["default"]["model"]:
        if config.get("model"):
            merged["model"] = config["model"]

    return merged
