"""File-based suggestion queue for agent writes."""

import json
import logging
import re
import time
import uuid
from pathlib import Path

logger = logging.getLogger("cc-brain")

SECRET_PATTERNS = [
    re.compile(r"(?:sk|pk|api[_-]?key)[_-][\w\-]{20,}", re.I),
    re.compile(r"ghp_[A-Za-z0-9_]{36,}"),
    re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    re.compile(r"Bearer\s+[A-Za-z0-9\-._~+/]+=*", re.I),
    re.compile(r"(?:password|secret|token)\s*[:=]\s*['\"][^'\"]{8,}['\"]", re.I),
]


def _has_secrets(text):
    for pat in SECRET_PATTERNS:
        if pat.search(text):
            return True
    return False


def enqueue(queue_dir, target, content, suggest_type="add"):
    if _has_secrets(content):
        return None, "Content contains potential secrets — rejected"

    suggestion = {
        "id": str(uuid.uuid4()),
        "timestamp": time.time(),
        "target": target,
        "content": content,
        "type": suggest_type,
    }

    queue_path = Path(queue_dir)
    queue_path.mkdir(parents=True, exist_ok=True)
    filename = f"{int(time.time())}-{suggestion['id'][:8]}.json"
    filepath = queue_path / filename

    filepath.write_text(json.dumps(suggestion, indent=2))
    logger.info("Queued suggestion %s for %s", suggestion["id"][:8], target)
    return suggestion["id"], None


def list_pending(queue_dir):
    queue_path = Path(queue_dir)
    if not queue_path.exists():
        return []

    pending = []
    for f in sorted(queue_path.glob("*.json")):
        try:
            data = json.loads(f.read_text())
            data["_file"] = str(f)
            pending.append(data)
        except (json.JSONDecodeError, OSError):
            continue
    return pending


def remove(filepath):
    try:
        Path(filepath).unlink()
    except OSError:
        pass
