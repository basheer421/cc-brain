# cc-brain: Claude Code Session Meta-Summarizer

## Overview

A lightweight macOS background app that watches all active Claude Code session logs in real-time, extracts conversation turns, and uses OpenRouter (DeepSeek V4 Flash) to maintain a living Markdown summary for each session. Sits in the macOS menu bar with a native template brain icon showing sync/idle/error status.

## Architecture

Single-process Python application with four cooperating subsystems:

```
┌─────────────────────────────────────────────────────┐
│                   MenuBarApp (rumps)                 │
│              Brain template icon + dropdown          │
├─────────────┬──────────────┬────────────────────────┤
│ SessionScanner │ TranscriptWatcher │   Summarizer   │
│  (thread)      │   (watchdog,      │  (OpenRouter   │
│  scans every   │    thread)        │   API client)  │
│  30s for new   │                   │                │
│  sessions      │                   │                │
└─────────────┴──────────────┴────────────────────────┘
        │               │                    │
        ▼               ▼                    ▼
~/.claude/sessions/  ~/.claude/projects/   ~/.cc-brain/
   *.json              **/*.jsonl          summaries/*.md
```

### 1. SessionScanner

- Runs on a background thread, polls every 30 seconds
- Reads `~/.claude/sessions/*.json` to discover active sessions (those with a running PID)
- Each session JSON contains `sessionId`, `cwd`, `status`, `pid`
- Maps each sessionId to its JSONL transcript path: `~/.claude/projects/<encoded-cwd>/<sessionId>.jsonl`
- The encoded CWD replaces `/` with `-` and strips the leading `-` (e.g., `/Users/bammar/code/private/hacka` → `-Users-bammar-code-private-hacka`)
- Maintains a registry of watched sessions; adds/removes as sessions start/end
- Notifies the TranscriptWatcher when new sessions are discovered

### 2. TranscriptWatcher

- Uses `watchdog` with `Observer` watching `~/.claude/projects/` recursively for `*.jsonl` `FileModifiedEvent`s
- macOS uses FSEvents backend natively — efficient, no polling
- On file change:
  1. Check if the modified file matches a known active session
  2. Debounce: wait 3 seconds (configurable) after last modification before processing. Reset timer on each new event for the same file
  3. After debounce: hand off to the Extractor

### 3. Extractor

- Tracks byte offset per session in `~/.cc-brain/state/offsets.json`
- On trigger: seek to last known offset, read new lines
- Parse each JSON line, filter by `type` field

**Smart mode (default):**
- Include: `type == "user"` → extract `message.content` (string or `text`-type blocks)
- Include: `type == "assistant"` → extract only `text`-type content blocks (visible reply text)
- Skip: `thinking` blocks, `tool_use` blocks, `tool_result` blocks
- Skip metadata types: `last-prompt`, `mode`, `permission-mode`, `ai-title`, `hook_success`, `file-history-snapshot`, `command_permissions`, `auto_mode`, `skill_listing`, `deferred_tools_delta`, `agent_listing_delta`, `mcp_instructions_delta`, `plan_mode_exit`, `task_reminder`

**Full mode (configurable):**
- Everything from smart mode, plus:
- `tool_use`: extract tool name and a truncated input summary (first 200 chars)
- `tool_result`: extract content text (first 500 chars)
- Still skip: `thinking` blocks and all metadata types

**Output format sent to LLM:**
```
[HH:MM] User: <message text>
[HH:MM] Assistant: <response text>
```

- Timestamps derived from the `timestamp` field (epoch milliseconds → local time `HH:MM`)
- Only advance the byte offset after successful summarization (so failed attempts re-read the delta)

### 4. Summarizer

**API Configuration:**
- Endpoint: `https://openrouter.ai/api/v1/chat/completions`
- Model: `deepseek/deepseek-v4-flash` (configurable)
- Auth: `Authorization: Bearer <OPENROUTER_API_KEY>`
- API key from config file or `OPENROUTER_API_KEY` env var (env var takes precedence)

**Prompt structure:**
```
System prompt:
You are a session summarizer for a developer's Claude Code sessions.
Given the previous summary (if any) and new conversation turns, produce
an updated Markdown summary. The summary is a living document — rewrite
it completely each time to reflect the full session state.

Use this exact structure:

# <project-name>
**Project:** <project path>
**Session:** <session-id>
**Started:** <start timestamp>
**Last updated:** <current timestamp>

## Goal
What the user is trying to accomplish (1-2 sentences, refined as it becomes clearer)

## Progress
- Completed steps as bullet points (most recent last)

## Key Decisions
- Important choices made and their rationale

## Current State
What's happening right now / what's next (1-2 sentences)

## Files Changed
- List of files created or modified (if mentioned in conversation)

User message:
Previous summary:
<contents of existing .md file, or "None — new session">

New conversation turns:
<extracted delta text>
```

