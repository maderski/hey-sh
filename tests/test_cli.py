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


class TestLooksLikeCommand(unittest.TestCase):
    def test_single_word_accepted(self) -> None:
        self.assertTrue(cli._looks_like_command("pwd"))
        self.assertTrue(cli._looks_like_command("ls"))

    def test_command_with_flag_accepted(self) -> None:
        self.assertTrue(cli._looks_like_command("ls -la"))
        self.assertTrue(cli._looks_like_command("grep -r pattern ."))
        self.assertTrue(cli._looks_like_command("uname -a"))

    def test_command_with_path_arg_accepted(self) -> None:
        self.assertTrue(cli._looks_like_command("cat /etc/passwd"))
        self.assertTrue(cli._looks_like_command("python3 script.py"))
        self.assertTrue(cli._looks_like_command("node app.js"))

    def test_subcommand_style_accepted(self) -> None:
        self.assertTrue(cli._looks_like_command("git status"))
        self.assertTrue(cli._looks_like_command("kubectl get pods"))
        self.assertTrue(cli._looks_like_command("npm install"))
        self.assertTrue(cli._looks_like_command("docker ps"))
        self.assertTrue(cli._looks_like_command("grep pattern file"))

    def test_tool_names_ending_in_s_accepted(self) -> None:
        # Tool names that end in 's' must not be rejected; only known prose
        # verbs are blocked.
        self.assertTrue(cli._looks_like_command("rails server"))
        self.assertTrue(cli._looks_like_command("nexus upload"))
        self.assertTrue(cli._looks_like_command("travis encrypt"))
        self.assertTrue(cli._looks_like_command("terminus deploy"))

    def test_uppercase_commands_accepted(self) -> None:
        # PowerShell-style and other mixed-case commands must be accepted.
        self.assertTrue(cli._looks_like_command("Get-Process"))
        self.assertTrue(cli._looks_like_command("Set-Location C:\\Users"))
        self.assertTrue(cli._looks_like_command("Get-Process -Name python"))

    def test_prose_verbs_rejected(self) -> None:
        self.assertFalse(cli._looks_like_command("shows hidden files"))
        self.assertFalse(cli._looks_like_command("lists all files in directory"))
        self.assertFalse(cli._looks_like_command("searches recursively"))
        self.assertFalse(cli._looks_like_command("displays file permissions"))

    def test_uppercase_prose_rejected(self) -> None:
        # Uppercase-initial prose verbs must still be rejected via the
        # case-insensitive _PROSE_STARTERS lookup.
        self.assertFalse(cli._looks_like_command("Shows hidden files"))
        self.assertFalse(cli._looks_like_command("Lists all files in directory"))

    def test_function_word_starters_rejected(self) -> None:
        # Articles, demonstratives, and pronouns that open explanation sentences
        # must be rejected; they are never valid command names.
        self.assertFalse(cli._looks_like_command("This command lists hidden files"))
        self.assertFalse(cli._looks_like_command("The option shows output"))
        self.assertFalse(cli._looks_like_command("An alternative approach"))
        self.assertFalse(cli._looks_like_command("It also displays hidden files"))
        self.assertFalse(cli._looks_like_command("these files are hidden"))

    def test_imperative_prose_with_flag_rejected(self) -> None:
        # Imperative explanation text that contains a flag token must be rejected.
        # The _PROSE_STARTERS check must fire before the shell-token path so
        # that "Uses -a to include hidden files" is not promoted to a command.
        self.assertFalse(cli._looks_like_command("Uses -a to include hidden files"))
        self.assertFalse(cli._looks_like_command("Use -r for recursive search"))
        self.assertFalse(cli._looks_like_command("Adds -v for verbose output"))

    def test_preposition_starters_rejected(self) -> None:
        # Prepositions that open explanation clauses are never command names.
        self.assertFalse(cli._looks_like_command("To include hidden files"))
        self.assertFalse(cli._looks_like_command("By default this enables verbose"))
        self.assertFalse(cli._looks_like_command("With the -a flag hidden files appear"))

    def test_prose_punctuation_rejected(self) -> None:
        # Trailing commas and sentence-ending periods are reliable prose signals
        # and must cause rejection even when the line also contains a flag token,
        # so that "To include hidden files, add -a." is never a command.
        self.assertFalse(cli._looks_like_command("To include hidden files, add -a."))
        self.assertFalse(cli._looks_like_command("find files, then sort"))
        self.assertFalse(cli._looks_like_command("grep pattern file."))

    def test_bare_dot_path_not_rejected(self) -> None:
        # The bare "." (current directory) must not trigger the sentence-period
        # rejection so that "find . -name '*.txt'" remains valid.
        self.assertTrue(cli._looks_like_command("find . -name file"))
        self.assertTrue(cli._looks_like_command("grep -r pattern ."))

    def test_special_shell_starters_accepted(self) -> None:
        # Commands that start with non-alphanumeric shell tokens must be accepted.
        self.assertTrue(cli._looks_like_command("[ -f file ]"))
        self.assertTrue(cli._looks_like_command("(cd /tmp && ls)"))
        self.assertTrue(cli._looks_like_command(": >file"))

    def test_hyphen_initial_multi_word_rejected(self) -> None:
        # Multi-word text starting with a hyphen is a flag description, not a
        # command invocation, and must be rejected regardless of what follows.
        self.assertFalse(cli._looks_like_command("-l shows long listing format"))
        self.assertFalse(cli._looks_like_command("-v verbose output"))


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

    def test_parse_response_options_special_shell_starters_parsed(self) -> None:
        # Option headers that begin with non-alphanumeric shell tokens must be
        # parsed as selectable options so main() never falls back to
        # extract_command() and produces a literal "1. [ -f file ]" string.
        response = (
            "1. [ -f file ] && cat file\n"
            "Test and print if file exists.\n"
            "2. (cd /tmp && ls)\n"
            "List /tmp contents in a subshell.\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "[ -f file ] && cat file")
        self.assertEqual(options[1]["command"], "(cd /tmp && ls)")

    def test_parse_response_options_uppercase_commands_parsed(self) -> None:
        # Uppercase-initial option headers (e.g. PowerShell cmdlets) must be
        # parsed as selectable options, not dropped, so main() never falls back
        # to extract_command() and runs "1. Get-Process" as literal text.
        response = (
            "1. Get-Process\n"
            "Lists running processes.\n"
            "2. Get-Process -Name python\n"
            "Filters by name.\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "Get-Process")
        self.assertEqual(options[1]["command"], "Get-Process -Name python")

    def test_parse_response_options_single_option_returned_for_malformed_list(self) -> None:
        # A partially malformed list (1 followed by 3, skipping 2) yields one
        # parseable option. That option is returned so main() uses the parsed
        # command rather than falling back to extract_command() which would
        # return the literal "1. pwd" string.
        response = "1. pwd\n3. uname -a\n"

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["command"], "pwd")

    def test_parse_response_options_ignores_numbered_explanation_lines(self) -> None:
        # --explain response: plain command first, then numbered explanation lines.
        # Should NOT be treated as ambiguous options.
        response = (
            "ls -la\n"
            "1. Lists all files including hidden ones\n"
            "2. Shows detailed information (permissions, size, date)\n"
        )

        self.assertEqual(cli.parse_response_options(response), [])

    def test_parse_response_options_uppercase_prose_not_treated_as_option(self) -> None:
        # An explanation line starting with an uppercase prose verb (e.g. "Lists
        # all files") must never become an option header — _looks_like_command
        # rejects it via the case-insensitive _PROSE_STARTERS lookup.
        response = (
            "1. ls -la\n"
            "2. Lists all files including hidden ones\n"
            "2. find . -name '*.txt'\n"
            "Shows all matching paths.\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "ls -la")
        self.assertIn("2. Lists all files", options[0]["body"])
        self.assertEqual(options[1]["command"], "find . -name '*.txt'")

    def test_parse_response_options_imperative_prose_with_flag_not_treated_as_option(self) -> None:
        # "2. Uses -a to include hidden files" contains a flag token (-a) but
        # must still be absorbed into option 1's body because "uses" is in
        # _PROSE_STARTERS, which is checked before the shell-token path.
        response = (
            "1. ls -la\n"
            "2. Uses -a to include hidden files\n"
            "2. find . -name '*.txt'\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "ls -la")
        self.assertIn("2. Uses -a to include hidden files", options[0]["body"])
        self.assertEqual(options[1]["command"], "find . -name '*.txt'")

    def test_parse_response_options_preposition_prose_with_flag_not_treated_as_option(self) -> None:
        # "2. To include hidden files, add -a." starts with "to" (_PROSE_STARTERS)
        # and also contains prose punctuation; it must be absorbed, not promoted,
        # so the real option 2 command is still selectable.
        response = (
            "1. ls -la\n"
            "2. To include hidden files, add -a.\n"
            "2. find . -name '*.txt'\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "ls -la")
        self.assertIn("2. To include hidden files", options[0]["body"])
        self.assertEqual(options[1]["command"], "find . -name '*.txt'")

    def test_parse_response_options_function_word_prose_not_treated_as_option(self) -> None:
        # "2. This command lists hidden files" must be absorbed into option 1's
        # body (not promoted to option 2) so the real "2. find ..." line is
        # correctly selected and executed rather than the prose text.
        response = (
            "1. ls -la\n"
            "2. This command lists hidden files\n"
            "2. find . -name '*.txt'\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "ls -la")
        self.assertIn("2. This command lists hidden files", options[0]["body"])
        self.assertEqual(options[1]["command"], "find . -name '*.txt'")

    def test_parse_response_options_lowercase_prose_not_treated_as_option(self) -> None:
        # Lowercase prose explanation lines ("2. shows hidden files") must be
        # absorbed into option 1's body so the real "2. find ..." line becomes
        # option 2. Without the _looks_like_command guard, choosing option 2
        # would run "shows hidden files" instead of the actual command.
        response = (
            "1. ls -la\n"
            "2. shows hidden files\n"
            "2. find . -name '*.txt'\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "ls -la")
        self.assertIn("2. shows hidden files", options[0]["body"])
        self.assertEqual(options[1]["command"], "find . -name '*.txt'")

    def test_parse_response_options_hyphen_flag_line_not_treated_as_option(self) -> None:
        # An explanation line starting with a flag ("-l ...") must never become
        # an option header, so selected["command"] is never "-l shows long format".
        response = (
            "1. ls -la\n"
            "2. -l shows long listing format\n"
            "2. find . -name '*.txt'\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "ls -la")
        self.assertIn("2. -l shows long listing format", options[0]["body"])
        self.assertEqual(options[1]["command"], "find . -name '*.txt'")

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

    def test_main_uses_parsed_command_for_single_option_response(self) -> None:
        # When the model returns only one parseable numbered option, main() must
        # save/copy/run the extracted command ("ls -la"), not the literal line
        # text ("1. ls -la") that extract_command() would have returned.
        stdout = FakeStream(is_tty=False)
        stderr = FakeStream(is_tty=False)
        stdin = FakeStream(is_tty=False)

        with patch("sys.argv", ["hey", "--no-run", "list files"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("hey.cli.detect_shell", return_value="zsh"), patch(
            "hey.cli.detect_platform", return_value="macOS"
        ), patch(
            "hey.cli.query_llm", return_value="1. ls -la\nLists all files."
        ), patch(
            "hey.cli.save_history"
        ) as save_history:
            cli.main()

        save_history.assert_called_once_with("list files", "ls -la", "zsh")
        self.assertEqual(stderr.getvalue(), "")

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
