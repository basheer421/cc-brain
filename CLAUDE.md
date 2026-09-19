# cc-brain

macOS menu bar app that watches AI coding agent sessions and generates living Markdown summaries via any OpenAI-compatible endpoint.

Supports Claude Code, Hermes, and Pi. Agent-agnostic by design.

## Project structure

- `cc_brain/` — Python package (app.py, watcher.py, scanner.py, extractor.py, summarizer.py, config.py, pi_scanner.py)
- `website/` — Vite + React + Tailwind landing site, deployed to CF Pages (`cc-brain.bachir.me`)
- `icons/` — macOS template menu bar icons (brain-idle, brain-sync, brain-error at 1x and 2x)
- `build_app.sh` — builds the .app bundle into `dist/CC Brain.app`
- `install.sh` — full install: deps, config, build, copy to /Applications, launch
- `uninstall.sh` — removes app, preserves data
- `cc-brain.sh` — launchd daemon management (install/start/stop/status/logs/run)

## Development

```bash
# Python app
pip3 install -r requirements.txt
python3 -m cc_brain.app          # run directly
./build_app.sh                   # build .app bundle
./install.sh                     # full install

# Website
cd website && bun install && bun run dev
```

## Deploy website

```bash
source .envrc
cd website && bun run build
wrangler pages deploy website/dist --project-name cc-brain
```

CF Pages project: `cc-brain` on Cloudflare account `7ffe6df225126017d3f5ac172d8517d3`.
Credentials in `.envrc` (gitignored). Domain: `cc-brain.bachir.me`.

## Runtime paths

- Config: `~/.cc-brain/config.json`
- Summaries: `~/.cc-brain/summaries/<project>-<timestamp>.md`
- State: `~/.cc-brain/state/offsets.json`
- Logs: `~/.cc-brain/logs/`
