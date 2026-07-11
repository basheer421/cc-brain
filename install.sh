#!/bin/bash
set -e

BOLD='\033[1m'
DIM='\033[2m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
RESET='\033[0m'

info()  { echo -e "${GREEN}==>${RESET} ${BOLD}$1${RESET}"; }
warn()  { echo -e "${YELLOW}==>${RESET} ${BOLD}$1${RESET}"; }
error() { echo -e "${RED}==>${RESET} ${BOLD}$1${RESET}"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CONFIG_DIR="$HOME/.cc-brain"
CONFIG_FILE="$CONFIG_DIR/config.json"

# ── Preflight ──────────────────────────────────────────────

info "Checking prerequisites..."

# Python 3.10+
PYTHON="$(command -v python3 2>/dev/null || true)"
if [ -z "$PYTHON" ]; then
    error "python3 not found. Install Python 3.10+ first."
fi

PY_VERSION=$("$PYTHON" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$("$PYTHON" -c "import sys; print(sys.version_info.major)")
PY_MINOR=$("$PYTHON" -c "import sys; print(sys.version_info.minor)")
if [ "$PY_MAJOR" -lt 3 ] || ([ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 10 ]); then
    error "Python 3.10+ required (found $PY_VERSION)"
fi

# Resolve real python binary (not pyenv shim — shims break .app launches)
REAL_PYTHON=$("$PYTHON" -c "import sys; print(sys.executable)")
echo "  Python $PY_VERSION ($REAL_PYTHON)"

# Claude Code installed
if [ ! -d "$HOME/.claude/sessions" ]; then
    error "Claude Code not found (~/.claude/sessions/ missing). Install Claude Code first."
fi
echo "  Claude Code detected"

# macOS
if [ "$(uname)" != "Darwin" ]; then
    error "cc-brain is macOS only."
fi

# ── Dependencies ───────────────────────────────────────────

info "Installing Python dependencies..."
"$PYTHON" -m pip install --quiet rumps watchdog requests Pillow 2>&1 | grep -v "already satisfied" || true

# ── Config ─────────────────────────────────────────────────

mkdir -p "$CONFIG_DIR"/{summaries,state,logs}

if [ ! -f "$CONFIG_FILE" ]; then
    info "Setting up configuration..."

    # Prompt for API key
    echo ""
    echo -e "  ${BOLD}OpenRouter API key required${RESET}"
    echo -e "  ${DIM}Get one at https://openrouter.ai/keys${RESET}"
    echo ""
    read -rp "  API key: " API_KEY

    if [ -z "$API_KEY" ]; then
        warn "No API key provided. You can add it later to $CONFIG_FILE"
        API_KEY=""
    fi

    cat > "$CONFIG_FILE" << CONF
{
  "openrouter_api_key": "$API_KEY",
  "model": "deepseek/deepseek-v4-flash",
  "extraction_mode": "smart",
  "debounce_seconds": 3,
  "summary_dir": "~/.cc-brain/summaries",
  "error_log": "~/.cc-brain/logs/errors.log"
}
CONF
    echo "  Config written to $CONFIG_FILE"
else
    info "Config already exists at $CONFIG_FILE"
fi

# ── Icons ──────────────────────────────────────────────────

if [ ! -f "$SCRIPT_DIR/icons/brain-idle.png" ]; then
    info "Generating menu bar icons..."
    cd "$SCRIPT_DIR"
    "$PYTHON" generate_icons.py
fi

# ── Build .app ─────────────────────────────────────────────

info "Building CC Brain.app..."
cd "$SCRIPT_DIR"
bash build_app.sh

# ── Install ────────────────────────────────────────────────

info "Installing to /Applications..."
if [ -d "/Applications/CC Brain.app" ]; then
    # Kill if running
    pkill -f "CC Brain.app" 2>/dev/null || true
    sleep 1
    rm -rf "/Applications/CC Brain.app"
fi
cp -r "$SCRIPT_DIR/dist/CC Brain.app" /Applications/

# ── Launch ─────────────────────────────────────────────────

info "Launching CC Brain..."
open "/Applications/CC Brain.app"
sleep 2

if pgrep -f "CC Brain" > /dev/null 2>&1; then
    echo ""
    echo -e "  ${GREEN}CC Brain is running!${RESET} Look for the brain icon in your menu bar."
else
    warn "App launched but may not be visible yet. Try opening it from Spotlight."
fi

# ── Done ───────────────────────────────────────────────────

echo ""
echo -e "${BOLD}Setup complete!${RESET}"
echo ""
echo "  Config:    $CONFIG_FILE"
echo "  Summaries: $CONFIG_DIR/summaries/"
echo "  Error log: $CONFIG_DIR/logs/errors.log"
echo "  App:       /Applications/CC Brain.app"
echo ""
echo -e "  ${DIM}To start on login: System Settings > General > Login Items > add CC Brain${RESET}"
echo -e "  ${DIM}To uninstall: ./uninstall.sh${RESET}"
echo ""
