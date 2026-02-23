import json
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "hey" / "config.json"
DEFAULT_PATH = "/v1/chat/completions"


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    try:
        return json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_config(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2))


def resolve_endpoint(config: dict) -> str:
    """Return the endpoint URL from config.

    Supports two keys (in priority order):
      endpoint  – full URL, used as-is
      host      – base URL, DEFAULT_PATH is appended automatically
    """
    if "endpoint" in config:
        return config["endpoint"]
    if "host" in config:
        host = config["host"].rstrip("/")
        return f"{host}{DEFAULT_PATH}"
    return "http://localhost:8080/v1/chat/completions"
