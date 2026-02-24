# hey-sh

A shell-native natural language CLI assistant. Ask for a shell command in plain English — `hey` calls a local LLM and returns the command, ready to copy, run, or explain.

## Requirements

- Python 3.9+
- A running [llama.cpp](https://github.com/ggerganov/llama.cpp) server (or any OpenAI-compatible endpoint) on `http://localhost:8080`

## Installation

### macOS + zsh (recommended)

Add `~/.local/bin` to your PATH if it isn't already:

```zsh
export PATH="$HOME/.local/bin:$PATH"
```

Add that line to your `~/.zshrc`, then reload it:

```bash
source ~/.zshrc
```

Requires uv to be installed on Mac
```bash
brew install uv
```

Then install `hey` as a global tool from the project directory:

```bash
uv tool install .
```

After that you can run `hey "..."` from anywhere.

### Editable install (development)

```bash
pip install -e .
```

Or just sync dependencies without installing:

```bash
uv sync
```

## Usage

```
hey [query] [options]
```

### Basic query

```bash
hey "list all open ports"
# → ss -tlnp
# Run it? [y/N]
```

### Options

| Flag | Short | Description |
|------|-------|-------------|
| `--explain` | `-e` | Print the command followed by a concise explanation |
| `--run` | `-r` | Run the command immediately without prompting |
| `--no-run` | | Never prompt to run |
| `--copy` | `-c` | Copy the command to the clipboard |
| `--history` | `-H` | Print recent command history and exit |
| `--history-n N` | | Number of history entries to show (default: 20) |
| `--endpoint URL` | | LLM endpoint URL (default: `http://localhost:8080/v1/chat/completions`) |
| `--model NAME` | | Model name sent in the request payload (default: `local`) |
| `--test` | | Test the connection to the LLM endpoint and exit |

### Examples

```bash
# Get a command with explanation
hey -e "compress a directory"

# Run immediately without prompting
hey -r "show disk usage"

# Copy the command to clipboard
hey -c "find files modified in the last 24 hours"

# Pipe stdin as context
echo "foo bar baz" | hey "sort these words"

# Use stdin as the full query
echo "show running docker containers" | hey

# View recent history
hey -H

# View last 50 history entries
hey -H --history-n 50

# Use a different endpoint or model
hey --endpoint http://localhost:11434/v1/chat/completions --model llama3 "restart nginx"
```

## Configuration

Create `~/.config/hey/config.json` to set persistent defaults.

**Set a custom LLM host** (path `/v1/chat/completions` is appended automatically):

```json
{
  "host": "http://[IP ADDRESS]:[PORT]"
}
```

**Or specify the full endpoint URL:**

```json
{
  "endpoint": "http://[IP ADDRESS]:[PORT]/v1/chat/completions"
}
```

**All supported keys:**

| Key | Description | Example |
|-----|-------------|---------|
| `host` | Base URL of your LLM server | `"http://[IP ADDRESS]:[PORT]"` |
| `endpoint` | Full endpoint URL (overrides `host`) | `"http://[IP ADDRESS]:[PORT]/v1/chat/completions"` |
| `model` | Model name sent in the request | `"llama3"` |

CLI flags (`--endpoint`, `--model`) always override config file values.

### Testing your connection

```bash
hey --test
# Endpoint: http://llama.cpp/v1/chat/completions
# OK  312ms  model=llama-3.2-3b

# On failure:
# Endpoint: http://llama.cpp/v1/chat/completions
# FAIL  Could not connect to http://llama.cpp/v1/chat/completions
```

`--test` respects your config file and any `--endpoint` / `--model` flags passed alongside it.

## Run prompt behavior

By default, `hey` prompts `[y/N]` after printing a command — but only when both stdout and stdin are a TTY. The prompt is automatically skipped when:

- stdin is piped (e.g., `echo "..." | hey`)
- stdout is redirected
- `--no-run` is passed
- `--run` / `-r` is passed (runs immediately instead)

## History

Commands are saved to `~/.local/share/hey/history.json` (max 500 entries).

## Development

```bash
# Install in editable mode
pip install -e .

# Lint and format
ruff check . && ruff format .
```
