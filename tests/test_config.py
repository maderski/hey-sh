import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hey import config


class TestConfig(unittest.TestCase):
    def test_load_config_returns_empty_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            with patch.object(config, "CONFIG_FILE", config_file):
                self.assertEqual(config.load_config(), {})

    def test_load_config_returns_empty_for_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "config.json"
            config_file.write_text("{invalid json")
            with patch.object(config, "CONFIG_FILE", config_file):
                self.assertEqual(config.load_config(), {})

    def test_save_config_writes_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            config_file = Path(tmpdir) / "nested" / "config.json"
            payload = {"host": "http://llm:8080", "model": "llama3"}
            with patch.object(config, "CONFIG_FILE", config_file):
                config.save_config(payload)

            self.assertEqual(json.loads(config_file.read_text()), payload)

    def test_resolve_endpoint_prefers_endpoint_over_host(self) -> None:
        resolved = config.resolve_endpoint(
            {
                "endpoint": "http://custom/v1/chat/completions",
                "host": "http://ignored:8080",
            }
        )

        self.assertEqual(resolved, "http://custom/v1/chat/completions")

    def test_resolve_endpoint_appends_default_path_to_host(self) -> None:
        resolved = config.resolve_endpoint({"host": "http://localhost:11434/"})

        self.assertEqual(resolved, "http://localhost:11434/v1/chat/completions")

    def test_resolve_endpoint_uses_default_when_config_empty(self) -> None:
        self.assertEqual(
            config.resolve_endpoint({}),
            "http://localhost:8080/v1/chat/completions",
        )
