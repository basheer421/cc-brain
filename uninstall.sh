#!/usr/bin/env bash
# Remove cc-brain: service, MCP registrations, Pi extension, then the program.
# Your memory in ~/.cc-brain is kept unless you pass --purge.
set -euo pipefail

ccb="$(command -v cc-brain || echo "$HOME/.local/bin/cc-brain")"
if [ -x "$ccb" ]; then
  "$ccb" uninstall "$@"
fi

if command -v uv >/dev/null 2>&1 && uv tool list 2>/dev/null | grep -q '^cc-brain '; then
  uv tool uninstall cc-brain
fi
if [ -d "$HOME/.local/share/cc-brain" ]; then
  rm -rf "$HOME/.local/share/cc-brain"
  rm -f "$HOME/.local/bin/cc-brain"
fi
echo "cc-brain removed."
