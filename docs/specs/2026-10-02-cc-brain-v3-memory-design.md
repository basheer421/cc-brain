# cc-brain v3 — Memory, not pages

**Date:** 2026-10-02
**Status:** Implementing (branch `brain-v3`)
**Author:** Bachir + Pi

## Problem (measured 2026-10-02)

| Layer | v2 today | Effect |
|---|---|---|
| Storage unit | Markdown pages, append-only. Largest project pages 66–70 KB (one Pitfalls section alone 47 KB, 143 bullets, avg 327 chars), plus a 68 KB one-shot memory dump. 886 KB of wiki in total | A search hit points at a 66 KB page, so the agent has to read the whole page. Querying is expensive, so agents skip it |
| Search | FTS5 `trigram`, query tokens OR'd, one row per **page**, snippet of 40 tokens | Noisy substring matches (e.g. short acronyms), long pages win on BM25, no semantics, no aliases (name variants) |
| Episodic memory | 3,789 session summaries in `~/.cc-brain/summaries/` | **Not indexed.** "What did I do yesterday" can't be queried |
| Time | None | Stale facts ("MR !117 merged") rank the same as today's |
| Write path | LLM extracts → appends bullets to a section. Gets 50 KB of whole wiki pages as dedup context on every call | Near-duplicates pile up; expensive calls; `correction.md`/`corrections.md` and `tool-quirk.md`/`tool-quirks.md` both exist |
| Summaries | "Rewrite completely each time", uncapped lists, `max_tokens` 4000 | Long sessions overflow; the **truncated output overwrites** the previous good summary (20 times on 2026-10-01) |

## Principles (stolen ideas)

| Idea | Source | cc-brain v3 |
|---|---|---|
| Atomic notes | Zettelkasten, A-MEM | A **fact** is the storage unit: one claim, ideally ≤ 200 chars, with metadata |
| Write-time memory ops | Mem0 | New candidate facts are compared to their nearest existing facts → `ADD` / `UPDATE` / `SUPERSEDE` / `NOOP`. Dedup happens on write, not by later compaction |
| Bi-temporal facts | Zep / Graphiti | Facts carry `created`, `last_seen`, `superseded_by`. Contradictions retire the old fact instead of coexisting |
| Episodic vs semantic | Hippocampus / neocortex | **Episodes** = session summaries, chunked and time-indexed. **Facts** = durable semantic memory |
| Sleep consolidation | Systems consolidation | A daily `sleep` pass merges near-duplicate facts (vector similarity + LLM decision), shortens long facts (original kept) |
| Hybrid retrieval | Standard IR (BM25 + dense, RRF fusion) | FTS5 BM25 (porter/unicode61) ∪ embedding cosine → Reciprocal Rank Fusion |
| Relevance × recency × importance | Generative Agents (Park et al. 2023) | Final score = RRF × recency decay × importance × project match |
| Entity aliases | Knowledge graphs, HippoRAG | `aliases` table expands query terms (Bob = Robert = bob@…) |
| Use strengthens memory | Hebbian / spaced repetition | Every recall hit bumps `hits` and `last_seen` |
| Views are generated | DB + materialised views | Markdown wiki pages are **rendered** from the DB: human-readable, git-diffable, size-bounded |

## Architecture

```
Pi / Hermes sessions ──watchdog──▶ summarizer (bounded, never writes truncated)
                                        │
                                        ├─▶ episodes  (chunks of each summary, by day/project)
                                        │
                                        └─▶ extractor ──candidates──▶ memory ops (ADD/UPDATE/SUPERSEDE/NOOP)
                                                                           │
                                     MCP: remember / correct ──────────────┤
                                                                           ▼
                                   ~/.cc-brain/brain.db  (SQLite, WAL)
                                   facts · facts_fts · episodes · episodes_fts · aliases · docs
                                                                           │
                         MCP: recall / timeline / wiki_search ◀────────────┤
                                                                           ▼
                                   render ─▶ ~/llm-wiki/{projects,failures,identity}/*.md (generated view, git)
                                   sleep  ─▶ daily merge/shorten pass
```

### Schema (`~/.cc-brain/brain.db`)

```sql
facts(id INTEGER PRIMARY KEY, text, kind, project, entities, source,
      created REAL, updated REAL, last_seen REAL, hits INTEGER DEFAULT 0,
      importance INTEGER DEFAULT 2,        -- 1 low, 2 normal, 3 high (corrections, pitfalls with cost)
      superseded_by INTEGER, original TEXT, -- original text kept when shortened by sleep
      embedding BLOB)                       -- float32, nullable
facts_fts USING fts5(text, project, entities, content='facts', tokenize='porter unicode61')
episodes(id INTEGER PRIMARY KEY, session, project, cwd, day TEXT, ts REAL, section, text, embedding BLOB)
episodes_fts USING fts5(text, project, section, content='episodes', tokenize='porter unicode61')
docs(id INTEGER PRIMARY KEY, path, section, text, embedding BLOB)   -- hand-written pages (wiki skills/)
docs_fts USING fts5(...)
aliases(alias TEXT PRIMARY KEY, canonical TEXT)
```

