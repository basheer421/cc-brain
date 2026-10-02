# cc-brain: long-term memory for coding agents. Design, choices, and measurements

**Author:** Bachir Ammar (with Pi)  ·  **Version:** v3, 2026-10-02  ·  **Repo:** github.com/basheer421/cc-brain

This document explains *why* cc-brain is built the way it is. It is meant for anyone (human or agent)
who needs to change it without re-learning every lesson. The phase plan is in
`docs/specs/2026-10-02-cc-brain-v3-memory-design.md`. Every number below was measured on real data:
the author's own agent sessions from July–October 2026, about 3,800 session summaries.

---

## 1. The problem

Coding agents (Claude Code, Pi, Hermes) start every session with no memory. Without help, the same mistakes come back:

- the same tool quirk gets rediscovered (`glab api` needs `--jq`, not `| jq`),
- a decision the user already made gets argued again,
- the user gets asked a question they answered last week,
- "what did I do yesterday?" can't be answered without digging through transcripts.

cc-brain watches agent sessions, distils them into memory, and serves that memory back to agents over MCP.
The hard part isn't storing things. It's **retrieval cheap enough that agents use it constantly**, and
**writes that don't rot over months**.

## 2. History: three designs

| Version | Date | Shape | Why it was replaced |
|---|---|---|---|
| v1 | 2026-07 | macOS menu-bar app. Watches sessions, keeps one living Markdown summary per session | Summaries are episodic only. No cross-session knowledge, no search |
| v2 | 2026-09-23 | CLI + daemon + MCP. LLM extracts knowledge from summaries and **appends bullets to wiki pages** (`~/llm-wiki/`). FTS5 search over pages | Pages bloated, search returned whole pages, duplicates piled up, truncation corrupted summaries (§3) |
| v3 | 2026-10-02 | **Atomic facts + episodes in SQLite**, hybrid retrieval, write-time memory ops, nightly sleep, wiki becomes a *generated view* | (current) |

## 3. What was wrong with v2 (measured 2026-10-02)

| Symptom | Measurement | Root cause |
|---|---|---|
| Querying was too expensive, so agents skipped it | A search hit pointed at a 66–205 KB page. The 20-question eval read **1,562 KB** in total | The storage unit was the page, so retrieval returned pages too |
| Pages bloated | `brain.md` 66 KB (Pitfalls section alone 47 KB, 143 bullets, avg 327 chars). Wiki total 886 KB | Append-only writes. Nothing ever merged or shortened |
| Duplicates | `correction.md` and `corrections.md`, `tool-quirk.md` and `tool-quirks.md` both existed. The same pitfall appeared reworded several times | Dedup happened inside the extraction LLM call, which had 50 KB of page text as context and did the job poorly |
| No episodic recall | 3,789 summaries on disk, **not indexed** | Summaries were output only, never input |
| Stale facts ranked like fresh ones | "MR !117 merged" scored the same as today's facts | No time dimension |
| Summaries corrupted | On 2026-10-01, **20** summaries were overwritten by output that hit `max_tokens` | "Rewrite completely" prompt with no length caps, and `finish_reason=length` was not checked |
| Write cost | 53–112 summary updates and 19–51 consolidations per day. Each consolidation carried ~50 KB of pages | Dedup context was whole pages |

## 4. Design principles, and where each came from

v3 takes ideas from memory research and human memory. Each one solves a specific v2 failure:

| Principle | Borrowed from | Fixes |
|---|---|---|
| **Atomic facts.** One claim of about 200 chars is the storage unit | Zettelkasten, A-MEM | Retrieval returns answers, not pages |
| **Write-time memory ops:** ADD / UPDATE / SUPERSEDE / NOOP against the nearest existing facts | Mem0 | Duplicates are stopped when written, not cleaned up later |
| **Facts with time.** `created`, `last_seen`, `superseded_by`; a contradiction retires the old fact | Zep / Graphiti (bi-temporal) | Stale facts stop competing with current ones |
| **Episodic and semantic memory kept separate** | Hippocampus / neocortex | "What happened when" (episodes) is separate from "what is true" (facts) |
| **Sleep consolidation.** A nightly pass merges near-duplicates and shortens long facts | Systems consolidation in sleep | Slow drift and bloat get repaired offline |
| **Hybrid retrieval.** BM25 plus dense vectors, fused with RRF | Standard IR | Exact tokens (flags, IDs) *and* paraphrases both hit |
| **Score = relevance × recency × importance** | Generative Agents (Park et al., 2023) | Fresh, important facts win ties |
| **Entity aliases** (Bob = Robert = bob@…) | Knowledge graphs, HippoRAG | Name variants still match |
| **Use strengthens memory.** Each recall hit bumps `hits` and `last_seen` | Hebbian learning / spaced repetition | Facts in active use stay ranked high |
| **Views are generated.** Markdown wiki rendered from the DB | Databases with materialised views | Humans still get readable, git-diffable pages, but the pages can't bloat |

