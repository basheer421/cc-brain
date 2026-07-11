# cc-brain

macOS menu bar app that watches Claude Code session logs and generates living Markdown summaries via OpenRouter (DeepSeek V4 Flash).

## Project structure

- `cc_brain/` — Python package (app.py, watcher.py, scanner.py, extractor.py, summarizer.py, config.py)
- `icons/` — macOS template menu bar icons (brain-idle, brain-sync, brain-error at 1x and 2x)
- `build_app.sh` — builds the .app bundle into `dist/CC Brain.app`
- `cc-brain.sh` — daemon management (install/start/stop/status/logs/run)
- Config: `~/.cc-brain/config.json`
- Summaries: `~/.cc-brain/summaries/<session-id>.md`
- State: `~/.cc-brain/state/offsets.json`

## Development

```bash
pip3 install -r requirements.txt
python3 -m cc_brain.app          # run directly
./build_app.sh                   # build .app bundle
```

## How it works

1. Watches `~/.claude/projects/**/*.jsonl` for changes (watchdog)
2. On change: debounces 3s, extracts new user/assistant messages
3. Sends delta + previous summary to OpenRouter for an updated living summary
4. Writes result to `~/.cc-brain/summaries/<session-id>.md`
