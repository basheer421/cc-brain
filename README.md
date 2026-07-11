# CC Brain

A macOS menu bar app that watches your [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions and generates living Markdown summaries in real-time.

Every time you exchange messages with Claude Code, CC Brain extracts the new conversation turns and sends them to an LLM (via [OpenRouter](https://openrouter.ai)) to incrementally update a structured summary file. You get a clean, readable record of what each session is doing — without lifting a finger.

<p align="center">
  <img src="docs/menu-bar.png" alt="CC Brain in the macOS menu bar" width="400">
</p>

## How it works

```
Claude Code session (JSONL log)
        │
        ▼
   File watcher (watchdog + FSEvents)
        │  debounce 3s
        ▼
   Delta extractor (new turns only)
        │
        ▼
   OpenRouter API (DeepSeek V4 Flash)
        │
        ▼
   ~/.cc-brain/summaries/project-name-timestamp.md
```

Each summary is a **living document** that gets rewritten with every update:

```markdown
# my-project
**Project:** /Users/you/code/my-project
**Started:** 2026-07-11 14:30

## Goal
Refactoring the auth middleware to support OAuth2 PKCE flow.

## Progress
- Analyzed existing session-based auth
- Decided on PKCE over implicit grant
- Implemented /auth/callback endpoint
- Added CSRF state parameter validation

## Key Decisions
- PKCE chosen over implicit grant for security
- Using httpOnly cookies instead of localStorage for tokens

## Current State
Writing tests for the callback endpoint.

## Files Changed
- src/auth/callback.ts (new)
- src/middleware/auth.ts (modified)
```

## Install

**Prerequisites:** macOS 12+, Python 3.10+, [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed.

```bash
git clone https://github.com/user/cc-brain.git
cd cc-brain
./install.sh
```

The installer will:
1. Install Python dependencies (`rumps`, `watchdog`, `requests`, `Pillow`)
2. Prompt for your [OpenRouter API key](https://openrouter.ai/keys)
3. Build and install `CC Brain.app` to `/Applications`
4. Launch the app

**To start on login:** System Settings → General → Login Items → add **CC Brain**.

## Configuration

Config lives at `~/.cc-brain/config.json`:

```json
{
  "openrouter_api_key": "sk-or-v1-...",
  "model": "deepseek/deepseek-v4-flash",
  "extraction_mode": "smart",
  "debounce_seconds": 3,
  "summary_dir": "~/.cc-brain/summaries",
  "error_log": "~/.cc-brain/logs/errors.log"
}
```

| Field | Description |
|-------|-------------|
| `openrouter_api_key` | Your OpenRouter API key. Env var `OPENROUTER_API_KEY` overrides this. |
| `model` | Any model available on OpenRouter. Default: `deepseek/deepseek-v4-flash`. |
| `extraction_mode` | `smart` (default) skips tool calls and thinking blocks. `full` includes them. |
| `debounce_seconds` | Wait time after last file change before processing. |
| `summary_dir` | Where summary `.md` files are saved. |
| `error_log` | Path to the error log file. |

Toggle between `smart` and `full` mode from the menu bar dropdown.

## Menu bar

The brain icon in your menu bar shows the current state:

| Icon | State | Meaning |
|------|-------|---------|
| 🧠 | Idle | Watching for changes, nothing to process |
| 🧠• | Syncing | Processing a conversation delta |
| 🧠! | Error | Last API call failed (check error log) |

**Dropdown menu:**
- **Active Sessions** — lists all running Claude Code sessions; click to open the summary
- **Open Summaries Folder** — reveals `~/.cc-brain/summaries/` in Finder
- **Open Error Log** — opens the error log
- **Mode: Smart / Full** — toggle extraction mode
- **Quit**

## Claude Code integration

CC Brain writes a global `~/.claude/CLAUDE.md` that tells Claude Code sessions where to find summaries. Any Claude Code session can read summaries from other sessions for cross-session context.

## Summary filenames

Files are named `<project-directory>-<start-timestamp-ms>.md`:

```
~/.cc-brain/summaries/
├── my-api-1783701911856.md
├── my-frontend-1783766521000.md
└── infra-1783755000000.md
```

## Development

```bash
# Run directly (without building .app)
pip3 install -r requirements.txt
python3 -m cc_brain.app

# Rebuild the app after code changes
./build_app.sh
cp -r "dist/CC Brain.app" /Applications/

# Manage as a launchd daemon (alternative to Login Items)
./cc-brain.sh install
./cc-brain.sh start|stop|restart|status|logs
```

## Uninstall

```bash
./uninstall.sh
# Data preserved at ~/.cc-brain/ — delete manually if desired
```

## Architecture

Single Python process with four subsystems:

- **SessionScanner** — polls `~/.claude/sessions/*.json` every 30s to discover active Claude Code sessions
- **TranscriptWatcher** — uses `watchdog` (FSEvents on macOS) to detect JSONL file changes with debouncing
- **Extractor** — parses new JSONL lines, extracts user/assistant text, tracks byte offsets
- **Summarizer** — calls OpenRouter API with previous summary + new delta, writes updated `.md`
- **MenuBarApp** — `rumps` app that ties everything together with a native template icon

## License

MIT
