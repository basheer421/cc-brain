# cc-brain

macOS menu bar app that watches Claude Code session logs and generates living Markdown summaries via OpenRouter.

## Project structure

- `cc_brain/` — Python package (app.py, watcher.py, scanner.py, extractor.py, summarizer.py, config.py)
- `icons/` — macOS template menu bar icons (brain-idle, brain-sync, brain-error at 1x and 2x)
- `build_app.sh` — builds the .app bundle into `dist/CC Brain.app`
- `install.sh` — full install: deps, config, build, copy to /Applications, launch
- `uninstall.sh` — removes app, preserves data
- `cc-brain.sh` — launchd daemon management (install/start/stop/status/logs/run)

## Development

```bash
pip3 install -r requirements.txt
python3 -m cc_brain.app          # run directly
./build_app.sh                   # build .app bundle
./install.sh                     # full install
```

## Runtime paths

- Config: `~/.cc-brain/config.json`
- Summaries: `~/.cc-brain/summaries/<project>-<timestamp>.md`
- State: `~/.cc-brain/state/offsets.json`
- Logs: `~/.cc-brain/logs/`
