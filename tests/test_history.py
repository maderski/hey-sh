import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hey import history


class TestHistory(unittest.TestCase):
    def test_load_returns_empty_when_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "history.json"
            with patch.object(history, "HISTORY_FILE", history_file):
                self.assertEqual(history._load(), [])

    def test_load_returns_empty_for_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "history.json"
            history_file.write_text("{oops")
            with patch.object(history, "HISTORY_FILE", history_file):
                self.assertEqual(history._load(), [])

    def test_save_history_trims_to_max_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "history.json"
            existing = [
                {
                    "timestamp": f"2024-01-01T00:00:{i:02d}+00:00",
                    "query": f"query {i}",
                    "command": f"cmd {i}",
                    "shell": "zsh",
                }
                for i in range(history.MAX_ENTRIES)
            ]
            history_file.write_text(json.dumps(existing))

            with patch.object(history, "HISTORY_FILE", history_file):
                history.save_history("new query", "new cmd", "bash")

            entries = json.loads(history_file.read_text())
            self.assertEqual(len(entries), history.MAX_ENTRIES)
            self.assertEqual(entries[0]["query"], "query 1")
            self.assertEqual(entries[-1]["query"], "new query")
            self.assertEqual(entries[-1]["command"], "new cmd")
            self.assertEqual(entries[-1]["shell"], "bash")
            self.assertIn("timestamp", entries[-1])

    def test_print_history_outputs_recent_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "history.json"
            history_file.write_text(
                json.dumps(
                    [
                        {
                            "timestamp": "2024-01-01T00:00:00+00:00",
                            "query": "old",
                            "command": "echo old",
                            "shell": "zsh",
                        },
                        {
                            "timestamp": "2024-01-02T00:00:00+00:00",
                            "query": "new",
                            "command": "echo new",
                            "shell": "zsh",
                        },
                    ]
                )
            )
            stdout = io.StringIO()

            with patch.object(history, "HISTORY_FILE", history_file), patch("sys.stdout", stdout):
                history.print_history(1)

            self.assertNotIn('"old"', stdout.getvalue())
            self.assertIn('2024-01-02T00:00:00+00:00  "new"', stdout.getvalue())
            self.assertIn("  → echo new", stdout.getvalue())

    def test_print_history_handles_empty_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            history_file = Path(tmpdir) / "history.json"
            stdout = io.StringIO()

            with patch.object(history, "HISTORY_FILE", history_file), patch("sys.stdout", stdout):
                history.print_history()

            self.assertEqual(stdout.getvalue().strip(), "No history yet.")
