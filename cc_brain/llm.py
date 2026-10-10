"""LLM provider chain for cc-brain's background calls (summaries, memory ops, sleep).

config["llm"]["chain"] is an ordered list of providers; the first that answers wins:
  {"name": "agy",       "type": "agy",    "model": "gemini-3.8-flash-low"}          # Google sub via Antigravity CLI
  {"name": "meridian",  "type": "openai", "api_base_url": "http://localhost:3456/v1", "model": "claude-sonnet-5"}
  {"name": "openrouter","type": "openai", "api_base_url": "...", "api_key": "...", "model": "...", "extra_body": {...}}
Task settings (llm.<task>.max_tokens etc.) apply to openai-type providers. Without a chain, the
legacy single endpoint (llm.default merged with llm.<task>) is used.

Contract (unchanged from the old daemon._call_api): returns the text, or None. Truncated output is
never returned; meta["truncated"] = True tells the caller to retry shorter.
Every attempt is appended to ~/.cc-brain/logs/llm.jsonl for cost/quality monitoring.
"""

import json
import logging
import re
import subprocess
import tempfile
import time
from pathlib import Path

from .config import get_llm_config

logger = logging.getLogger("cc-brain")

LOG = Path.home() / ".cc-brain" / "logs" / "llm.jsonl"
COOLDOWN_S = 900          # skip a provider this long after a hard failure (no credit, down, auth)
AGY_MAX_PROMPT = 400_000  # argv limit is ~1 MB on macOS; bigger prompts go to the next provider
MAX_CALL_S = 180          # wall-clock cap per provider attempt (llm.max_call_seconds overrides)
MIN_GAP_S = 5             # min wall-clock gap between call starts (llm.min_interval_s) — keeps replays slow
_cooldown = {}
_last_call = 0.0


class HardFail(Exception):
    """Provider unusable for a while (402/401/429/connection refused/binary missing)."""


def _log(entry):
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _strip_fence(text):
    m = re.fullmatch(r"\s*```[a-zA-Z]*\n(.*?)\n```\s*", text or "", flags=re.S)
    return m.group(1) if m else text