Two deliberate **non-choices**:

- **No vector DB, no graph DB.** At ~2k facts and ~19k episode chunks, SQLite FTS5 plus a numpy matrix
  in memory is fast and has nothing to operate. The DB is 112 MB, mostly embeddings.
- **No auto-injection into prompts.** Agents *query* memory when they need it. Bachir's call:
  injected summaries waste context on every turn and go stale. Querying costs about 750 tokens per question,
  so it can be done constantly.

## 5. Architecture

```
Pi / Hermes sessions ──watchdog──▶ summarizer (bounded; truncated output never saved)
                                                   │
                                                   ├─▶ episodes   (chunks of each summary, by day/project)
                                                   │
                                                   └─▶ memory ops (ADD / UPDATE / SUPERSEDE / NOOP)
                                                              │
                              MCP remember / correct ─────────┤
                                                              ▼
                                ~/.cc-brain/brain.db  (SQLite, WAL)
                                facts · facts_fts · episodes · episodes_fts · docs · aliases
                                                              │
                     MCP recall / timeline / wiki_search ◀────┤
                                                              ▼
                     nightly 03:00: sleep (merge, shorten) ─▶ render ─▶ ~/llm-wiki (generated, git)
```

The LLM work behind the summarizer, memory ops and sleep goes through a **provider chain** (§9).
The embedder runs locally on Ollama (`nomic-embed-text`), so session content stays on the laptop.

### 5.1 Storage

```sql
facts(id, text, kind, project, entities, source, created, updated, last_seen, hits,
      importance,            -- 1 minor · 2 normal · 3 correction / costly pitfall / hard rule
      superseded_by,         -- retired facts are kept as history, never deleted
      original,              -- pre-shortening text (sleep is reversible)
      embedding BLOB)        -- float32, L2-normalised
facts_fts    USING fts5(text, project, entities, tokenize='porter unicode61')
episodes(id, session, project, cwd, day, ts, section, text, embedding)
episodes_fts USING fts5(...)
docs(...)  docs_fts(...)     -- hand-written skill pages, indexed read-only
aliases(alias PRIMARY KEY, canonical)
```

`kind` ∈ `fact, pitfall, decision, preference, correction, procedure, person, note`.
`project` is the repo slug (`my-api`, `web`) or `global`.

**Why `porter unicode61` and not v2's `trigram`?** Trigram matched substrings, so a three-letter acronym hit every page
that merely contained those letters inside a longer word. Porter stemming matches word forms ("connections" ↔ "connection"), and the
dense side covers paraphrases.

## 6. Retrieval

`recall(query, project?, kind?, since?, limit=8)`:

1. **Alias expansion:** query tokens are rewritten through `aliases`.
2. **BM25:** `facts_fts MATCH` (OR of quoted tokens), top 50.
3. **Dense:** cosine between the query embedding and all fact embeddings (a numpy matrix, cached), top 50.
   If Ollama is down this step is skipped and BM25 alone still answers.
4. **Fusion:** Reciprocal Rank Fusion, `Σ 1/(60 + rank)`. RRF needs no score calibration between BM25 and cosine.
5. **Re-rank by multiplying:**
   - recency `0.75 + 0.25·exp(−age_days/60)`. The floor is 0.75, so an old but correct fact is never buried.
   - importance `{1: 0.9, 2: 1.0, 3: 1.15}`
   - project match `1.25`; `global` facts get `1.0`; other projects get `0.9`
6. Return ~8 facts (~2 KB). Bump `hits` and `last_seen`.

The multipliers are deliberately gentle. Relevance dominates, and time and importance only break ties.
The eval (§10) showed that stronger boosts pushed correct answers out of the top 5.

`timeline(project?, since?, until?, query?)` returns episode chunks ordered by time, or ranked by the
query if one is given. It answers "what did I do yesterday" and "where did we leave X".

## 7. Write path

### 7.1 Summarizer (episodic input)

- Hard caps in the prompt: Progress ≤ 10 bullets with the oldest folded into one `Earlier:` bullet,
  whole summary under 600 words. Names, IDs and numbers are preferred over narrative.
- On `finish_reason=length`, **the old summary is kept**. There is one retry with "≤ 6 bullets, ≤ 350 words".
  Partial text is never written. This fixes the 20-overwrites-a-day bug.
- Each saved summary is chunked into `episodes` (Goal, Progress, Decisions, …) and embedded.

### 7.2 Memory ops (semantic input)

For each new or updated summary, rate-limited to one call per project every 15 minutes:

