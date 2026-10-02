"""`cc-brain init`, `doctor`, `uninstall`: everything around the installed package.

install.sh only puts the `cc-brain` binary on disk (uv tool, or pip in a private venv). All machine setup
lives here so it is idempotent, re-runnable, and testable against a throwaway HOME:
config + LLM provider detection, local embeddings, background service, MCP registration, Pi extension.

Nothing is installed system-wide. Optional tools (uv, Ollama, agy) are detected, never installed.
"""

import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import click

HOME = Path.home()
DATA = HOME / ".cc-brain"
CONFIG = DATA / "config.json"
ENV_FILE = DATA / ".env"
LOG_DIR = DATA / "logs"
BACKUP = DATA / "backup"

LABEL = os.environ.get("CC_BRAIN_SERVICE_LABEL", "io.ccbrain.daemon")  # override only for tests
LEGACY_LABELS = ("io.ccbrain.agent",)  # v1 menu-bar app
LAUNCH_AGENTS = HOME / "Library" / "LaunchAgents"
SYSTEMD_UNIT = HOME / ".config" / "systemd" / "user" / "cc-brain.service"
PIP_VENV = HOME / ".local" / "share" / "cc-brain" / "venv"   # pip fallback location (install.sh)

PI_DIR = HOME / ".pi" / "agent"
PI_EXT = PI_DIR / "extensions" / "cc-brain-recall.ts"
EXT_SRC = Path(__file__).parent / "integrations" / "pi" / "cc-brain-recall.ts"

EMBED_URL = "http://localhost:11434"
EMBED_MODEL = "nomic-embed-text"
OPENROUTER = "https://openrouter.ai/api/v1"
MERIDIAN = "http://localhost:3456/v1"

AGENT_SNIPPET = """\
## Memory (cc-brain)
Before planning, debugging or asking about past work, call `recall` (2-3 phrasings, concrete terms).
"What did I do / where did we leave X" -> `timeline`. Save durable lessons with `remember`
(one claim <= 200 chars, rule + why); fix wrong ones with `correct(id, text)`."""


# ── helpers ──────────────────────────────────────────────────────────────────

def _ok(msg):
    click.echo(f"  {click.style('✓', fg='green')} {msg}")


def _warn(msg):
    click.echo(f"  {click.style('!', fg='yellow')} {msg}")


def _fail(msg):
    click.echo(f"  {click.style('✗', fg='red')} {msg}")


def _step(msg):
    click.echo(click.style(f"\n==> {msg}", bold=True))


def bin_path():
    """Stable path to the cc-brain binary. ~/.local/bin survives `uv tool upgrade`; venv paths don't."""
    local = HOME / ".local" / "bin" / "cc-brain"
    if local.exists():
        return str(local)
    found = shutil.which("cc-brain")
    return found or str(Path(sys.argv[0]).absolute())


def _find(cmd):
    return shutil.which(cmd) or next((str(p) for p in [HOME / ".local" / "bin" / cmd] if p.exists()), None)


def _http_ok(url, timeout=2.0):
    import requests
    try:
        return requests.get(url, timeout=timeout).status_code < 500
    except requests.RequestException:
        return False


def _read_json(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".cc-brain-tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n")
    os.replace(tmp, path)


def _backup(path):
    BACKUP.mkdir(parents=True, exist_ok=True)
    dest = BACKUP / f"{path.name}.{int(__import__('time').time())}"
    shutil.copy2(path, dest)
    return dest


def _version():
    try:
        from importlib.metadata import version
        return version("cc-brain")
    except Exception:
        return "unknown"


def _install_method():
    exe = Path(sys.prefix).resolve().as_posix()
    if "/uv/tools/" in exe:
        return "uv tool"
    if exe == PIP_VENV.resolve().as_posix():
        return "pip (private venv)"
    return f"python env ({sys.executable})"


# ── LLM providers ────────────────────────────────────────────────────────────

