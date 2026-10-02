# CC Brain

Long-term memory for AI coding agents. A background daemon watches your agent sessions, distils them into
**atomic facts** and **time-indexed episodes**, and serves them back to any agent over **MCP**. Answers come
back as ~2 KB of ranked facts, so agents can afford to check memory before every task.

Supports **Pi**, **Claude Code** and **Hermes** session sources.

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

Register the MCP server with your agent:

```json
{ "mcpServers": { "cc-brain": { "command": "cc-brain", "args": ["mcp"] } } }
```

## Install

```bash
git clone https://github.com/basheer421/cc-brain.git && cd cc-brain
pip install -e .
ollama pull nomic-embed-text          # local embeddings (optional: BM25-only without it)
cc-brain start -b                     # or install the launchd agent (see io.ccbrain.agent.plist)
cc-brain migrate-v3 --apply           # one-time: import an existing v2 wiki into facts
cc-brain index-episodes --embed       # one-time: index existing session summaries
```

Requirements: Python 3.10+, macOS or Linux, and at least one LLM provider (below).

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
cc-brain start [-b] | stop | status       daemon
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

There are no unit tests by design. The integration tests run on a **copy** of your live `brain.db`:

```bash
python tests/it_summary_truncation.py   # truncated output never overwrites a summary
python tests/it_mcp.py                  # real stdio MCP round-trip
python tests/it_consolidate.py          # real summaries -> ops, no duplicate ADDs
python tests/it_e2e_wiring.py [--live]  # summary -> episode + facts -> recall
python tests/it_llm_chain.py            # provider order, cooldown, truncation (needs providers up)
python tests/eval_recall.py             # hit@5 and bytes read: v2 vs BM25 vs hybrid
```

## License

MIT
