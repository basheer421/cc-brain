# CC Brain

Cross-session awareness for [Claude Code](https://docs.anthropic.com/en/docs/claude-code) — and now [Hermes Agent](https://hermes-agent.nousresearch.com). A macOS menu bar app that watches your agent sessions and generates living Markdown summaries in real-time.

**Website:** [cc-brain.bachir.me](https://cc-brain.bachir.me)

Every time you exchange messages with Claude Code or Hermes, CC Brain extracts the new conversation turns and sends them to an LLM (any OpenAI-compatible endpoint — OpenRouter, or your own local vLLM) to incrementally update a structured summary file.

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
- An LLM API key ([OpenRouter](https://openrouter.ai/keys), or any OpenAI-compatible endpoint)
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and/or [Hermes Agent](https://hermes-agent.nousresearch.com) installed

## How it works

Two sources, one brain. Both are event-driven — no polling.

```
Claude Code session (JSONL log)          Hermes session (SQLite state.db)
        │                                        │
        ▼                                        ▼
   File watcher (watchdog + FSEvents)      post_llm_call shell hook
        │  debounce 3s                          │  touches ~/.cc-brain/triggers/hermes-<id>
        │                                        ▼
        │                                  File watcher (same observer)
        ▼                                        ▼
   Delta extractor (new turns only)   ◄──────────┘
        │
        ▼
   LLM (OpenAI-compatible API)
        │
        ▼
   ~/.cc-brain/summaries/<project>-<timestamp>.md      ← Claude Code
   ~/.cc-brain/summaries/h-<project>-<timestamp>.md    ← Hermes (h- prefix)
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

## Hermes integration

CC Brain also syncs [Hermes Agent](https://hermes-agent.nousresearch.com) sessions — desktop app, CLI, and gateway alike. Hermes summaries get an `h-` filename prefix so both agents' sessions live side by side in one folder.

The integration is event-driven via Hermes's native [shell hooks](https://hermes-agent.nousresearch.com/docs/user-guide/features/hooks):

1. A `post_llm_call` shell hook (`~/.hermes/agent-hooks/ccbrain-notify.sh`) fires after every agent turn and touches `~/.cc-brain/triggers/hermes-<session_id>`.
2. CC Brain's existing watchdog observer picks up the trigger and reads only that session's new messages from `~/.hermes/state.db` (read-only — never writes to Hermes's database).

Register the hook once:

```bash
hermes config set hooks.post_llm_call \
  '[{"command": "~/.hermes/agent-hooks/ccbrain-notify.sh", "timeout": 10, "hooks_auto_accept": true}]'
```

If Hermes isn't installed, the trigger directory stays empty and CC Brain behaves exactly as before.

## Configuration

Config lives at `~/.cc-brain/config.json`:

```json
{
  "api_key": "sk-...",
  "api_base_url": "https://openrouter.ai/api/v1",
  "model": "deepseek/deepseek-v4-flash",
  "extraction_mode": "smart",
  "debounce_seconds": 3,
  "max_tokens": 2000,
  "extra_body": {},
  "summary_dir": "~/.cc-brain/summaries",
  "error_log": "~/.cc-brain/logs/errors.log"
}
```

| Field | Description |
|-------|-------------|
| `api_key` | API key for your endpoint. `openrouter_api_key` still works as a fallback; env var `OPENROUTER_API_KEY` overrides. |
| `api_base_url` | Any OpenAI-compatible endpoint. Default: `https://openrouter.ai/api/v1`. Point it at your own vLLM/llama.cpp server to summarize for free. |
| `model` | Model name at that endpoint. Default: `deepseek/deepseek-v4-flash`. |
| `extraction_mode` | `smart` (default) skips tool calls and thinking blocks. `full` includes them. |
| `debounce_seconds` | Wait time after last file change before processing. |
| `max_tokens` | Completion budget for summaries. Default: `2000`. |
| `extra_body` | Extra JSON merged into the API payload. E.g. `{"chat_template_kwargs": {"enable_thinking": false}}` to disable thinking mode on Qwen3-style models served by vLLM. |

Toggle between `smart` and `full` mode from the menu bar dropdown.

### Local model example (vLLM)

```json
{
  "api_key": "your-key",
  "api_base_url": "http://your-gpu-box:4000/v1",
  "model": "Qwen3-27B",
  "max_tokens": 4000,
  "extra_body": { "chat_template_kwargs": { "enable_thinking": false } }
}
```

Thinking models emit `reasoning_content` with a null `content` unless thinking is disabled — hence the `extra_body` knob.

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

Single Python process with six subsystems:

- **SessionScanner** — polls `~/.claude/sessions/*.json` every 30s for active sessions (menu bar list)
- **TranscriptWatcher** — `watchdog` (FSEvents) detects Claude Code JSONL changes *and* Hermes trigger files with debouncing
- **Extractor** — parses new JSONL lines, extracts user/assistant text, tracks byte offsets
- **HermesScanner** — reads new turns for a triggered session from `~/.hermes/state.db` (read-only SQLite), tracks message-id offsets
- **Summarizer** — calls the configured LLM with previous summary + new delta, writes updated `.md`
- **MenuBarApp** — `rumps` ties it together with a native menu bar icon

## Contributing

```bash
git clone https://github.com/basheer421/cc-brain.git
cd cc-brain
pip3 install -r requirements.txt
python3 -m cc_brain.app
```

PRs welcome. If you're fixing a bug, include steps to reproduce. If you're adding a feature, open an issue first so we can discuss.

The website lives in `website/` — run `cd website && bun install && bun run dev` to work on it locally.

## License

MIT