def detect_providers():
    """Providers usable right now, in preference order. Nothing here costs a token."""
    found = []
    agy = _find("agy")
    if agy:
        found.append({"name": "agy", "type": "agy", "model": "gemini-3.8-flash-low", "timeout": 240, "bin": agy})
    if _http_ok(f"{MERIDIAN}/models", timeout=1.5):
        found.append({"name": "meridian", "type": "openai", "api_base_url": MERIDIAN,
                      "model": "claude-sonnet-5", "json_mode": False, "timeout": 240})
    if _openrouter_key():
        found.append(_openrouter_entry())
    return found


def _openrouter_entry():
    return {"name": "openrouter", "type": "openai", "api_base_url": OPENROUTER,
            "model": "deepseek/deepseek-v4.1-flash", "extra_body": {"reasoning": {"effort": "low"}}}


def _openrouter_key():
    if os.environ.get("OPENROUTER_API_KEY"):
        return os.environ["OPENROUTER_API_KEY"]
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text().splitlines():
            if line.strip().startswith("OPENROUTER_API_KEY="):
                return line.split("=", 1)[1].strip()
    return None


def _save_env_key(name, value):
    lines = [l for l in (ENV_FILE.read_text().splitlines() if ENV_FILE.exists() else [])
             if not l.strip().startswith(f"{name}=")]
    lines.append(f"{name}={value}")
    ENV_FILE.write_text("\n".join(lines) + "\n")
    ENV_FILE.chmod(0o600)


def setup_config(interactive):
    _step("Config and LLM providers")
    for d in ("summaries", "state", "logs", "queue"):
        (DATA / d).mkdir(parents=True, exist_ok=True)

    if CONFIG.exists():
        cfg = _read_json(CONFIG)
        if cfg is None:
            _fail(f"{CONFIG} is not valid JSON; fix it and re-run")
            return False
        chain = (cfg.get("llm") or {}).get("chain")
        _ok(f"keeping existing {CONFIG} ({len(chain or [])} providers in chain)")
        return True

    chain = detect_providers()
    for p in chain:
        _ok(f"found {p['name']} ({p['model']})")
    if not any(p["name"] == "openrouter" for p in chain) and interactive:
        click.echo("  An OpenRouter key adds a pay-per-use fallback (~$2/week at heavy use). Enter to skip.")
        key = click.prompt("  OpenRouter API key", default="", show_default=False, hide_input=True).strip()
        if key:
            _save_env_key("OPENROUTER_API_KEY", key)
            chain.append(_openrouter_entry())
            _ok("saved key to ~/.cc-brain/.env (chmod 600)")
    if not chain:
        _warn("no LLM provider found: memory search works, but new sessions won't be distilled.")
        _warn("add one later in ~/.cc-brain/config.json → llm.chain (see README → LLM providers), then `cc-brain doctor`")

    cfg = {"llm": {"chain": chain, "consolidation": {"max_tokens": 12000}}}
    if any(p["name"] == "openrouter" for p in chain):
        # the key comes from ~/.cc-brain/.env; it is matched to the chain entry by base URL
        cfg["llm"]["default"] = {"api_base_url": OPENROUTER, "model": "deepseek/deepseek-v4.1-flash"}
    _write_json(CONFIG, cfg)
    _ok(f"wrote {CONFIG}")
    return True


# ── embeddings ───────────────────────────────────────────────────────────────

def _ollama_models():
    import requests
    try:
        r = requests.get(f"{EMBED_URL}/api/tags", timeout=2)
        return [m.get("name", "") for m in r.json().get("models", [])]
    except Exception:
        return None