**Incremental strategy:** Each call sends previous summary (~500-1000 tokens) + new delta (~100-500 tokens). Never sends the full conversation history. Cost per update: ~$0.001 or less.

**Concurrency:** Max one API call at a time. Subsequent triggers queue. If multiple sessions trigger simultaneously, process sequentially (FIFO).

**Error handling:**
- On API failure: retry once after 5 seconds
- On second failure: log to error log, set menu bar status to error (🔴), do NOT advance byte offset (delta will be retried on next trigger)
- On success: advance byte offset, set status back to idle

## Menu Bar App

**Icon:** Native macOS template image — brain outline, white on transparent, rendered at 18×18pt (36×36px @2x). Marked as `template=True` in rumps so macOS handles light/dark/active states automatically.

**Icon states:**
- **Idle** (⚪): Standard brain icon — watching, no activity
- **Syncing** (🟢): Brain icon with small activity dot — currently processing a delta or calling API
- **Error** (🔴): Brain icon with exclamation badge — last API call failed

All three states are separate template PNG files bundled with the app.

**Dropdown menu:**
```
Active Sessions ▸
  ├── hacka — ~/code/private/hacka        → click opens summary .md
  ├── cc-brain — ~/code/private/cc-brain  → click opens summary .md
  └── (no active sessions)
─────────────────
Open Summaries Folder                     → reveals ~/.cc-brain/summaries/ in Finder
Open Error Log                            → opens error log file in Console.app or default editor
─────────────────
Mode: Smart  /  Mode: Full                → toggle extraction mode (checkmark on active)
─────────────────
Quit cc-brain
```

## Configuration

**File:** `~/.cc-brain/config.json`

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

All fields have sensible defaults except `openrouter_api_key` which is required. Env var `OPENROUTER_API_KEY` overrides the config file value.

## Daemon Management

**launchd plist:** `~/Library/LaunchAgents/io.ccbrain.agent.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>io.ccbrain.agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/python3</string>
    <string>/path/to/cc-brain/cc_brain/app.py</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>/Users/bammar/.cc-brain/logs/stdout.log</string>
  <key>StandardErrorPath</key>
  <string>/Users/bammar/.cc-brain/logs/stderr.log</string>
</dict>
</plist>
```

**Management script:** `cc-brain.sh`

```
cc-brain.sh start   → launchctl load the plist
cc-brain.sh stop    → launchctl unload the plist
cc-brain.sh restart → stop + start
cc-brain.sh status  → check if process is running via launchctl list
cc-brain.sh logs    → tail -f ~/.cc-brain/logs/errors.log
```

## Directory Layout

**Runtime data:**
```
~/.cc-brain/
├── config.json
├── summaries/
│   ├── <session-id>.md        # one per session
│   └── ...
├── state/
│   └── offsets.json           # byte offsets per session JSONL
└── logs/
    ├── errors.log             # application error log
    ├── stdout.log             # launchd stdout
    └── stderr.log             # launchd stderr
```

**Project source:**
```
cc-brain/
├── cc_brain/
│   ├── __init__.py
│   ├── app.py                 # rumps MenuBarApp, main entry point
│   ├── watcher.py             # watchdog FileSystemEventHandler + debouncing
│   ├── scanner.py             # session discovery from ~/.claude/sessions/
│   ├── extractor.py           # JSONL parsing + content filtering
│   ├── summarizer.py          # OpenRouter API client
│   └── config.py              # config loading + defaults
├── icons/
│   ├── brain-idle.png         # 18x18 template icon
│   ├── brain-idle@2x.png      # 36x36 template icon
│   ├── brain-sync.png
│   ├── brain-sync@2x.png
│   ├── brain-error.png
│   └── brain-error@2x.png
├── cc-brain.sh                # start/stop/status script
├── io.ccbrain.agent.plist     # launchd plist template
├── install.sh                 # creates ~/.cc-brain dirs, installs plist, pip installs deps
├── requirements.txt
└── pyproject.toml
```

## Dependencies

```
rumps>=0.4.0
watchdog>=4.0.0
requests>=2.31.0
```

Python 3.10+ (system Python or brew-installed).

## Error Handling Summary

| Scenario | Behavior |
|----------|----------|
| OpenRouter API 4xx/5xx | Retry once after 5s, then log + set 🔴 status |
| Invalid/missing API key | Log error on startup, set 🔴, show "No API Key" in menu |
| JSONL parse error (corrupt line) | Skip line, log warning, continue |
| Session JSONL deleted mid-watch | Remove from registry, no crash |
| watchdog observer crash | KeepAlive in launchd restarts process |
| Config file missing | Create with defaults (minus API key), prompt via menu |
| Disk full / write failure on summary | Log error, set 🔴, retry on next trigger |

## Out of Scope

- Web UI or dashboard
- Historical session browsing (only active sessions)
- Multi-user support
- Encryption of summaries
- Custom summary templates (hardcoded prompt)
