import io
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.modules.setdefault("httpx", SimpleNamespace(Client=None, ConnectError=Exception, TimeoutException=Exception, HTTPStatusError=Exception))

from hey import cli


class FakeStream(io.StringIO):
    def __init__(self, value: str = "", is_tty: bool = False) -> None:
        super().__init__(value)
        self._is_tty = is_tty

    def isatty(self) -> bool:
        return self._is_tty


class TestCliParsing(unittest.TestCase):
    def test_parse_response_options_with_explanations(self) -> None:
        response = (
            "1. cat /etc/arch-release\n"
            "Check the distro release file.\n"
            "2. uname -r\n"
            "Show the kernel version.\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(
            options,
            [
                {
                    "number": "1",
                    "command": "cat /etc/arch-release",
                    "body": "1. cat /etc/arch-release\nCheck the distro release file.",
                },
                {
                    "number": "2",
                    "command": "uname -r",
                    "body": "2. uname -r\nShow the kernel version.",
                },
            ],
        )

    def test_parse_response_options_rejects_non_sequential_numbering(self) -> None:
        response = "1. pwd\n3. uname -a\n"

        self.assertEqual(cli.parse_response_options(response), [])

    def test_parse_response_options_ignores_numbered_explanation_lines(self) -> None:
        # --explain response: plain command first, then numbered explanation lines.
        # Should NOT be treated as ambiguous options.
        response = (
            "ls -la\n"
            "1. Lists all files including hidden ones\n"
            "2. Shows detailed information (permissions, size, date)\n"
        )

        self.assertEqual(cli.parse_response_options(response), [])

    def test_extract_command_strips_inline_backticks(self) -> None:
        self.assertEqual(cli.extract_command("`ls -la`"), "ls -la")

    def test_select_option_accepts_valid_choice_after_retry(self) -> None:
        with patch("builtins.input", side_effect=["x", "2"]):
            selected = cli.select_option(
                [
                    {"number": "1", "command": "pwd", "body": "1. pwd"},
                    {"number": "2", "command": "uname -a", "body": "2. uname -a"},
                ]
            )

        self.assertEqual(selected, {"number": "2", "command": "uname -a", "body": "2. uname -a"})


class TestCliMain(unittest.TestCase):
    def test_main_exits_noninteractive_on_multiple_options(self) -> None:
        stdout = FakeStream(is_tty=False)
        stderr = FakeStream(is_tty=False)
        stdin = FakeStream(is_tty=False)

        with patch("sys.argv", ["hey", "ambiguous query"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("hey.cli.detect_shell", return_value="zsh"), patch(
            "hey.cli.detect_platform", return_value="macOS"
        ), patch(
            "hey.cli.query_llm", return_value="1. cat /etc/arch-release\n2. uname -r"
        ), patch(
            "hey.cli.save_history"
        ) as save_history:
            with self.assertRaises(SystemExit) as cm:
                cli.main()

        self.assertEqual(cm.exception.code, 1)
        self.assertIn("1. cat /etc/arch-release", stdout.getvalue())
        self.assertIn("Multiple command options need an interactive terminal", stderr.getvalue())
        save_history.assert_not_called()

    def test_main_saves_selected_command(self) -> None:
        stdout = FakeStream(is_tty=True)
        stderr = FakeStream(is_tty=True)
        stdin = FakeStream(is_tty=True)

        with patch("sys.argv", ["hey", "ambiguous query"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("builtins.input", side_effect=["2", "n"]), patch(
            "hey.cli.detect_shell", return_value="zsh"
        ), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm", return_value="1. cat /etc/arch-release\n2. uname -r"
        ), patch(
            "hey.cli.save_history"
        ) as save_history:
            cli.main()

        save_history.assert_called_once_with("ambiguous query", "uname -r", "zsh")
        self.assertIn("Selected: uname -r", stdout.getvalue())
        self.assertEqual(stderr.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
