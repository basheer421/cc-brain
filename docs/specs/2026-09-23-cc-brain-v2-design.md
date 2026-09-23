# cc-brain v2 — Knowledge Consolidator & MCP Server

**Date:** 2026-09-23
**Status:** Design
**Author:** Bachir + Pi

## Problem

AI coding harnesses (Pi, OpenCode, Claude Code) each have their own memory systems that are:
- **Eager-loaded** — Pi injects 73 skill descriptions + memory policy into every session (~17K tokens wasted)
- **Harness-locked** — Pi's 780KB of accumulated knowledge (MEMORY.md, USER.md, failures.md, 56 skills) is inaccessible to other tools
- **Coupled** — switching or slimming down the harness means losing or rebuilding knowledge

## Solution

Evolve cc-brain from a session summarizer into a **knowledge consolidator** that:
1. Watches sessions across harnesses (Pi, Claude Code, Hermes) — already works
2. Extracts and consolidates durable knowledge into `~/llm-wiki/` — expanded from project-only to skills, failures, identity
3. Exposes an MCP server so any harness can search and suggest writes to the wiki
4. Replaces Pi's built-in memory system (pi-hermes-memory) with a harness-agnostic alternative

## Architecture

```
┌──────────────────────────────────────────────────────────┐
│                   cc-brain daemon                        │
│                   (cc-brain start)                       │
│                                                          │
│  ┌──────────┐   ┌────────────┐   ┌───────────────────┐  │
│  │ Watchers  │──▶│ Extractors │──▶│   Summarizer      │  │
│  │ CC, Pi,   │   │ per-       │   │ session → .md     │  │
│  │ Hermes    │   │ harness    │   └─────────┬─────────┘  │
│  └──────────┘   └────────────┘             │             │
│                                            ▼             │
│                               ┌───────────────────────┐  │
│                               │    Consolidator       │  │
│                               │ summary → llm-wiki    │  │
│                               │  • project facts      │  │
│                               │  • skills extraction  │  │
│                               │  • failures/pitfalls  │  │
│                               │  • identity updates   │  │
│                               └─────────┬─────────────┘  │
│                                         │                │
│                                         ▼                │
│                               ┌───────────────────────┐  │
│                               │   llm-wiki (git)      │  │
│                               │  projects/ skills/    │  │
│                               │  failures/ identity/  │  │
│                               └───────────────────────┘  │
│                                         ▲                │
│  ┌───────────────────────┐              │                │
│  │  Suggestion Queue     │──────────────┘                │
│  │  ~/.cc-brain/queue/   │                               │
│  └───────────┬───────────┘                               │
│              ▲                                           │
└──────────────┼───────────────────────────────────────────┘
               │
┌──────────────┼───────────────────────────────────────────┐
│         cc-brain mcp (stdio, per-connection)             │
│                                                          │
│  wiki_search  wiki_read  wiki_suggest  wiki_index        │
│                                                          │
│  Launched by harness config. Reads wiki directly.        │
│  Writes go through suggestion queue → daemon merges.     │
└──────────────────────────────────────────────────────────┘
```

### Process Model

Two separate processes share the `~/llm-wiki/` directory:

- **`cc-brain start`** — long-running daemon. Watches sessions, runs consolidation pipeline, processes suggestion queue, writes to wiki, git commits. Managed by launchd.
- **`cc-brain mcp`** — short-lived stdio MCP server. Launched per-connection by the harness (Pi, OpenCode, etc). Reads wiki for search/read. Queues suggestions as files for the daemon.

Communication between them: file-based queue at `~/.cc-brain/queue/`. Each suggestion is a JSON file. Daemon watches the queue directory via watchdog. On startup, daemon processes any backlog of queued suggestions (handles the case where daemon was down while MCP server was still receiving suggestions).

## llm-wiki Structure

