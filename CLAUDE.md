# cc-brain

Long-term memory for AI coding agents: a daemon distils Pi / Hermes sessions into atomic facts and
time-indexed episodes (SQLite), served over MCP (`recall`, `timeline`, `remember`, `correct`, `forget`, `wiki_search`).

**Read `docs/cc-brain-design.md` before changing ranking, write gates, sleep, or LLM providers.** It records why
each choice was made and the measurements behind it.

## Project structure

- `cc_brain/brain.py` — store: facts, episodes, docs, aliases; hybrid recall (BM25 + dense, RRF, re-rank)
- `cc_brain/memory_ops.py` — write path (ADD/UPDATE/SUPERSEDE/NOOP + paraphrase gate) and nightly `sleep`
- `cc_brain/llm.py` — provider chain (`config.llm.chain`), cooldowns, `llm.jsonl` attempt log
- `cc_brain/pi_sessions.py`, `daemon.py` — session watching, bounded summarizer, daily maintenance
- `cc_brain/render.py` — generated Markdown wiki view (≤ 25 KB pages)
- `cc_brain/mcp_server.py`, `cli.py` — interfaces
- `cc_brain/installer.py` — `init` / `doctor` / `uninstall` (config, providers, service, MCP, Pi extension); `install.sh` only installs the binary
- `cc_brain/integrations/pi/cc-brain-recall.ts` — Pi auto-recall extension, shipped as package data and symlinked by `init`
- `cc_brain/consolidator.py`, `search.py`, `compact.py`, `migrate*.py` — v2 code kept for migration/compat
- `website/` — Vite + React + Tailwind landing site (Cloudflare Pages, `cc-brain.bachir.me`)

## Development

Tooling: **uv** for Python (never bare pip), **pnpm** for the website (never npm).

```bash
CC_BRAIN_SOURCE=. ./install.sh   # editable uv tool install + cc-brain init
cc-brain doctor
cc-brain start -f                # foreground daemon (stop the service first)
cc-brain recall "query"          # try retrieval
```

Tests are integration-only (`uv run python tests/<name>.py`), on a **copy** of the live `brain.db` (see README → Tests). Personal eval cases and
probes live in `tests/local/` (gitignored); `tests/*.example.json` show the shape.

**This repo is public.** Never commit real memory content (facts, names, hosts, IPs, client details) in tests,
fixtures or docs — put it in `tests/local/` or `docs/local/`.

## Deploy website

```bash
source .envrc                    # Cloudflare credentials (gitignored)
cd website && pnpm install && pnpm build
pnpm dlx wrangler pages deploy dist --project-name cc-brain
```

`curl cc-brain.bachir.me | bash` serves the `install.sh` copied into the build (`functions/_middleware.ts`), not
GitHub, so **redeploy the site after changing `install.sh`**.

## Runtime paths

- DB: `~/.cc-brain/brain.db` · Config: `~/.cc-brain/config.json` · Summaries: `~/.cc-brain/summaries/`
- State: `~/.cc-brain/state/` · Logs: `~/.cc-brain/logs/{daemon.log,llm.jsonl}`

## Installer testing

Test `install.sh` / `init` against a throwaway HOME and a test service label, never your real one:
`env HOME=/tmp/ccb-t CC_BRAIN_SOURCE=$PWD CC_BRAIN_SERVICE_LABEL=io.ccbrain.test UV_CACHE_DIR=~/.cache/uv bash install.sh --yes`.
launchctl talks to the real user domain even with a fake HOME, so legacy-agent cleanup only acts on plists under HOME.
