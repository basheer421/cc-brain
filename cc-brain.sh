#!/bin/bash
# cc-brain daemon management script

PLIST_LABEL="io.ccbrain.agent"
PLIST_SRC="$(cd "$(dirname "$0")" && pwd)/io.ccbrain.agent.plist"
PLIST_DST="$HOME/Library/LaunchAgents/io.ccbrain.agent.plist"
LOG_DIR="$HOME/.cc-brain/logs"

case "$1" in
  install)
    # Install dependencies
    echo "Installing Python dependencies..."
    pip3 install -r "$(dirname "$0")/requirements.txt"

    # Create directories
    mkdir -p "$HOME/.cc-brain"/{summaries,state,logs}

    # Generate plist with actual paths
    PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
    PYTHON_PATH="$(which python3)"

    sed -e "s|__PYTHON_PATH__|$PYTHON_PATH|g" \
        -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
        "$PLIST_SRC" > "$PLIST_DST"

    echo "Installed plist to $PLIST_DST"
    echo "Run '$0 start' to launch cc-brain."
    ;;

  start)
    if [ ! -f "$PLIST_DST" ]; then
      echo "Not installed. Run '$0 install' first."
      exit 1
    fi
    launchctl load "$PLIST_DST" 2>/dev/null
    echo "cc-brain started."
    ;;

  stop)
    launchctl unload "$PLIST_DST" 2>/dev/null
    echo "cc-brain stopped."
    ;;

  restart)
    "$0" stop
    sleep 1
    "$0" start
    ;;

  status)
    if launchctl list "$PLIST_LABEL" &>/dev/null; then
      PID=$(launchctl list "$PLIST_LABEL" 2>/dev/null | grep PID | awk '{print $NF}')
      echo "cc-brain is running (PID: $PID)"
    else
      echo "cc-brain is not running."
    fi
    ;;

  logs)
    ERROR_LOG=$(python3 -c "import json; print(json.load(open('$HOME/.cc-brain/config.json')).get('error_log', '$LOG_DIR/errors.log'))" 2>/dev/null || echo "$LOG_DIR/errors.log")
    # Expand tilde
    ERROR_LOG="${ERROR_LOG/#\~/$HOME}"
    echo "Tailing error log: $ERROR_LOG"
    tail -f "$ERROR_LOG"
    ;;

  run)
    # Run in foreground (for development)
    cd "$(dirname "$0")"
    python3 -m cc_brain.app
    ;;

  uninstall)
    "$0" stop 2>/dev/null
    rm -f "$PLIST_DST"
    echo "Uninstalled. Data in ~/.cc-brain preserved."
    ;;

  *)
    echo "Usage: $0 {install|start|stop|restart|status|logs|run|uninstall}"
    exit 1
    ;;
esac