def setup_embeddings(interactive):
    _step("Local embeddings (optional)")
    models = _ollama_models()
    if models is None:
        hint = "brew install ollama" if platform.system() == "Darwin" else "https://ollama.com/download"
        _warn(f"Ollama not running: recall uses keyword search only. For semantic recall: {hint}, then re-run `cc-brain init`")
        return
    if any(m.split(":")[0] == EMBED_MODEL for m in models):
        _ok(f"Ollama has {EMBED_MODEL}")
        return
    ollama = _find("ollama")
    if not ollama:
        _warn(f"Ollama is running but the CLI isn't on PATH; run `ollama pull {EMBED_MODEL}`")
        return
    if interactive and not click.confirm(f"  Pull {EMBED_MODEL} (~270 MB) into Ollama?", default=True):
        _warn("skipped; recall uses keyword search only")
        return
    r = subprocess.run([ollama, "pull", EMBED_MODEL])
    (_ok if r.returncode == 0 else _fail)(f"ollama pull {EMBED_MODEL}: rc={r.returncode}")


# ── wiki view ────────────────────────────────────────────────────────────────

def setup_wiki():
    from .config import load_config
    wiki = Path(load_config()["wiki_dir"]).expanduser()
    wiki.mkdir(parents=True, exist_ok=True)
    if not (wiki / ".git").exists() and shutil.which("git"):
        subprocess.run(["git", "init", "-q", str(wiki)], check=False)
    _ok(f"wiki view at {wiki}")


# ── background service ───────────────────────────────────────────────────────

def _plist(label, binary):
    path_dirs = [str(Path(binary).parent), str(HOME / ".local" / "bin"), "/opt/homebrew/bin",
                 "/usr/local/bin", "/usr/bin", "/bin"]
    path = ":".join(dict.fromkeys(path_dirs))
    log = LOG_DIR / "daemon.log"
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>{label}</string>
  <key>ProgramArguments</key>
  <array><string>{binary}</string><string>start</string></array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><dict><key>SuccessfulExit</key><false/></dict>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>{log}</string>
  <key>StandardErrorPath</key><string>{log}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key><string>{path}</string>
    <key>HOME</key><string>{HOME}</string>
  </dict>
