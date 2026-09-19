# CC Brain

Session memory for AI coding agents. A macOS menu bar app that watches your agent sessions and generates living Markdown summaries in real-time.

Currently supports **Claude Code**, **Hermes**, and **Pi** — with more agents easy to add.

**Website:** [cc-brain.bachir.me](https://cc-brain.bachir.me)

Every time you exchange messages with a supported agent, CC Brain extracts the new conversation turns and sends them to an LLM (any OpenAI-compatible endpoint) to incrementally update a structured summary file.

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
- An LLM API key (any OpenAI-compatible endpoint — [OpenRouter](https://openrouter.ai/keys), [OpenCode Go](https://opencode.ai/docs/go/), [DeepSeek](https://platform.deepseek.com/), or your own vLLM)
- At least one supported agent installed

## Supported agents

| Agent | Source | Detection | Summary prefix |
|-------|--------|-----------|----------------|
| [Claude Code](https://docs.anthropic.com/en/docs/claude-code) | `~/.claude/projects/**/*.jsonl` | FSEvents file watcher | *(none)* |
| [Hermes](https://hermes-agent.nousresearch.com) | `~/.hermes/state.db` (read-only) | `post_llm_call` shell hook → trigger file | `h-` |
| [Pi](https://opencode.ai) | `~/.pi/agent/sessions/**/*.jsonl` | FSEvents file watcher | `p-` |

All sources are event-driven — no polling.

## How it works

```
Claude Code (JSONL)     Hermes (SQLite)      Pi (JSONL)
       │                      │                   │
       ▼                      ▼                   ▼
  File watcher         post_llm_call hook    File watcher
  (watchdog)           → trigger file        (watchdog)
       │                      │                   │
       └──────────────────────┼───────────────────┘
                              ▼
                     Delta extractor (new turns only)
                              │
                              ▼
                     LLM (OpenAI-compatible API)
                              │
                              ▼
              ~/.cc-brain/summaries/
              ├── my-app-17...md          ← Claude Code
              ├── h-my-app-17...md        ← Hermes
              └── p-my-app-17...md        ← Pi
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
  "api_key": "sk-...",
  "api_base_url": "https://opencode.ai/zen/go/v1",
  "model": "deepseek-v4.1-flash",
  "extraction_mode": "smart",
  "debounce_seconds": 3,
  "max_tokens": 4000,
  "extra_headers": {},
  "extra_body": {},
  "summary_dir": "~/.cc-brain/summaries",
  "error_log": "~/.cc-brain/logs/errors.log"
}
```

| Field | Description |
|-------|-------------|
| `api_key` | API key for your endpoint. |
| `api_base_url` | Any OpenAI-compatible endpoint. |
| `model` | Model name at that endpoint. |
| `extraction_mode` | `smart` (default) skips tool calls and thinking blocks. `full` includes them. |
| `debounce_seconds` | Wait time after last file change before processing. |
| `max_tokens` | Completion budget for summaries. Default: `2000`. |
| `extra_headers` | Extra HTTP headers merged into API requests. E.g. `{"x-opencode-session": "cc-brain"}` for OpenCode Go. |
| `extra_body` | Extra JSON merged into the API payload. E.g. `{"chat_template_kwargs": {"enable_thinking": false}}` for Qwen3-style models on vLLM. |

Toggle between `smart` and `full` mode from the menu bar dropdown.

### Endpoint examples

**OpenCode Go** (DeepSeek Flash for $10/mo):
```json
{
  "api_key": "sk-...",
  "api_base_url": "https://opencode.ai/zen/go/v1",
  "model": "deepseek-v4.1-flash",
  "extra_headers": { "x-opencode-session": "cc-brain" }
}
```

**OpenRouter:**
```json
{
  "api_key": "sk-or-...",
  "api_base_url": "https://openrouter.ai/api/v1",
  "model": "deepseek/deepseek-v4-flash"
}
```

**Local vLLM:**
```json
{
  "api_key": "none",
  "api_base_url": "http://your-gpu-box:4000/v1",
  "model": "Qwen3-27B",
  "max_tokens": 4000,
  "extra_body": { "chat_template_kwargs": { "enable_thinking": false } }
}
```

## Hermes integration

CC Brain syncs [Hermes Agent](https://hermes-agent.nousresearch.com) sessions via native shell hooks. Register the hook once:

```bash
hermes config set hooks.post_llm_call \
  '[{"command": "~/.hermes/agent-hooks/ccbrain-notify.sh", "timeout": 10, "hooks_auto_accept": true}]'
```

If Hermes isn't installed, the trigger directory stays empty and CC Brain behaves exactly as before.

## Pi integration

CC Brain watches Pi sessions automatically — no setup needed. It monitors `~/.pi/agent/sessions/` for JSONL changes (top-level sessions only; subagent runs and forks are skipped). If Pi isn't installed, the directory doesn't exist and CC Brain ignores it.

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

Single Python process with seven subsystems:

- **SessionScanner** — polls `~/.claude/sessions/*.json` every 30s for active Claude Code sessions (menu bar list)
- **TranscriptWatcher** — `watchdog` (FSEvents) detects Claude Code JSONL changes, Hermes trigger files, and Pi session JSONL changes, all with debouncing
- **Extractor** — parses new JSONL lines, extracts user/assistant text, tracks byte offsets
- **HermesScanner** — reads new turns for a triggered session from `~/.hermes/state.db` (read-only SQLite), tracks message-id offsets
- **PiScanner** — reads new turns from Pi session JSONLs, handles Pi's `type: "message"` format, tracks byte offsets with `pi:` prefix
- **Summarizer** — calls the configured LLM with previous summary + new delta, writes updated `.md`
- **MenuBarApp** — `rumps` ties it together with a native menu bar icon

## Adding a new agent

CC Brain is designed to be extended. Each agent source needs:

1. A **scanner** module that knows where the agent stores sessions and how to extract user/assistant turns
2. A **watcher** hook — either a file watcher path or a trigger mechanism
3. A **filename prefix** (e.g. `p-` for Pi) to distinguish summaries

See `cc_brain/pi_scanner.py` for a clean example.

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
