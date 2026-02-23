import json
import os
from datetime import datetime, timezone
from pathlib import Path

HISTORY_FILE = Path.home() / ".local" / "share" / "hey" / "history.json"
MAX_ENTRIES = 500


def _load() -> list:
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return []


def _save(entries: list) -> None:
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_FILE.write_text(json.dumps(entries, indent=2))


def save_history(query: str, command: str, shell: str) -> None:
    entries = _load()
    entries.append(
        {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "query": query,
            "command": command,
            "shell": shell,
        }
    )
    if len(entries) > MAX_ENTRIES:
        entries = entries[-MAX_ENTRIES:]
    _save(entries)


def print_history(n: int = 20) -> None:
    entries = _load()
    recent = entries[-n:] if len(entries) > n else entries
    if not recent:
        print("No history yet.")
        return
    for entry in recent:
        ts = entry.get("timestamp", "")
        query = entry.get("query", "")
        command = entry.get("command", "")
        print(f'{ts}  "{query}"')
        print(f"  → {command}")
