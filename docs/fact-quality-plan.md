# Fact quality plan (Oct 2026)

## Problem (audit of 45 recent facts, 2026-10-07)
- ~8/45 noise: MR/branch status logs that won't matter in a week.
- 4 duplicate pairs slipped in.
- Stale facts never superseded ("X kept 48h" stayed live after a later "X destroyed").
- ~5 wrong project/kind (project = session cwd, not subject).
- Auto-recall injects off-topic facts: always top 3–5, no relevance floor.

## Root causes (code)
- `add_fact` dedup gate too strict: jaccard ≥ 0.85 or cosine ≥ 0.97.
- `memory_ops.consolidate` shows the LLM related facts from ONE recall over the whole summary,
  project-boosted → misses cross-project duplicates and the facts it should supersede.
- OPS_PROMPT has no rule against MR-status facts; project taken from cwd.
- Daily `sleep` spends 60 agy calls re-checking unchanged clusters (merged 0–1/day).

## Decisions
| Topic | Choice | Why |
|---|---|---|
| General decision model (clef-flash) | **No** for cc-brain | Generic, 6 GB, weak on contradiction (ANLI 59). Revisit as a shared endpoint once a 2nd project needs it. |
| Relevance gate (P5) | **A:** embedding-similarity threshold first (0 RAM) → **B:** `ms-marco-MiniLM-L6` cross-encoder (~100 MB) only if A fails eval. Never an always-loaded 1 GB reranker. | RAM budget 0–100 MB. |
| Keep/drop + kind/project (P1) | Prompt rules first, then logistic regression / SetFit on existing nomic embeddings | ~KB, ms, learns *our* notion of junk. Labels: superseded/forgotten facts + hand-graded set. |
| same/replaces/different (P2) | Stays on the LLM chain | Hardest judgment; NLI (DeBERTa) only as optional pre-filter later. |
| Graph | SQLite `fact_entities` table, regex/alias extraction — no graph DB | ~80% of the value, zero new services. |
| Embedding model | Keep `nomic-embed-text` | Retrieval isn't the bottleneck; re-embed of ~21k items not worth it. |

## Plan (in order; each step has an eval before the next)
| # | Step | Classifier? | Done when |
|---|---|---|---|
| 0 | Eval set: hand-label ~50 auto-recall prompts (relevant y/n per injected fact) + 45 graded facts (keep/drop, kind, project) | — | `docs/local/eval/*.jsonl` exists |
| 1 | **P6** one-off cleanup: merge 4 dup pairs, supersede the stale fact | — | facts fixed via brain API |
| 2 ✅ | **P1a** OPS_PROMPT rules: no MR/branch status, project by subject, user rules via `config.memory_rules` | — | 2–3 days of output reviewed |
| 3 | **P5-A** auto-recall: inject only if cosine(prompt, fact) ≥ threshold (tune on eval) | threshold | eval precision ≥ ~85%, otherwise go 3b |
| 3b | **P5-B** MiniLM-L6 cross-encoder, load on demand, unload after 10 min idle | reranker | beats 3 on eval |
| 3c | Query with prompt + last assistant turn; cap generic person/preference facts to 1; inject ≤3 | — | beats 29% on eval |
| 4 | **P1b** keep/drop (+kind/project) classifier on nomic embeddings, gate new facts | own classifier | ≥ ~85% on eval |
| 5 | **P2** per-candidate cross-project dense search (cos ≥ 0.80) → LLM same/replaces/different | — | dup pairs from audit would be caught |
| 6 | **P4** `fact_entities` table (hosts, IPs, MR/ticket ids, repos, people) + backfill | — | only if stale facts persist after 5 |
| 7 | **P3** daily sleep: skip unchanged clusters, group by entity, ask "which are outdated" | — | only after 6 |

## Already shipped (feat/llm-retry-queue, d45478c)
Durable retry queue, wake-aware 90 s pause, 180 s wall-clock call cap, 5 s call pacing.
Verified overnight 2026-10-06→07: 25 wakes, 0 timeouts, 0 lost jobs, agy p50 11.7 s / max 132 s.

## Results
- 2026-10-07 step 1 done: 4 dup pairs merged/retired, stale fact superseded.
- 2026-10-07 step 0: `docs/local/eval/recall.json` = 50 real prompts × 160 injected facts, labels drafted by agent, approved by the user.
  Current auto-recall precision **29%** (46/160 relevant).
- 2026-10-07 step 3 (P5-A) **FAILED**: nomic cosine median relevant 0.66 vs irrelevant 0.62; best threshold 0.65 → 39% precision at 54% recall.
  A threshold can't separate them → go to 3b (cross-encoder).

- 2026-10-07 step 3b: rerankers barely beat nomic. AUC (0.5 = coin flip): nomic 0.67, MiniLM-L6 0.68 (7 ms, ~400 MB),
  mxbai-xsmall 0.62, bge-reranker-base 0.72 (32 ms, ~1.1 GB). At top-30% cut: best precision 48% / recall 50%.
  Conclusion: scoring is not the bottleneck — prompts are context-dependent ("ok done", "yea") and the pool is full of
  generic preference facts. Don't ship a reranker; fix the query/pool instead (see step 3c).

- 2026-10-07 step 3c: query = prompt + last assistant reply (Files-changed footer stripped), ≤1 generic fact, ≤3 facts.
  precision 28% (vs 29%), prompts with ≥1 relevant 29/50 (same). No gain. First run was invalid: 32/44 contexts were the footer.
  Conclusion: retrieval method is not the lever. For ~20/50 prompts no relevant fact exists in the pool; the pool is
  dominated by stale MR/branch/status facts. Fix the pool first (steps 2, 4, 5); revisit injection afterwards.

## Open
- Remove OpenRouter from chain (402, out of credit).
- Daily sleep marks itself done before running (failed run skips the day).
