# CC Brain

Cross-session awareness for [Claude Code](https://docs.anthropic.com/en/docs/claude-code). A macOS menu bar app that watches your sessions and generates living Markdown summaries in real-time.

**Website:** [cc-brain.bachir.me](https://cc-brain.bachir.me)

Every time you exchange messages with Claude Code, CC Brain extracts the new conversation turns and sends them to an LLM (via [OpenRouter](https://openrouter.ai)) to incrementally update a structured summary file.

<p align="center">
  <img src="docs/menu-bar.png" alt="CC Brain in the macOS menu bar" width="400">
</p>

## Install

```bash
curl -sSL cc-brain.bachir.me | bash
```

### Homebrew

```bash
pip3 install rumps watchdog requests Pillow
brew tap basheer421/tap
brew install cc-brain
```

### From source

```bash
git clone https://github.com/basheer421/cc-brain.git
cd cc-brain
./install.sh
```

The installer handles dependencies, prompts for your API key, builds the app, and launches it.

### Requirements

- macOS 12+
- Python 3.10+
- [OpenRouter API key](https://openrouter.ai/keys)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed

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
   ~/.cc-brain/summaries/<project>-<timestamp>.md
```

Each summary is a living document that gets rewritten with every update:

```markdown
# my-project
**Project:** /Users/you/code/my-project
**Started:** 2026-07-11 14:30

## Goal
Refactoring the auth middleware to support OAuth2 PKCE flow.

## Progress
- Analyzed existing session-based auth
- Implemented /auth/callback endpoint
- Added CSRF state parameter validation

## Key Decisions
- PKCE chosen over implicit grant for security
- Using httpOnly cookies instead of localStorage

## Current State
Writing tests for the callback endpoint.

## Files Changed
- src/auth/callback.ts (new)
- src/middleware/auth.ts (modified)
```

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
| `openrouter_api_key` | Your [OpenRouter](https://openrouter.ai/keys) API key. Env var `OPENROUTER_API_KEY` overrides. |
| `model` | Any model on OpenRouter. Default: `deepseek/deepseek-v4-flash`. |
| `extraction_mode` | `smart` (default) skips tool calls and thinking blocks. `full` includes them. |
| `debounce_seconds` | Wait time after last file change before processing. |

Toggle between `smart` and `full` mode from the menu bar dropdown.

## Menu bar

| Icon | State | Meaning |
|------|-------|---------|
| 🧠 | Idle | Watching for changes |
| 🧠• | Syncing | Processing a conversation delta |
| 🧠! | Error | Last API call failed (check error log) |

**Dropdown:**
- **Active Sessions** — click to open a session's summary
- **Open Summaries Folder** — reveals `~/.cc-brain/summaries/` in Finder
- **Open Error Log**
- **Mode: Smart / Full** — toggle extraction mode
- **Quit**

## Claude Code integration

CC Brain writes to `~/.claude/CLAUDE.md` so any Claude Code session can read summaries from other sessions for cross-session awareness.

## Development

```bash
pip3 install -r requirements.txt
python3 -m cc_brain.app          # run directly

./build_app.sh                    # rebuild .app
cp -r "dist/CC Brain.app" /Applications/
```

## Uninstall

```bash
brew uninstall cc-brain
# Or: ./uninstall.sh

# Data preserved at ~/.cc-brain/ — delete manually if desired
```

## Architecture

Single Python process with four subsystems:

- **SessionScanner** — polls `~/.claude/sessions/*.json` every 30s for active sessions
- **TranscriptWatcher** — `watchdog` (FSEvents) detects JSONL changes with debouncing
- **Extractor** — parses new JSONL lines, extracts user/assistant text, tracks byte offsets
- **Summarizer** — calls OpenRouter with previous summary + new delta, writes updated `.md`
- **MenuBarApp** — `rumps` ties it together with a native menu bar icon

## License

MIT