```
~/llm-wiki/
  AGENTS.md                 ← harness-agnostic soul + lazy-load instructions
  index.md                  ← keyword-tagged table of contents
  changelog.md              ← auto-updated by cc-brain

  identity/
    preferences.md          ← communication style, rules, habits
    environment.md          ← OS, tools, infra layout, stable facts

  projects/                 ← already exists, 11 pages
    ag.md
    brain.md
    shared-services.md
    ...

  skills/                   ← consolidated from 56 Pi skills → ~15-20 files
    k3s-ops.md              ← from k3s-cluster-ops + k3s-add-backend + k3s-log-shipping + k3s-ingress-security
    gitlab.md               ← from gitlab-ops + review-mrs
    deploy-platform.md      ← from g137-deploy-platform-dev + g137-deploy-onboard
    document-tools.md       ← docx + pdf + xlsx
    clickup.md              ← from clickup-task-ops
    monitoring.md           ← from g137-monitoring-ops
    daily-ops.md            ← daily-standup + weekly-review + meeting-action-items
    github.md               ← 7 github-* skills consolidated
    ag-ops.md               ← 5 ag-* skills consolidated
    infra.md                ← g137-onprem-infra + headscale-access + oci-infra-audit
    securechat.md           ← from securechat-ops
    pi-setup.md             ← great-pi-setup + pi-coding-agent-hermes-integration + pi-token-audit
    apple-tools.md          ← apple-notes + apple-reminders
    design-tools.md         ← architecture-diagram + claude-design + sketch
    misc-projects.md        ← sportic-ops + magnitude-site-ops + anwar-tiba-docs

  failures/
    pitfalls.md             ← cross-project pitfalls grouped by domain
    corrections.md          ← things user corrected agents on
    tool-quirks.md          ← non-obvious tool/framework behavior
```

### Skills Format

Plain markdown. No Pi-specific SKILL.md frontmatter. Any agent can `cat` them.

```markdown
# K3s Operations

## When to Use
Deploying to, operating, or debugging the G137 shared k3s cluster.

## Procedures

### Add a backend to k3s
1. Create Helm chart in shared-services/charts/...
2. ...

### Check cluster health
1. ssh k3s-cp-1 ...

## Pitfalls
- Node memory: k3s workers have 8GB, OOMKill threshold at 100Mi eviction
- ...
```

### index.md Keywords

Keywords are specific to avoid false matches from generic terms:

```markdown
### Skills
- [k3s-ops](skills/k3s-ops.md) — k3s-cluster, helm-chart, traefik-ingress, alloy-daemonset, loki-log-shipping
- [deploy-platform](skills/deploy-platform.md) — g137-yaml, kaniko-build, helm-deploy, git-push-deploy, platform-onboard
- [gitlab](skills/gitlab.md) — glab-cli, merge-request, gitlab-pipeline, ci-runner
```

Keywords use compound terms (hyphenated) to be specific enough that general queries like "build" or "deploy" don't match everything.

### AGENTS.md

The single file every harness reads:

```markdown
# Bachir Ammar — AI Agent Instructions

## Identity
Software engineer & sysadmin at G137 (Abu Dhabi). Owns all infra.
English; knows Arabic. Workday ~9-17, off Sunday.

## Communication
Short, direct answers. Tables over prose. Depth only when studying together.
Honest positioning, not agreement. No emojis unless asked.

## Rules
- Plan-first for big/multi-file work; act directly on small tasks
- ASK before irreversible ops (prod, deletes, migrations, push to main)
- Evidence before claims — real tool output, never fabricated
- No unit tests. Integration/e2e only.
- Run `date` before time-sensitive reasoning

## Knowledge System
This agent uses ~/llm-wiki/ as its knowledge base, accessed via the cc-brain MCP server.

1. For ANY task, first call `wiki_search` with specific terms from the task
2. Read relevant pages with `wiki_read` when search returns matches
3. After discovering reusable knowledge, call `wiki_suggest` to persist it
4. Do NOT maintain separate memory files — all knowledge goes through cc-brain

## Project References
- G137 infra truth: ~/code/g137/infra-docs/docs/ (check before infra work)
- All G137 repos: ~/code/g137/ (run git fetch before reading)
- GitLab CLI (glab) available for MRs, pipelines, issues
```

## MCP Server

### Transport
stdio — standard for local MCP servers. Harness launches `cc-brain mcp` as a child process.

### Tools

#### `wiki_search`
Search wiki pages by query.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `query` | string | yes | Search terms |
| `limit` | number | no | Max results (default 5) |
| `scope` | string | no | `all` (default), `skills`, `projects`, `failures`, `identity` |