1. Recall the ~30 **most related existing facts**, using the summary's Goal, Decisions and Current State as the query.
   v2 sent 50 KB of whole pages; this context is ~5–7k tokens.
2. One LLM call returns `{"ops": [...]}`, each op being ADD, UPDATE(id), SUPERSEDE(id) or NOOP(id).
3. Deterministic guards, in this order (LLMs ignore "don't duplicate" instructions often enough to need them):
   - an op that references an id the model wasn't shown is downgraded to ADD (or dropped),
   - exact or near-exact text (normalised token Jaccard ≥ 0.85) becomes NOOP plus touch,
   - **paraphrase gate:** a candidate ADD whose embedding is ≥ 0.85 cosine to a live fact in the same
     project (or global) becomes NOOP. The threshold is **measured**: real paraphrases scored ~0.89,
     related-but-distinct facts scored ≤ 0.71,
   - store-level dense dedup: ≥ 0.97 cosine is always NOOP.
4. If the reply is truncated, retry once asking for fewer ops.

`remember` and `correct` over MCP do **no LLM call**. They use only the deterministic dedup, so they are
instant, and sleep handles semantic merging later. `correct(id, text)` supersedes the old fact, which stays as history.
A secret filter rejects anything that looks like a key or token.

### 7.3 Sleep (nightly, 03:00 local, ≤ 60 LLM calls)

- **Merge:** connected components of live facts with cosine ≥ 0.90 in the same project, 2–8 facts per cluster.
  The LLM merges each cluster into the fewest facts. Corrections keep `kind=correction`, and the merged
  fact takes the cluster's highest importance.
- **Shorten:** facts over 320 chars are rewritten to ≤ 200 chars, with the original kept in `facts.original`.
- **Key-term coverage guard.** This is the most important safety rule in sleep. Before any rewrite is
  accepted, cc-brain extracts the *key terms* from the originals: backticked spans, paths, flags, and
  tokens containing digits (IPs, ports, IDs, versions). The rewrite must keep **≥ 90%** of them for a merge
  and **≥ 85%** for a shorten. Otherwise it is discarded. LLM summarisation usually loses exactly the
  part that matters, like the flag or the port number; this guard catches that.
- After sleep, the skill docs are re-indexed and the wiki is re-rendered.

## 8. Generated wiki view

`cc-brain render` writes `projects/<slug>.md`, `failures/<kind>.md` and `identity/*.md` from live facts.
Facts are grouped by kind and sorted by importance, then `last_seen`. Pages are **paginated at 25 KB**,
so a page an agent opens always fits in one read. Each page carries a "generated, don't edit" marker.
`skills/` stays hand-written. Wiki git history keeps every old page. Migration from v2 was lossless:
every bullet became a fact (1,943), and bullet-less section prose became `note` facts.

Result: 49 pages, the largest 24.8 KB, with 1,945 rendered bullets matching the live facts one for one.

## 9. LLM providers (choice made 2026-10-02)

The background work is summaries, memory ops and sleep. It needs a model that is good at
instruction-following and JSON, but it doesn't need frontier reasoning. Options tested on the same real
consolidation prompt:

| Option | Result | Decision |
|---|---|---|
| **agy** (Antigravity CLI), `gemini-3.8-flash-low` on a Google subscription | ✅ 15 s, valid JSON, 5 terse facts. In the consolidation tests: ~10–11 s per call, ~21k-char prompt, ~0.9k-char output | **Primary.** $0 extra, and it doesn't use the Claude quota |
| **Meridian** (local Claude-subscription proxy, `localhost:3456`), `claude-sonnet-5` | ✅ 18 s, valid JSON, 10 facts. Best quality | **Fallback.** It shares the weekly Claude quota with interactive Pi, so it isn't first |
| Meridian, `claude-haiku-4-5` | ⚠️ 67 s, 8.9k output tokens | Rejected |
| Self-hosted Qwen (vLLM/SGLang on a GPU box) | ❌ box repurposed, endpoint down | Not in chain; works as an `openai` entry when up |
| OpenRouter, `deepseek-v4.1-flash` | ❌ 402, out of credit. Historically about **$1.88 per 7 days** (~1M tokens/day) | **Last resort** after a top-up |

How the chain works (`cc_brain/llm.py`):

- Providers are tried in order. A **hard failure** (401/402/403/429, connection refused, missing binary,
  auth or quota errors) puts that provider in a **15-minute cooldown**. A **soft failure** (timeout, 5xx,
  bad output) just moves to the next provider for this call.
- **Truncation stops the chain.** The caller gets `None` with `meta.truncated` and retries with a shorter
  request. Sending the same oversized request on to every provider would only burn quota.
