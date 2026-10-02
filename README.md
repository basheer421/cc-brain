# CC Brain

Long-term memory for AI coding agents. A background daemon watches your agent sessions, distils them into
**atomic facts** and **time-indexed episodes**, and serves them back to any agent over **MCP**. Answers come
back as ~2 KB of ranked facts, so agents can afford to check memory before every task.

Learns from **Pi** and **Hermes** sessions. Serves memory to any MCP client (Pi, Claude Code, Hermes, ...).

**Website:** [cc-brain.bachir.me](https://cc-brain.bachir.me)  ·  **Design paper:** [`docs/cc-brain-design.md`](docs/cc-brain-design.md)

## Why

Agents forget everything between sessions, so the same tool quirk gets rediscovered and the same
question gets asked twice. Earlier versions of cc-brain stored memory as Markdown pages. Search worked,
but every hit meant reading a 60–200 KB page, so agents stopped searching. v3 stores one claim per row and
returns only the claims that matter:

| | v2 (pages) | v3 (facts) |
|---|---|---|
| Correct answer in top 5 (20 real questions) | 20/20 | 20/20 |
| Context the agent reads for those 20 questions | 1,562 KB | ~60 KB |
| "What did I do yesterday?" | not possible | `timeline(since="yesterday")` |
| Duplicates | appended forever | blocked at write time, merged nightly |
| Wrong facts | stay | `correct(id)` retires them, history kept |

## How it works

```
agent sessions ──watchdog──▶ summarizer (bounded; truncated output is never saved)
                                │
                                ├─▶ episodes    chunks of each session summary, by day and project
                                └─▶ memory ops  LLM decides ADD / UPDATE / SUPERSEDE / NOOP against related facts
                                                  │
                                       ~/.cc-brain/brain.db  (SQLite + FTS5 + local embeddings)
                                                  │
              MCP: recall · timeline · remember · correct · forget · wiki_search
                                                  │
              nightly: sleep (merge near-duplicates, shorten long facts) ─▶ render Markdown wiki view
```

- **Retrieval:** BM25 (FTS5, porter) plus dense vectors (Ollama `nomic-embed-text`, local), fused with
  RRF, then re-ranked by recency, importance and project. Entity aliases expand names.
- **Writes:** deterministic guards run around the LLM: exact/Jaccard dedup, an embedding paraphrase gate,
  and a key-term coverage check so merges never drop a command, path, flag or number.
- **Wiki:** `~/llm-wiki/` is *generated* from the DB (≤ 25 KB per page, git-committed). Read it, don't edit it.

See [`docs/cc-brain-design.md`](docs/cc-brain-design.md) for every design choice and the measurements behind it.

## MCP tools

| Tool | Use |
|---|---|
| `recall(query, project?, kind?, limit=8)` | Ranked facts: pitfalls, decisions, preferences, corrections, people, procedures |
| `timeline(project?, since?, until?, query?)` | What happened when. `since`/`until` take `today`, `yesterday`, `7d` or `YYYY-MM-DD` |
| `remember(text, kind?, project?, importance?)` | Store one durable fact (≤ 200 chars, rule + why). Near-duplicates merge |
| `correct(id, text)` / `forget(id)` | Retire a wrong or outdated fact. The old version is kept as history |
| `wiki_search`, `wiki_read`, `wiki_list`, `wiki_suggest` | Compatibility with v2 clients |

`cc-brain init` registers the MCP server with Pi and Claude Code for you. For other clients:

```json
{ "mcpServers": { "cc-brain": { "command": "cc-brain", "args": ["mcp"] } } }
```

## Install

```bash
curl -sSL cc-brain.bachir.me | bash
```

Requirements: macOS or Linux, and **[uv](https://docs.astral.sh/uv/)** (recommended) or Python 3.10+.
The installer never installs uv, Python or anything system-wide, and never uses `sudo`:

| You have | It does |
|---|---|
| uv | `uv tool install cc-brain` (isolated env; upgrade with `uv tool upgrade cc-brain`) |
| Python 3.10+ only | creates a private venv in `~/.local/share/cc-brain/venv`, installs with pip there, links `~/.local/bin/cc-brain` |
| neither | stops and tells you to install uv |

Then it runs `cc-brain init`, which sets up the machine. `init` is safe to re-run, and asks before each change
(`--yes` accepts the defaults):

1. `~/.cc-brain/config.json` with the LLM providers it finds (agy, a local Meridian proxy, an OpenRouter key)
2. local embeddings: pulls `nomic-embed-text` if Ollama is running (optional; without it recall is keyword-only)
3. MCP registration for Pi (`~/.pi/agent/mcp.json`) and Claude Code (`~/.claude.json`), with a backup of each file
4. the **Pi auto-recall extension**, symlinked into `~/.pi/agent/extensions/`, so it updates with cc-brain
5. a background service: launchd agent `io.ccbrain.daemon` on macOS, systemd user unit on Linux
6. `cc-brain doctor`, which checks all of the above

It never edits your `AGENTS.md` / `CLAUDE.md`. Instead it prints a 4-line snippet telling your agent when to call `recall`.

```bash
cc-brain doctor                       # check providers, embeddings, daemon, MCP, extension
cc-brain uninstall [--purge]          # remove service, MCP entries, extension (--purge also deletes memory)
```

From a checkout (development): `CC_BRAIN_SOURCE=. ./install.sh` installs in editable mode.

Coming from v2: `cc-brain migrate-v3 --apply` imports the old wiki into facts, and
`cc-brain index-episodes --embed` indexes existing session summaries.

### Pi auto-recall

Before each prompt, the extension runs `cc-brain recall` on your message (boosted for the current repo) and adds
the matching facts above the model's turn: up to 5 on the first prompt, then up to 3 new ones. It skips
chit-chat and slash commands, makes no LLM call, and does nothing if cc-brain is down. Turn it off with
`CC_BRAIN_AUTO_RECALL=0`. Decisions are logged to `~/.cc-brain/logs/auto-recall.jsonl`.

## LLM providers

Background work (summaries, memory ops, sleep) goes through an ordered **provider chain**. The first
provider that answers wins. A hard failure (no credit, auth, rate limit, connection refused) puts that
provider in a 15-minute cooldown. Truncated output is never used.

```json
{
  "llm": {
    "chain": [
      { "name": "agy",        "type": "agy",    "model": "gemini-3.8-flash-low", "bin": "/abs/path/to/agy" },
      { "name": "meridian",   "type": "openai", "api_base_url": "http://localhost:3456/v1", "model": "claude-sonnet-5", "json_mode": false },
      { "name": "openrouter", "type": "openai", "api_base_url": "https://openrouter.ai/api/v1", "model": "deepseek/deepseek-v4.1-flash" }
    ],
    "consolidation": { "max_tokens": 12000 }
  }
}
```

| `type` | Talks to | Notes |
|---|---|---|
| `openai` | Any OpenAI-compatible `/chat/completions` (OpenRouter, vLLM, a local proxy) | `api_key` falls back to the top-level key when the base URL matches. Supports `extra_headers` and `extra_body` |
| `agy` | Google Antigravity CLI (`agy -p`) | Runs in an empty temp dir with tool permissions denied. Use an **absolute `bin` path** under launchd |

Without a `chain`, the legacy single endpoint (`api_base_url`, `api_key`, `model`) is used. Every attempt is
logged to `~/.cc-brain/logs/llm.jsonl` (provider, status, seconds, token/char counts).

## CLI

```
cc-brain init [-y] | doctor | uninstall   machine setup / health check / removal
cc-brain start [-b] | stop | status       daemon (normally run by the service)
cc-brain recall "query" [--project P]     facts
cc-brain timeline --since yesterday       episodes
cc-brain remember "text" --kind pitfall   write a fact
cc-brain sleep [--dry-run]                run the consolidation pass now
cc-brain render                           regenerate the wiki view
cc-brain brain-stats                      counts
cc-brain mcp                              MCP stdio server
```

## Data

| Path | What |
|---|---|
| `~/.cc-brain/brain.db` | Facts, episodes, docs, aliases (SQLite WAL) |
| `~/.cc-brain/summaries/` | Living session summaries (`p-` Pi, `h-` Hermes) |
| `~/.cc-brain/config.json` | Configuration |
| `~/.cc-brain/logs/` | `daemon.log`, `llm.jsonl` |
| `~/llm-wiki/` | Generated Markdown view (git) |

## Tests

There are no unit tests by design. The integration tests run on a **copy** of your live `brain.db`
(`uv run` builds a project `.venv` with the dependencies on first use):

```bash
uv run python tests/it_summary_truncation.py   # truncated output never overwrites a summary
uv run python tests/it_mcp.py                  # real stdio MCP round-trip
uv run python tests/it_consolidate.py          # real summaries -> ops, no duplicate ADDs
uv run python tests/it_e2e_wiring.py [--live]  # summary -> episode + facts -> recall
uv run python tests/it_llm_chain.py            # provider order, cooldown, truncation (needs providers up)
uv run python tests/eval_recall.py             # hit@5 and bytes read: v2 vs BM25 vs hybrid
```

## License

MIT
