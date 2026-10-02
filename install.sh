#!/usr/bin/env bash
# cc-brain installer.   curl -sSL cc-brain.bachir.me | bash      (args: ... | bash -s -- --yes)
#
# Puts the `cc-brain` binary on disk, then runs `cc-brain init` for the rest (config, service, MCP).
#   - with uv (recommended):  uv tool install   → isolated env, `uv tool upgrade cc-brain` later
#   - without uv:             python3 -m venv ~/.local/share/cc-brain/venv + pip, linked into ~/.local/bin
# It never installs uv, Python or anything system-wide, and never uses sudo.
#
# Env: CC_BRAIN_SOURCE=<path|url>  install from a local checkout or another archive (default: GitHub main)
set -euo pipefail

main() {
  local bold=$'\033[1m' green=$'\033[32m' yellow=$'\033[33m' red=$'\033[31m' reset=$'\033[0m'
  info() { printf '%s==>%s %s%s%s\n' "$green" "$reset" "$bold" "$1" "$reset"; }
  warn() { printf '%s==>%s %s\n' "$yellow" "$reset" "$1"; }
  die()  { printf '%s==>%s %s\n' "$red" "$reset" "$1" >&2; exit 1; }

  case "$(uname -s)" in
    Darwin|Linux) ;;
    *) die "cc-brain supports macOS and Linux (found $(uname -s))." ;;
  esac

  local src="${CC_BRAIN_SOURCE:-https://github.com/basheer421/cc-brain/archive/refs/heads/main.tar.gz}"
  local bin_dir="$HOME/.local/bin" editable=""
  if [ -d "$src" ]; then
    src="$(cd "$src" && pwd)"
    editable="--editable"   # local checkout: code edits apply without reinstalling
  fi

  if command -v uv >/dev/null 2>&1; then
    info "Installing cc-brain with uv ($(uv --version))"
    uv tool install --force --quiet $editable "$src"
    bin_dir="$(uv tool dir --bin)"
  else
    local py=""
    for c in python3.13 python3.12 python3.11 python3.10 python3; do
      if command -v "$c" >/dev/null 2>&1 &&
         "$c" -c 'import sys, venv; sys.exit(sys.version_info < (3, 10))' 2>/dev/null; then
        py="$(command -v "$c")"; break
      fi
    done
    if [ -z "$py" ]; then
      die "cc-brain needs uv (recommended) or Python 3.10+. Install uv: https://docs.astral.sh/uv/getting-started/installation/ then re-run."
    fi
    warn "uv not found; using pip in a private venv ($py). uv is recommended: https://docs.astral.sh/uv/"
    local venv="$HOME/.local/share/cc-brain/venv"
    "$py" -m venv --clear "$venv"
    "$venv/bin/python" -m pip install --quiet --upgrade pip
    "$venv/bin/python" -m pip install --quiet $editable "$src"
    mkdir -p "$bin_dir"
    ln -sf "$venv/bin/cc-brain" "$bin_dir/cc-brain"
  fi

  local ccb="$bin_dir/cc-brain"
  [ -x "$ccb" ] || die "install finished but $ccb is missing"
  info "Installed $("$ccb" --version 2>/dev/null || echo cc-brain) → $ccb"
  case ":$PATH:" in
    *":$bin_dir:"*) ;;
    *) warn "$bin_dir is not on your PATH. Add it:  echo 'export PATH=\"$bin_dir:\$PATH\"' >> ~/.zshrc  (or ~/.bashrc)" ;;
  esac

  # curl | bash: stdin is the script, so prompts read from the terminal; no terminal → defaults
  if [ -r /dev/tty ] && [ -w /dev/tty ] && { : </dev/tty; } 2>/dev/null; then
    "$ccb" init "$@" </dev/tty
  else
    "$ccb" init --yes "$@"
  fi
}

main "$@"