Returns: array of `{ path, title, snippet, score }`.

Backend v1: SQLite FTS5 over wiki page contents. Index rebuilt on startup and after every wiki write.

Future v2: Embedding-based semantic search using the embedding model on spark-589e. The MCP interface stays identical — only the backend changes.

#### `wiki_read`
Read a specific wiki page.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `path` | string | yes | Relative to wiki root (e.g. `skills/k3s-ops.md`) |

Returns: `{ path, content, last_modified }`.

#### `wiki_suggest`
Queue a knowledge write for the daemon to process.

| Param | Type | Required | Description |
|-------|------|----------|-------------|
| `target` | string | yes | Page path (e.g. `skills/k3s-ops.md`) or `auto` for cc-brain to decide |
| `content` | string | yes | Knowledge to add/update |
| `type` | string | no | `add` (default), `update`, `correction` |

Flow:
1. MCP server writes a JSON file to `~/.cc-brain/queue/<timestamp>-<uuid>.json`
2. Daemon picks it up, LLM-merges content into the target page
3. Writes file, git commits
4. Returns `{ status: "queued", id: "<uuid>" }` immediately (async)

Content is scanned for secrets (API keys, tokens, SSH keys) before queueing — rejects with an error if found.

#### `wiki_index`
Return the full index.md for the agent to browse.

No params. Returns: `{ content: "<index.md contents>" }`.

## Consolidator

### Extraction

After each session summary update (same trigger as current wiki.py), the consolidator makes one LLM call with:

**System prompt:**
```
You are a knowledge extractor. Given a session summary, extract NEW durable
knowledge into structured JSON. Only extract things not already present in
the existing wiki pages provided.

Return JSON:
{
  "extractions": [
    {
      "target": "projects/brain.md",
      "section": "## Commands",
      "action": "append",
      "content": "- `pytest -x --timeout=60` — run brain tests with 60s timeout"
    },
    ...
  ]
}

If nothing new to extract, return: { "extractions": [] }

Categories:
- PROJECT FACTS → projects/<name>.md (commands, config, architecture)
- SKILLS → skills/<topic>.md (reusable procedures, step-by-step)
- FAILURES → failures/pitfalls.md|corrections.md|tool-quirks.md
- IDENTITY → identity/preferences.md|environment.md (only on real changes)
```

**User message includes:**
- The session summary
- Current contents of potentially affected wiki pages (so the LLM can dedup)

### Merge Logic

cc-brain applies extractions mechanically based on `action`:
- `append` — add content to the end of the specified `## section`
- `replace_section` — replace the entire `## section` with new content
- `create_section` — add a new `## section` to the file
- `create_file` — create a new wiki page (also updates index.md)

No LLM call for the merge itself — the extraction prompt produces ready-to-apply content. This is cheaper and more predictable than asking the LLM to rewrite full pages.

### Rate Limiting

| Category | Min interval |
|----------|-------------|
| Project facts | 15 min per project (same as now) |
| Skills | 30 min global |
| Failures | 30 min global |
| Identity | 60 min global |

### Suggestion Queue Processing