`kind` ∈ `fact | pitfall | decision | preference | correction | procedure | person | note`.
`project` = repo slug (`my-api`, `web`) or `global`.

### Retrieval: `recall(query, project?, kind?, since?, limit=8)`

1. Expand query tokens through `aliases`.
2. BM25: `facts_fts MATCH` (OR of quoted tokens), top 50.
3. Dense: cosine(query embedding, fact embeddings), top 50 (skipped if the embedder is down; BM25 alone still works).
4. RRF: `Σ 1/(60 + rank)`.
5. Multiply: recency `0.75 + 0.25·exp(-age_days/60)`, importance `{1:0.9, 2:1.0, 3:1.15}`, project match `1.25`. Superseded facts excluded.
6. Return about 8 × 200 chars ≈ 2 KB, not a 66 KB page. Bump `hits` and `last_seen`.

`timeline(project?, since?, until?, query?)`: episodes ordered by time (or ranked if `query` is given); returns Goal + Progress chunks per session.

`wiki_search` stays for compatibility. It returns recall facts + doc chunks + episodes in one list.

### Write path

- **Summarizer:** hard caps in the prompt (Progress ≤ 10 bullets, older work folded into one `Earlier:` line; Decisions ≤ 6; Files ≤ 12; total ≤ 600 words). If `finish_reason == length`: keep the old summary, retry once with "compress harder", never write a truncated summary.
- **Extractor:** gets the summary + the ~30 most related existing facts (not 50 KB of pages). Emits candidate facts `{text, kind, project, entities, importance}`.
- **Memory ops:** for each candidate, nearest existing facts (hybrid). Exact/near-exact (normalised Jaccard ≥ 0.85) → NOOP + touch. Otherwise one batched LLM call decides ADD / UPDATE(id) / SUPERSEDE(id) / NOOP.
- **MCP `remember`:** deterministic dedup only (no LLM in the MCP process); `sleep` does semantic merging later. Secret filter retained.

### Generated views

`cc-brain render` writes `projects/<slug>.md`, `failures/<kind>.md`, `identity/*.md` from live facts, grouped by kind, sorted by importance then last_seen, and commits the wiki. `skills/` stays hand-written and is indexed into `docs`. Old pages stay in git history; migration is lossless (every bullet becomes a fact; bullet-less section prose becomes a `note` fact).

## Phases (each independently testable)

| Phase | Deliverable | Test (real data) |
|---|---|---|
| 1 | Bounded summarizer, truncation never overwrites, `episodes` index over all summaries, `timeline` CLI + MCP | Truncation path with a stub API returns old summary untouched. Index all 3,789 summaries; `timeline --since 2026-10-01` lists that day's known sessions |
| 2 | `facts` store, lossless migration of the wiki, aliases, BM25 `recall` with ranking, `remember`/`correct`, MCP tools | Migration count = bullet count; eval set of real questions (from real misses in daily work) hits in top 5; bytes returned per query vs v2 |
| 3 | Ollama embeddings (local, private), hybrid RRF, Mem0-style consolidator replacing page appends | Eval set again, hybrid ≥ BM25; real summary through the consolidator produces ops, no duplicate ADDs |
| 4 | `render` views, `sleep` pass, daemon wiring, deploy (restart daemon), docs/skill updates | End-to-end: new session → summary → episode + facts → recall finds it; rendered pages ≤ 25 KB |

## Non-goals

- No remote vector DB, no graph DB. SQLite + numpy is enough at this scale (~5k facts, ~20k chunks).
- No auto-injection of summaries into prompts. Agents **query** (Bachir's call: querying beats injected summaries).

## Status (2026-10-02)

| Phase | Commit | Result |
|---|---|---|
| 1 | a412627 | 3,789 summaries → 19,001 episodes, all embedded; truncation never overwrites |
| 2 | a742cb9 | 1,943 facts migrated (lossless); MCP recall/timeline/remember/correct pass `tests/it_mcp.py` |
| 3 | ef352a9 | hit@5 20/20 (v2, BM25, hybrid); 1,562 KB → ~60 KB read per eval run; `it_consolidate.py 3` PASS, no duplicate ADDs |
| 4 | 3a662dd | render: 49 pages, max 24.8 KB, 1,945 bullets = live facts; daemon on v3 path; `it_e2e_wiring.py` PASS (LLM stubbed) |

Resolved 2026-10-02: provider chain (`cc_brain/llm.py`, agy Gemini → Meridian → OpenRouter) replaced the single OpenRouter endpoint; `it_e2e_wiring.py --live` and `it_llm_chain.py` PASS. Rationale and measurements: `docs/cc-brain-design.md`.
