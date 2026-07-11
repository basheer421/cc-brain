#!/bin/bash
set -e

echo "Uninstalling CC Brain..."

# Stop if running
pkill -f "CC Brain.app" 2>/dev/null || true

# Remove app
rm -rf "/Applications/CC Brain.app"
echo "  Removed /Applications/CC Brain.app"

# Remove launchd plist if present
PLIST="$HOME/Library/LaunchAgents/io.ccbrain.agent.plist"
if [ -f "$PLIST" ]; then
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "  Removed launchd plist"
fi

echo ""
echo "Uninstalled. Your data is preserved at ~/.cc-brain/"
echo "To remove data too: rm -rf ~/.cc-brain"