def _openai(p, task_cfg, messages, json_mode, meta):
    import requests

    url = p.get("api_base_url", "").rstrip("/")
    headers = {"Content-Type": "application/json", **p.get("extra_headers", {})}
    # no key in the chain entry: reuse the legacy key (config/dotfile/env) when it targets the same endpoint
    key = p.get("api_key") or (task_cfg.get("api_key") if task_cfg.get("api_base_url", "").rstrip("/") == url else None)
    if key:
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": p["model"], "messages": messages,
            "max_tokens": p.get("max_tokens") or task_cfg.get("max_tokens", 4000)}
    if json_mode and p.get("json_mode", True):
        body["response_format"] = {"type": "json_object"}
    body.update(p.get("extra_body", {}))
    try:
        resp = requests.post(f"{url}/chat/completions", json=body, headers=headers,
                             timeout=(10, min(p.get("timeout", 180), meta["cap"])))
    except requests.ConnectionError as e:
        raise HardFail(f"connection: {e.__class__.__name__}")
    if resp.status_code in (401, 402, 403, 429):
        raise HardFail(f"HTTP {resp.status_code}: {resp.text[:160]}")
    resp.raise_for_status()
    j = resp.json()
    choice = j["choices"][0]
    usage = j.get("usage") or {}
    meta["usage"] = {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens") if k in usage}
    if choice.get("finish_reason") == "length":
        meta["truncated"] = True
        return None
    return choice["message"]["content"]


def _agy(p, task_cfg, messages, json_mode, meta):
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    user = "\n\n".join(m["content"] for m in messages if m["role"] != "system")
    prompt = (f"<instructions>\n{system}\n</instructions>\n\n<input>\n{user}\n</input>\n\n"
              "Do not use any tools, do not read or write files. Reply with the requested output only"
              + (" — a single JSON object." if json_mode else "."))
    if len(prompt) > AGY_MAX_PROMPT:
        raise ValueError(f"prompt {len(prompt)} chars > agy limit")
    cmd = [p.get("bin", "agy"), "-p", prompt, "--model", p["model"], "--output-format", "text",
           "--disable-slash-commands", "--print-timeout", f"{p.get('timeout', 240)}s"]
    # empty cwd: agy is an agent; without --dangerously-skip-permissions its tool calls are soft-denied anyway
    # Deadline on the wall clock (time.time), not the monotonic clock subprocess.run uses: macOS
    # pauses the monotonic clock during sleep, which let one call run 87 min across a lid-close.
    deadline = time.time() + meta["cap"]
    with tempfile.TemporaryDirectory(prefix="cc-brain-agy-") as cwd, \
            tempfile.TemporaryFile("w+") as fout, tempfile.TemporaryFile("w+") as ferr:
        try:
            proc = subprocess.Popen(cmd, stdout=fout, stderr=ferr, text=True, cwd=cwd)
        except FileNotFoundError:
            raise HardFail("agy binary not found")
        while proc.poll() is None:
            if time.time() > deadline:
                proc.kill()
                proc.wait()
                raise TimeoutError(f"agy exceeded {meta['cap']}s wall clock")
            time.sleep(1)
        fout.seek(0)
        ferr.seek(0)
        stdout, stderr = fout.read(), ferr.read()
    out = (stdout or "").strip()
    if proc.returncode != 0 or not out:
        err = (stderr or out)[-300:]
        if re.search(r"auth|login|quota|exhausted|rate.?limit|429|permission denied", err, re.I):
            raise HardFail(f"agy rc={proc.returncode}: {err}")
        raise RuntimeError(f"agy rc={proc.returncode}: {err}")
    meta["usage"] = {"prompt_chars": len(prompt), "output_chars": len(out)}
    return _strip_fence(out)


def call_api(config, messages, task="default", json_mode=False, meta=None):
    meta = {} if meta is None else meta
    task_cfg = get_llm_config(config, task)
    global _last_call
    llm_cfg = config.get("llm") or {}
    chain = llm_cfg.get("chain") or [dict(task_cfg, name="legacy", type="openai")]
    now = time.time()
    for p in chain:
        name = p.get("name", p.get("type"))
        if _cooldown.get(name, 0) > now:
            continue
        wait = _last_call + llm_cfg.get("min_interval_s", MIN_GAP_S) - time.time()
        if wait > 0:
            time.sleep(wait)
        _last_call = time.time()
        cap = min(p.get("timeout", MAX_CALL_S), llm_cfg.get("max_call_seconds", MAX_CALL_S))
        attempt = {"cap": cap}
        t0 = time.time()
        status = "ok"
        try:
            fn = _agy if p.get("type") == "agy" else _openai
            text = fn(p, task_cfg, messages, json_mode, attempt)
            if text is None:
                status = "truncated" if attempt.get("truncated") else "empty"
        except HardFail as e:
            _cooldown[name] = time.time() + COOLDOWN_S
            status, text = f"hardfail: {e}"[:300], None
        except Exception as e:  # timeouts, 5xx, bad output: try the next provider, no cooldown
            status, text = f"error: {e}"[:300], None
        _log({"ts": round(t0), "task": task, "provider": name, "model": p.get("model"),
              "status": status, "secs": round(time.time() - t0, 1), **attempt.get("usage", {})})
        if text:
            meta["provider"] = name
            return text
        if status != "ok":
            logger.warning("LLM %s/%s failed (task=%s): %s", name, p.get("model"), task, status)
        if status == "truncated":
            meta["truncated"] = True  # let the caller retry shorter rather than burn the whole chain
            return None
    logger.error("LLM chain exhausted (task=%s)", task)
    return None
