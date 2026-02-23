# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

`hey-sh` is a shell-native natural language CLI assistant. It takes a natural-language query, calls a local llama.cpp OpenAI-compatible endpoint, and returns a shell command — with optional explanation, run prompt, clipboard copy, and history.

## Commands

```
uv sync                        # install deps
uv run hey "query"             # run without installing
pip install -e .               # editable install
python -m hey "query"          # run via module
ruff check . && ruff format .  # lint + format
```

## Entry point

`hey = "hey.cli:main"` — the `hey` command is the only entry point.

## Architecture

```
hey/
├── __init__.py     # version string
├── __main__.py     # python -m hey support
├── cli.py          # argparse + orchestration
├── llm.py          # httpx call to llama.cpp OpenAI-compatible endpoint
├── shell.py        # shell detection + subprocess execution
├── history.py      # JSON history in ~/.local/share/hey/history.json
└── clipboard.py    # pbcopy / xclip / clip dispatch
```

## LLM endpoint

Default: `http://localhost:8080/v1/chat/completions` (llama.cpp server).
Override with `--endpoint URL` and `--model NAME`.

## Run prompt behavior

- Default: prompt `[y/N]` only when stdout is a TTY and stdin is not piped
- `--run` / `-r`: execute immediately without prompting
- `--no-run`: never prompt
- Stdin piped → run prompt is always skipped