The daemon watches `~/.cc-brain/queue/` for new JSON files. For each suggestion:
1. Read the suggestion
2. Load the target wiki page
3. LLM merges the suggestion into the page (same prompt pattern as consolidation, but with the agent's suggested content as input)
4. Write file, git commit with message `suggest: <target> (<type>)`
5. Delete the queue file
6. Rebuild search index

## Migration Command

`cc-brain migrate-pi-memory` — one-time import of Pi's accumulated knowledge into llm-wiki.

### Sources

| Source | Size | Target |
|--------|------|--------|
| `~/.pi/agent/pi-hermes-memory/MEMORY.md` | 115KB | `identity/environment.md` + relevant `projects/*.md` |
| `~/.pi/agent/pi-hermes-memory/USER.md` | 58KB | `identity/preferences.md` |
| `~/.pi/agent/pi-hermes-memory/failures.md` | 608KB | `failures/pitfalls.md` + `failures/corrections.md` + `failures/tool-quirks.md` |
| `~/.pi/agent/pi-hermes-memory/skills/*/SKILL.md` | 56 skills | `skills/*.md` (consolidated) |

### Process

1. Read all source files
2. **Chunk large files** — failures.md split by entry boundaries (~20KB chunks)
3. For each chunk, LLM extracts and categorizes into wiki structure
4. **Skill consolidation** uses a hardcoded mapping:

```python
SKILL_CONSOLIDATION_MAP = {
    "skills/k3s-ops.md": [
        "k3s-cluster-ops", "k3s-add-backend", "k3s-log-shipping", "k3s-ingress-security"
    ],
    "skills/gitlab.md": [
        "gitlab-ops", "review-mrs"
    ],
    "skills/deploy-platform.md": [
        "g137-deploy-platform-dev", "g137-deploy-onboard"
    ],
    "skills/github.md": [
        "github", "github-auth", "github-code-review", "github-issue-to-pr",
        "github-issues", "github-pr-workflow", "github-repo-management"
    ],
    "skills/ag-ops.md": [
        "ag-brain-architecture", "ag-onprem-ops", "ag-platform-dev",
        "ag-task-runner-ops", "ag-task-worker"
    ],
    "skills/document-tools.md": ["docx", "pdf", "xlsx"],
    "skills/monitoring.md": ["g137-monitoring-ops"],
    "skills/clickup.md": ["clickup-task-ops"],
    "skills/daily-ops.md": [
        "daily-standup", "weekly-review-planning", "meeting-action-items"
    ],
    "skills/infra.md": [
        "g137-onprem-infra", "headscale-access", "oci-infra-audit"
    ],
    "skills/securechat.md": ["securechat-ops"],
    "skills/pi-setup.md": [
        "great-pi-setup", "pi-coding-agent-hermes-integration", "pi-token-audit"
    ],
    "skills/apple-tools.md": ["apple-notes", "apple-reminders"],
    "skills/design-tools.md": [
        "architecture-diagram", "claude-design", "sketch"
    ],
    "skills/misc-projects.md": [
        "sportic-ops", "magnitude-site-ops", "anwar-tiba-docs"
    ],
}
```

5. Dedup against existing wiki pages
6. Write files, git commit
7. Rebuild search index

### Safety

- Dry-run mode by default: `cc-brain migrate-pi-memory --dry-run` shows what would be written
- `cc-brain migrate-pi-memory --apply` to actually write
- Does NOT delete Pi's memory files — they stay as backup
- Secret scanning on all content before write

## CLI

```
cc-brain start                          # start daemon (foreground)
cc-brain stop                           # stop daemon via PID file
cc-brain status                         # health: sessions watched, wiki pages, last consolidation
cc-brain mcp                            # start MCP server (stdio, launched by harness)
cc-brain tui                            # terminal dashboard (connects to daemon via unix socket)
cc-brain migrate-pi-memory [--apply]    # one-time Pi memory migration (dry-run by default)
cc-brain search "query"                 # CLI search over wiki (convenience)
```

### Daemon Management

- PID file: `~/.cc-brain/cc-brain.pid`
- Unix socket: `~/.cc-brain/daemon.sock` (for TUI connection)
- Logs: `~/.cc-brain/logs/daemon.log`
- Managed by launchd plist (replaces current rumps app launch)

### TUI (v1 minimal)

Connects to daemon via unix socket. Shows:
- Active watched sessions (harness, project, last activity)
- Recent consolidation events (time, target file, action)
- Suggestion queue depth
- Search index stats (page count, last rebuild)

Implementation: `textual` library for a proper terminal UI. **TUI is optional for v1** — ship daemon + MCP + consolidator + migration first, add TUI later. The daemon writes status to `~/.cc-brain/state/daemon-status.json` which TUI (or `cc-brain status`) reads. No socket protocol needed for v1.

## LLM Configuration

```json
{
  "llm": {
    "default": {
      "api_base_url": "http://litellm.tail.g137.internal:4000/v1",
      "api_key": "sk-...",
      "model": "qwen3.8-27b"
    },
    "summarization": {},
    "consolidation": {},
    "migration": {}
  }
}
```

Each task type inherits from `default` and can override model/endpoint. Empty object = use default. This lets Bachir use g137-litellm qwen for everything now, and point specific tasks at smarter models later.

Fallback chain: task-specific config → default config → OpenRouter (existing fallback).

## Dependencies

### Keep
- `watchdog` — file system watching
- `requests` — LLM API calls
- `sqlite3` — FTS search (stdlib, no install)

### Add
- `textual` — TUI dashboard
- `mcp` — MCP server SDK (Python, for stdio transport)
- `click` — CLI framework

### Remove
- `rumps` — macOS menu bar (replaced by daemon + TUI)
- `Pillow` — was used for menu bar icons

## File Changes

### New files
- `cc_brain/consolidator.py` — extraction pipeline (replaces wiki.py scope)
- `cc_brain/mcp_server.py` — MCP stdio server
- `cc_brain/search.py` — FTS5 search index
- `cc_brain/daemon.py` — launchd daemon entry point
- `cc_brain/tui.py` — terminal dashboard
- `cc_brain/migrate.py` — Pi memory migration
- `cc_brain/cli.py` — click CLI entry point
- `cc_brain/queue.py` — suggestion queue (file-based)

### Modified files
- `cc_brain/config.py` — add LLM config per task type, remove rumps-specific config
- `cc_brain/summarizer.py` — call consolidator after summary update (currently calls wiki.py)

### Removed files
- `cc_brain/app.py` — rumps menu bar app
- `cc_brain/wiki.py` — replaced by consolidator.py
- `generate_icons.py` — no more menu bar icons
- `icons/` — no more menu bar

## Harness Integration

### Pi configuration

MCP server registration (in Pi's MCP config):
```json
{
  "mcpServers": {
    "cc-brain": {
      "command": "cc-brain",
      "args": ["mcp"]
    }
  }
}
```

AGENTS.md changes: replace the Knowledge section with a pointer to `~/llm-wiki/AGENTS.md` and instructions to use cc-brain MCP tools.

### Packages to remove from Pi after migration
- `npm:pi-hermes-memory` (replaced by cc-brain MCP)

### Packages to keep in Pi
- `npm:pi-subagents`
- `npm:pi-lens`
- `npm:pi-caveman`
- `npm:pi-meridian-extension`
- `npm:pi-web-access`
- `npm:pi-background-tasks`
- `npm:billion-context-pi`
- `npm:@juicesharp/rpiv-todo`
- `npm:pi-mcp-adapter` (needed for cc-brain MCP)

### Estimated token savings per Pi session
- Removed: skill index (~5K), memory policy (~2K), hermes-memory tool schemas (~3K)
- Added: cc-brain MCP tool schemas (~1K, only 4 tools)
- **Net savings: ~9K tokens/session off the baseline**

## Edge Cases

### Daemon down while MCP receives suggestions
Suggestions queue as files. Daemon processes backlog on startup.

### Git conflicts in llm-wiki
Daemon runs `git status` before writing. If the working tree is dirty (manual edit in progress), daemon logs a warning and skips that write cycle. Next cycle retries. The daemon never runs `git stash` or `git reset` — manual edits take priority.

### Large wiki pages
If a page exceeds 10KB after a merge, daemon logs a warning. Future: auto-split into sub-pages. For v1, just warn.

### LLM extraction returns garbage
Consolidator validates that returned JSON has the expected schema. Malformed responses are logged and skipped. No wiki write on parse failure.

## Implementation Phases

### Phase 1 (MVP)
- CLI skeleton (click)
- Daemon with existing watcher/extractor/summarizer pipeline
- Consolidator (replaces wiki.py)
- MCP server (search + read + suggest + index)
- FTS5 search index
- Remove rumps/app.py

### Phase 2
- Migration command (migrate-pi-memory)
- Pi harness integration (AGENTS.md rewrite, remove pi-hermes-memory)

### Phase 3
- TUI dashboard
- Suggestion review workflow
- Embedding search backend (spark model)

## Future (not in v1)

- **Embedding search** — swap FTS5 for semantic search using spark-589e embedding model
- **Multi-harness reading** — OpenCode and Claude Code configs pointing at cc-brain MCP
- **Nightly deep consolidation** — cross-session dedup and stale page cleanup
- **Wiki page splitting** — auto-split pages that grow past a threshold
- **Suggestion review UI** — TUI shows pending suggestions before daemon auto-merges