</dict>
</plist>
"""


def _launchctl(*args):
    return subprocess.run(["launchctl", *args], capture_output=True, text=True)


def _gui():
    return f"gui/{os.getuid()}"


def _launchd_loaded(label):
    return _launchctl("print", f"{_gui()}/{label}").returncode == 0


def _bootstrap(plist):
    """(Re)load a launch agent. bootout returns before the job is gone; bootstrapping too early fails with
    'Bootstrap failed: 5: Input/output error', so wait for the unload and retry once."""
    import time
    label = plist.stem
    _launchctl("bootout", f"{_gui()}/{label}")
    for attempt in range(2):
        for _ in range(20):
            if not _launchd_loaded(label):
                break
            time.sleep(0.5)
        r = _launchctl("bootstrap", _gui(), str(plist))
        if r.returncode == 0:
            return r
        time.sleep(1)
    return r


def _remove_launchd(label):
    # legacy labels only count when their plist is under this HOME: launchctl sees the real user domain,
    # so a test run with a temp HOME must not stop the real daemon
    plist = LAUNCH_AGENTS / f"{label}.plist"
    if not plist.exists() and (label != LABEL or not _launchd_loaded(label)):
        return False
    was = True
    _launchctl("bootout", f"{_gui()}/{label}")
    plist.unlink(missing_ok=True)
    return was


def setup_service():
    _step("Background service")
    binary = bin_path()
    system = platform.system()
    if system == "Darwin":
        for legacy in LEGACY_LABELS:
            if legacy != LABEL and _remove_launchd(legacy):
                _ok(f"removed old launchd agent {legacy}")
        LAUNCH_AGENTS.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        plist = LAUNCH_AGENTS / f"{LABEL}.plist"
        content = _plist(LABEL, binary)
        if plist.exists() and plist.read_text() == content and _launchd_loaded(LABEL) and service_running():
            _ok(f"launchd agent {LABEL} already running (pid {service_running()})")
            return True
        plist.write_text(content)
        r = _bootstrap(plist)
        if r.returncode != 0:
            _fail(f"launchctl bootstrap failed: {r.stderr.strip()}")
            return False
        _ok(f"launchd agent {LABEL} → {binary} start (log: ~/.cc-brain/logs/daemon.log)")
        _wait_for_daemon()
        return True
    if system == "Linux" and shutil.which("systemctl"):
        SYSTEMD_UNIT.parent.mkdir(parents=True, exist_ok=True)
        SYSTEMD_UNIT.write_text(
            "[Unit]\nDescription=cc-brain memory daemon\n\n"
            f"[Service]\nExecStart={binary} start\nRestart=on-failure\nRestartSec=30\n\n"
            "[Install]\nWantedBy=default.target\n")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        r = subprocess.run(["systemctl", "--user", "enable", "--now", "cc-brain.service"],
                           capture_output=True, text=True)
        (_ok if r.returncode == 0 else _fail)(f"systemd user unit cc-brain.service: {r.stderr.strip() or 'enabled'}")
        if r.returncode == 0:
            _wait_for_daemon()
        return r.returncode == 0
    _warn(f"no service manager support on {system}; run `cc-brain start -b` yourself")
    return False


def _wait_for_daemon(seconds=15):
    """First start indexes docs and backfills embeddings before writing its pid; give it a moment."""
    import time
    for _ in range(seconds * 2):
        if service_running():
            return
        time.sleep(0.5)
    _warn("daemon hasn't written its pid yet; check ~/.cc-brain/logs/daemon.log")


def remove_service():
    removed = []
    if platform.system() == "Darwin":
        for label in (LABEL, *LEGACY_LABELS):
            if _remove_launchd(label):
                removed.append(f"launchd {label}")
    elif SYSTEMD_UNIT.exists():
        subprocess.run(["systemctl", "--user", "disable", "--now", "cc-brain.service"], check=False)
        SYSTEMD_UNIT.unlink()
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        removed.append("systemd cc-brain.service")
    return removed


def service_running():
    from .config import load_config
    pid_file = Path(load_config()["pid_file"])
    try:
        pid = int(pid_file.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (OSError, ValueError):
        return None


# ── agent integrations ───────────────────────────────────────────────────────

def mcp_targets():
    """(client name, config path, entry extras) for every agent found on this machine."""
    targets = []
    if PI_DIR.exists():
        # directTools: pi-mcp-adapter exposes recall/timeline as first-class tools instead of via a proxy
        targets.append(("Pi", PI_DIR / "mcp.json", {"directTools": True}))
    if (HOME / ".claude.json").exists() or shutil.which("claude"):
        targets.append(("Claude Code", HOME / ".claude.json", {}))
    if (HOME / ".config" / "mcp" / "mcp.json").exists():
        targets.append(("shared mcp.json", HOME / ".config" / "mcp" / "mcp.json", {}))
    return targets


def setup_mcp(interactive):
    _step("MCP server registration")
    binary = bin_path()
    targets = mcp_targets()
    if not targets:
        _warn("no MCP client found (Pi, Claude Code). Register manually: "
              f'{{"mcpServers": {{"cc-brain": {{"command": "{binary}", "args": ["mcp"]}}}}}}')
    for name, path, extra in targets:
        data = _read_json(path) if path.exists() else {}
        if data is None:
            _fail(f"{name}: {path} is not valid JSON; skipped")
            continue
        entry = {"command": binary, "args": ["mcp"], **extra}
        servers = data.setdefault("mcpServers", {})
        if servers.get("cc-brain") == entry:
            _ok(f"{name}: already registered")
            continue
        if interactive and not click.confirm(f"  Register cc-brain with {name} ({path})?", default=True):
            continue
        if path.exists():
            _backup(path)
        servers["cc-brain"] = entry
        _write_json(path, data)
        _ok(f"{name}: registered in {path}")
    if (HOME / ".hermes").exists():
        _warn(f"Hermes found: add an mcp_servers entry for `{binary} mcp` in ~/.hermes/config.yaml")


def remove_mcp():
    removed = []
    for name, path, _ in mcp_targets():
        data = _read_json(path) if path.exists() else None
        entry = (data or {}).get("mcpServers", {}).get("cc-brain")
        if entry and "cc-brain" in str(entry.get("command", "")):
            _backup(path)
            del data["mcpServers"]["cc-brain"]
            _write_json(path, data)
            removed.append(f"MCP entry in {path}")
    return removed


def setup_pi_extension():
    if not PI_DIR.exists():
        return
    _step("Pi auto-recall extension")
    PI_EXT.parent.mkdir(parents=True, exist_ok=True)
    if PI_EXT.is_symlink() and PI_EXT.resolve() == EXT_SRC.resolve():
        _ok(f"already linked: {PI_EXT}")
        return
    if PI_EXT.exists() or PI_EXT.is_symlink():
        if PI_EXT.exists() and not PI_EXT.is_symlink():
            _ok(f"backed up old copy to {_backup(PI_EXT)}")
        PI_EXT.unlink()
    PI_EXT.symlink_to(EXT_SRC)
    _ok(f"linked {PI_EXT} → package copy (updates with cc-brain; `/reload` in Pi to activate)")


def remove_pi_extension():
    if PI_EXT.is_symlink() or PI_EXT.exists():
        PI_EXT.unlink()
        return [str(PI_EXT)]
    return []


# ── commands ─────────────────────────────────────────────────────────────────

def run_init(yes, service, mcp, pi_extension):
    interactive = not yes and sys.stdin.isatty()
    click.echo(click.style(f"cc-brain {_version()} setup", bold=True) + f"  ({_install_method()}, {bin_path()})")
    if not setup_config(interactive):
        sys.exit(1)
    setup_embeddings(interactive)
    setup_wiki()
    if mcp:
        setup_mcp(interactive)
    if pi_extension:
        setup_pi_extension()
    if service:
        setup_service()
    _step("Tell your agent to use it")
    click.echo("  Add this to your AGENTS.md / CLAUDE.md (cc-brain never edits those files):\n")
    click.echo("\n".join("    " + l for l in AGENT_SNIPPET.splitlines()))
    click.echo("")
    sys.exit(run_doctor())


def run_doctor():
    """Print every check; return 0 when nothing is broken (warnings allowed), else 1."""
    from .config import load_config

    click.echo(click.style("\ncc-brain doctor", bold=True))
    bad = 0

    def check(status, msg):
        nonlocal bad
        {"ok": _ok, "warn": _warn, "fail": _fail}[status](msg)
        bad += status == "fail"

    check("ok", f"cc-brain {_version()} via {_install_method()} → {bin_path()}")
    if not shutil.which("uv"):
        check("warn", "uv not found (recommended for installs and upgrades: https://docs.astral.sh/uv/)")

    cfg_raw = _read_json(CONFIG) if CONFIG.exists() else None
    if cfg_raw is None:
        check("fail", f"config missing or invalid: {CONFIG} (run `cc-brain init`)")
        return 1
    cfg = load_config()
    chain = (cfg.get("llm") or {}).get("chain") or []
    usable = 0
    for p in chain:
        name = p.get("name", p.get("type"))
        if p.get("type") == "agy":
            agy = p.get("bin") if p.get("bin") and Path(p["bin"]).exists() else shutil.which(p.get("bin", "agy"))
            ok = bool(agy)
            check("ok" if ok else "fail", f"provider {name}: {'binary ' + agy if ok else 'binary not found (set an absolute bin)'}")
        else:
            url = p.get("api_base_url", "").rstrip("/")
            local = url.startswith(("http://localhost", "http://127."))
            key = p.get("api_key") or (_openrouter_key() if "openrouter.ai" in url else None)
            reach = _http_ok(f"{url}/models", timeout=3)
            ok = reach and (local or bool(key))
            why = "reachable" if ok else ("unreachable" if not reach else "no API key (~/.cc-brain/.env)")
            check("ok" if ok else "warn", f"provider {name}: {url} {why}")
        usable += ok
    if not chain:
        check("fail", "no LLM provider in llm.chain: new sessions won't be distilled")
    elif not usable:
        check("fail", "no LLM provider usable right now")

    models = _ollama_models()
    if models is None:
        check("warn", "Ollama not running: keyword-only recall")
    elif not any(m.split(":")[0] == EMBED_MODEL for m in models):
        check("warn", f"Ollama is missing {EMBED_MODEL}: run `ollama pull {EMBED_MODEL}`")
    else:
        check("ok", f"embeddings: Ollama {EMBED_MODEL}")

    db = Path(cfg["brain_db"])
    if db.exists():
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            facts = con.execute("SELECT COUNT(*) FROM facts WHERE superseded_by IS NULL").fetchone()[0]
            eps = con.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]
            check("ok", f"memory: {facts} facts, {eps} episode chunks ({db})")
        except sqlite3.Error as e:
            check("fail", f"memory DB unreadable: {e}")
        finally:
            con.close()
    else:
        check("warn", "memory DB not created yet (the daemon creates it on first start)")

    pid = service_running()
    if platform.system() == "Darwin":
        loaded = _launchd_loaded(LABEL)
        check("ok" if loaded and pid else "fail",
              f"daemon: launchd {LABEL} {'loaded' if loaded else 'NOT loaded'}, "
              f"{'running pid ' + str(pid) if pid else 'not running'} (log: ~/.cc-brain/logs/daemon.log)")
        for legacy in LEGACY_LABELS:
            if legacy != LABEL and (LAUNCH_AGENTS / f"{legacy}.plist").exists():
                check("warn", f"old launchd agent {legacy} still loaded: re-run `cc-brain init`")
    else:
        check("ok" if pid else "fail", f"daemon: {'running pid ' + str(pid) if pid else 'not running'}")

    for name, path, _ in mcp_targets():
        entry = ((_read_json(path) or {}).get("mcpServers") or {}).get("cc-brain") if path.exists() else None
        if not entry:
            check("warn", f"MCP: not registered with {name} (`cc-brain init`)")
        elif not Path(entry.get("command", "")).exists() and not shutil.which(entry.get("command", "")):
            check("fail", f"MCP: {name} points at a missing binary {entry.get('command')} (`cc-brain init`)")
        else:
            check("ok", f"MCP: {name} → {entry['command']}")

    if PI_DIR.exists():
        if PI_EXT.is_symlink() and PI_EXT.exists():
            check("ok", "Pi auto-recall extension linked")
        elif PI_EXT.exists():
            check("warn", "Pi auto-recall extension is a copy, not a link: `cc-brain init` relinks it")
        else:
            check("warn", "Pi auto-recall extension not installed (`cc-brain init`)")

    click.echo(click.style("\nall good" if not bad else f"\n{bad} problem(s)", fg="green" if not bad else "red"))
    return 1 if bad else 0


def run_uninstall(purge, yes):
    removed = remove_service() + remove_mcp() + remove_pi_extension()
    for r in removed:
        _ok(f"removed {r}")
    if not removed:
        _ok("nothing to remove (no service, MCP entries or extension)")
    if purge:
        if yes or click.confirm(f"  Delete {DATA} (all memory, summaries, config)?", default=False):
            shutil.rmtree(DATA, ignore_errors=True)
            _ok(f"deleted {DATA}")
    else:
        _ok(f"kept your memory in {DATA} (use --purge to delete)")
    click.echo("\nTo remove the program itself: "
               + ("`uv tool uninstall cc-brain`" if _install_method() == "uv tool"
                  else f"`rm -rf {PIP_VENV.parent} ~/.local/bin/cc-brain`")
               + "  (uninstall.sh does both steps)")
