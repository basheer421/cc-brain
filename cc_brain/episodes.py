"""Parse session summaries (~/.cc-brain/summaries/*.md) into time-stamped episode chunks."""

import re
from datetime import datetime
from pathlib import Path

_FIELD = re.compile(r"^\*\*(Project|Session|Started|Last updated):\*\*\s*(.*?)\s*$", re.M)
PROGRESS_CHUNK = 5


def project_slug(cwd):
    if not cwd or cwd.strip() in ("/", "~") or Path(cwd) == Path.home():
        return "global"
    name = Path(cwd.rstrip("/")).name.lower()
    return re.sub(r"[^a-z0-9]+", "-", name).strip("-") or "global"


def _parse_dt(value):
    value = (value or "").strip().replace("T", " ")
    for fmt, n in (("%Y-%m-%d %H:%M", 16), ("%Y-%m-%d", 10)):
        try:
            return datetime.strptime(value[:n], fmt)
        except ValueError:
            continue
    return None


def _sections(text):
    out, name, buf = {}, None, []
    for line in text.splitlines():
        if line.startswith("## "):
            if name:
                out[name] = "\n".join(buf).strip()
            name, buf = line[3:].strip(), []
        elif name:
            buf.append(line)
    if name:
        out[name] = "\n".join(buf).strip()
    return out


def parse_summary(path):
    """Return (meta, chunks). chunks = [(section, text)]."""
    path = Path(path)
    text = path.read_text(errors="replace")
    fields = {k.lower(): v for k, v in _FIELD.findall(text)}
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), path.stem)
    cwd = fields.get("project", "")
    updated = _parse_dt(fields.get("last updated")) or datetime.fromtimestamp(path.stat().st_mtime)
    meta = {
        "file": path.name,
        "title": title,
        "cwd": cwd,
        "project": project_slug(cwd) if cwd else "global",
        "session": fields.get("session", path.stem),
        "ts": updated.timestamp(),
        "day": updated.strftime("%Y-%m-%d"),
    }
    secs = _sections(text)
    chunks = []
    overview = "\n".join(
        p for p in (f"{title}", secs.get("Goal", ""), "Now: " + secs["Current State"] if secs.get("Current State") else "") if p
    )
    chunks.append(("overview", overview))
    bullets = [l for l in secs.get("Progress", "").splitlines() if l.strip()]
    for i in range(0, len(bullets), PROGRESS_CHUNK):
        chunks.append(("progress", "\n".join(bullets[i:i + PROGRESS_CHUNK])))
    for name in ("Key Decisions", "Files Changed"):
        if secs.get(name):
            chunks.append((name.lower().replace(" ", "_"), secs[name][:3000]))
    return meta, [(s, t) for s, t in chunks if t.strip()]