- agy is an agent, not a completion API. It is called with `-p`, `--disable-slash-commands`, an empty temp
  directory as cwd, and **no** `--dangerously-skip-permissions`, so any tool call it tries is soft-denied.
  The prompt goes in argv, capped at 400k chars (the macOS argv limit is ~1 MB); bigger prompts go to the
  next provider. Code fences in the output are stripped.
- Every attempt is appended to `~/.cc-brain/logs/llm.jsonl` (provider, model, status, seconds,
  token/char counts). That log is the cost and quality record for the long-running test.

Gotchas found while wiring it:

| Gotcha | Effect | Fix |
|---|---|---|
| The launchd plist `PATH` doesn't include `~/.local/bin` | agy would hard-fail as "binary not found" on every call and drop silently to Meridian | Set an absolute `"bin"` path in the agy chain entry |
| Meridian ignores `max_tokens` (returns the full answer, `finish_reason=stop`) | Meridian never truncates, which is fine, but it can't be used to test the truncation path | `tests/it_llm_chain.py` uses a local stub endpoint for that path |

## 10. Evaluation

### 10.1 Retrieval: 20 real questions (`tests/eval_recall.py`)

The questions came from real misses in daily work: things an agent should have known but asked about. Three are
pure paraphrases that share no keywords with the answer.

| | v2 (page FTS) | v3 BM25 | v3 hybrid |
|---|---|---|---|
| hit@5 | 20/20 | 20/20 | 20/20 |
| bytes the agent must read | **1,562 KB** | 55 KB | 62 KB |

Same accuracy at about **25× less context**. That ratio is the whole point: v2 was accurate but so
expensive that agents skipped it. Hybrid matters for paraphrases and for when BM25 vocabulary drifts,
and it costs nothing extra when Ollama is up.

### 10.2 Integration tests (real data, no unit tests by design)

| Test | Checks | Status |
|---|---|---|
| `it_summary_truncation.py` | Truncated LLM output never overwrites a summary | PASS |
| `it_mcp.py` | Real stdio MCP on a DB copy: recall, timeline, remember + dedup, correct retires old, secret reject, wiki_search | PASS |
| `it_consolidate.py` | Real summaries → ops, no duplicate ADDs. A rerun on the same summary adds ≤ 25% new ops | PASS (agy: 17 ops; one rerun was all NOOPs) |
| `it_e2e_wiring.py [--live]` | Daemon path: summary → episode + facts → recall top-1 + timeline | PASS (stub and live agy) |
| `it_llm_chain.py` | agy answers first; broken provider → cooldown → Meridian; cooldown skips; truncation stops the chain; attempts are logged | PASS |

## 11. What is not known yet (the long-running test, 2026-10-02 → 10-04)

Everything above was measured over hours. The open questions are about **weeks**:

| Risk | What to watch | Signal it's going wrong |
|---|---|---|
| Fact growth | live facts per day, ADD vs NOOP ratio in `daemon.log` | > ~50 ADDs/day with a steady workload means the gates are leaking |
| Duplicates getting past the gates | sleep `clusters` / `merged_away` counts | merged_away rising night after night |
| Sleep losing information | `facts.original` diffs, coverage-guard rejections | A useful command or ID missing from a merged fact |
| Recency over-decay | eval rerun weekly | hit@5 dropping on old-but-true facts |
| Provider mix and latency | `llm.jsonl`: share of agy vs Meridian, hardfail counts | Mostly Meridian means agy is broken or rate-limited |
| Embedding drift | changing the Ollama model makes all stored vectors incomparable | The model must be pinned. A change requires `embed_missing` after clearing vectors |

## 12. Operating notes

- Install: `install.sh` installs the binary only (uv tool, else pip in a private venv; it never installs uv itself). `cc-brain init` does
  the machine setup and is idempotent; `cc-brain doctor` checks it. Choices: the CLI owns setup so it can be tested against a temp HOME;
  the Pi extension is a symlink into the installed package so upgrades reach Pi; agent instruction files are never edited.
- Daemon: launchd agent `io.ccbrain.daemon` (systemd user unit on Linux), written by `init`. Restart with
  `launchctl kickstart -k gui/$(id -u)/io.ccbrain.daemon`.
- `mcp` is pinned `<2`: the 2.x SDK removed the `Server.list_tools()` decorator API. Found by the clean-HOME install test.
- Data: `~/.cc-brain/brain.db` (facts, episodes), `~/.cc-brain/summaries/`, `~/.cc-brain/logs/{daemon.log,llm.jsonl}`.
- Config: `~/.cc-brain/config.json` → `llm.chain`, `embed`, `consolidation_min_interval_s`.
- Manual passes: `cc-brain sleep [--dry-run]`, `cc-brain render`.
- Tests write the per-project rate-limit key into the live state file (`~/.cc-brain/state/consolidator.json`). A test run can
  delay real consolidation for that project by up to 15 minutes. This is harmless.
