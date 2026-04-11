import io
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# hey.cli imports from hey.llm which imports httpx at module level.  Stub it
# out before importing hey.cli so the tests run without the real httpx package.
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
        # Title Case tool+subcommand pairs (two words) must be accepted so that
        # LLM responses like "1. Git status" or "2. Docker ps" are parsed as
        # real option headers rather than falling back to extract_command().
        self.assertTrue(cli._looks_like_command("Git status"))
        self.assertTrue(cli._looks_like_command("Docker ps"))
        # Three-word invocations with a shell token (dot in filename) are caught
        # by the shell-token path before the subcommand fallback is reached.
        self.assertTrue(cli._looks_like_command("Python manage.py runserver"))

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
        # Base-form (imperative) verbs that open numbered explanation steps must
        # also be caught before the shell-token check rescues them via a flag.
        self.assertFalse(cli._looks_like_command("Add -a to include hidden files"))
        self.assertFalse(cli._looks_like_command("Note that -v enables verbose output"))
        self.assertFalse(cli._looks_like_command("Include -r for recursive search"))
        self.assertFalse(cli._looks_like_command("Append --format=json for JSON output"))

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

    def test_absolute_path_commands_accepted(self) -> None:
        # Commands whose first token is an absolute or relative path must be
        # accepted even when later args have no shell tokens, so that option
        # headers like "1. /usr/bin/kubectl get pods" are parsed rather than
        # falling back to extract_command() which would save the literal
        # numbered line.
        self.assertTrue(cli._looks_like_command("/usr/bin/kubectl get pods"))
        self.assertTrue(cli._looks_like_command("/usr/local/bin/python3 manage.py"))
        self.assertTrue(cli._looks_like_command("./gradlew build"))
        self.assertTrue(cli._looks_like_command("/bin/ls"))

    def test_shell_token_with_comma_or_dot_not_rejected(self) -> None:
        # Words that contain shell metacharacters ($, {, ', /, …) are shell
        # tokens, not prose words, and must be exempted from the
        # prose-punctuation gate even if they happen to end with , or ..
        # Without this exemption parse_response_options() returns no options
        # and main() falls back to extract_command(), running a literal
        # "1. awk …" string instead of the real command.
        self.assertTrue(cli._looks_like_command("awk '{print $1, $2}' file.txt"))
        self.assertTrue(cli._looks_like_command("awk '{print $1}' data.csv"))
        self.assertTrue(cli._looks_like_command("find /var/log/. -name '*.log'"))

    def test_special_shell_starters_accepted(self) -> None:
        # Commands that start with non-alphanumeric shell tokens must be accepted.
        self.assertTrue(cli._looks_like_command("[ -f file ]"))
        self.assertTrue(cli._looks_like_command("(cd /tmp && ls)"))
        self.assertTrue(cli._looks_like_command(": >file"))

    def test_title_case_short_prose_rejected(self) -> None:
        # Title Case explanation phrases with 3+ words and no shell tokens must
        # be rejected so they are never promoted to option headers. Two-word
        # Title Case phrases (e.g. "Git status") are intentionally accepted as
        # tool+subcommand pairs; prose of that length is expected to be caught
        # by _PROSE_STARTERS before reaching the subcommand fallback.
        self.assertFalse(cli._looks_like_command("List hidden files"))
        self.assertFalse(cli._looks_like_command("Show all processes"))
        self.assertFalse(cli._looks_like_command("Display all output"))
        self.assertFalse(cli._looks_like_command("Enable verbose mode"))

    def test_single_word_prose_starter_rejected(self) -> None:
        # Single-word entries from _PROSE_STARTERS must be rejected so that
        # "2. lists" in LLM output is never promoted to an option header.
        self.assertFalse(cli._looks_like_command("lists"))
        self.assertFalse(cli._looks_like_command("shows"))
        self.assertFalse(cli._looks_like_command("this"))
        self.assertFalse(cli._looks_like_command("it"))
        self.assertFalse(cli._looks_like_command("the"))

    def test_single_word_uppercase_non_starter_rejected(self) -> None:
        # Single Title Case words that are NOT in _PROSE_STARTERS but are
        # clearly not command names must also be rejected so that option
        # headers like "2. Alternative" never displace the real command.
        # Gate 5 rejects them because they are uppercase with no / or -.
        self.assertFalse(cli._looks_like_command("Alternative"))
        self.assertFalse(cli._looks_like_command("None"))
        self.assertFalse(cli._looks_like_command("Output"))
        self.assertFalse(cli._looks_like_command("Default"))

    def test_hyphen_initial_single_word_rejected(self) -> None:
        # A lone flag token must be rejected whether or not it has trailing words.
        self.assertFalse(cli._looks_like_command("-v"))
        self.assertFalse(cli._looks_like_command("-l"))

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

    def test_parse_response_options_skips_introductory_prose(self) -> None:
        # Models sometimes prepend a lead-in line before the numbered list.
        # parse_response_options must find option 1 even when prose comes first.
        response = (
            "Here are a few options:\n"
            "1. cat /etc/arch-release\n"
            "Check the distro release file.\n"
            "2. uname -r\n"
            "Show the kernel version.\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "cat /etc/arch-release")
        self.assertEqual(options[1]["command"], "uname -r")

    def test_parse_response_options_ignores_code_fences(self) -> None:
        response = (
            "```bash\n"
            "1. cat /etc/arch-release\n"
            "Check the distro release file.\n"
            "2. uname -r\n"
            "Show the kernel version.\n"
            "```\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "cat /etc/arch-release")
        self.assertNotIn("```", options[0]["body"])
        self.assertEqual(options[1]["command"], "uname -r")

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

    def test_parse_response_options_base_form_imperative_prose_with_flag_not_treated_as_option(self) -> None:
        # "2. Add -a to include hidden files" uses an imperative base form
        # ("add") with a flag token (-a).  Without "add" in _PROSE_STARTERS the
        # shell-token check rescues the line, next_expected advances to 3, and
        # the real "2. find ..." line is swallowed into the body — so option 2
        # runs the prose string instead of the actual command.
        response = (
            "1. ls -la\n"
            "2. Add -a to include hidden files\n"
            "2. find . -name '*.txt'\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "ls -la")
        self.assertIn("2. Add -a to include hidden files", options[0]["body"])
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

    def test_parse_response_options_title_case_prose_not_treated_as_option(self) -> None:
        # "2. List hidden files" is short Title Case prose with no shell tokens.
        # The subcommand fallback must reject it so the real "2. find ..." line
        # becomes option 2 and is correctly executed instead of prose text.
        response = (
            "1. ls -la\n"
            "2. List hidden files\n"
            "2. find . -name '*.txt'\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "ls -la")
        self.assertIn("2. List hidden files", options[0]["body"])
        self.assertEqual(options[1]["command"], "find . -name '*.txt'")

    def test_parse_response_options_absolute_path_command_parsed(self) -> None:
        # Option headers whose first token is an absolute path must be parsed
        # as selectable options. Without the "/" check in the subcommand
        # fallback, parse_response_options() returns no options and main()
        # falls back to extract_command(), saving a literal "1. /usr/bin/..."
        # string instead of the real command.
        response = (
            "1. /usr/bin/kubectl get pods\n"
            "List running pods.\n"
            "2. /usr/bin/kubectl get services\n"
            "List running services.\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "/usr/bin/kubectl get pods")
        self.assertEqual(options[1]["command"], "/usr/bin/kubectl get services")

    def test_parse_response_options_awk_command_parsed(self) -> None:
        # awk '{print $1, $2}' contains $1, which ends with ',' and would
        # falsely trigger the prose-punctuation gate if shell-token words were
        # not exempted.  parse_response_options() must return two options so
        # main() never falls back to extract_command() and saves a literal
        # "1. awk ..." string.
        response = (
            "1. awk '{print $1, $2}' file.txt\n"
            "Print first two fields.\n"
            "2. cut -d' ' -f1,2 file.txt\n"
            "Cut first two fields by space.\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "awk '{print $1, $2}' file.txt")
        self.assertEqual(options[1]["command"], "cut -d' ' -f1,2 file.txt")

    def test_parse_response_options_single_word_prose_starter_not_treated_as_option(self) -> None:
        # "2. lists" is a single-word prose label that must be absorbed into
        # option 1's body so the real "2. find ..." line becomes option 2.
        response = (
            "1. ls -la\n"
            "2. lists\n"
            "2. find . -name '*.txt'\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "ls -la")
        self.assertIn("2. lists", options[0]["body"])
        self.assertEqual(options[1]["command"], "find . -name '*.txt'")

    def test_parse_response_options_single_word_uppercase_label_not_treated_as_option(self) -> None:
        # "2. Alternative" is a Title Case label not in _PROSE_STARTERS; it
        # must still be absorbed (not promoted) so the real "2. find ..." line
        # is correctly returned as option 2.  This is the exact scenario
        # described in the bug report: 1. ls -la\n2. Alternative\n2. find ...
        response = (
            "1. ls -la\n"
            "2. Alternative\n"
            "2. find . -name '*.txt'\n"
        )

        options = cli.parse_response_options(response)

        self.assertEqual(len(options), 2)
        self.assertEqual(options[0]["command"], "ls -la")
        self.assertIn("2. Alternative", options[0]["body"])
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

    def test_extract_command_skips_empty_lines(self) -> None:
        self.assertEqual(cli.extract_command("\n\nls -la"), "ls -la")

    def test_extract_command_skips_code_fences(self) -> None:
        self.assertEqual(cli.extract_command("```bash\nls -la\n```"), "ls -la")

    def test_extract_command_falls_back_to_first_line_when_all_fenced(self) -> None:
        # When every non-empty line is a code fence, fall back to lines[0].strip().
        self.assertEqual(cli.extract_command("```\n```"), "```")

    def test_extract_command_strips_inline_backticks(self) -> None:
        self.assertEqual(cli.extract_command("`ls -la`"), "ls -la")

    def test_select_option_returns_none_on_eof(self) -> None:
        with patch("builtins.input", side_effect=EOFError):
            selected = cli.select_option(
                [
                    {"number": "1", "command": "pwd", "body": "1. pwd"},
                    {"number": "2", "command": "uname -a", "body": "2. uname -a"},
                ]
            )
        self.assertIsNone(selected)

    def test_select_option_returns_none_on_empty_answer(self) -> None:
        with patch("builtins.input", return_value=""):
            selected = cli.select_option(
                [
                    {"number": "1", "command": "pwd", "body": "1. pwd"},
                    {"number": "2", "command": "uname -a", "body": "2. uname -a"},
                ]
            )
        self.assertIsNone(selected)

    def test_select_option_single_option_list(self) -> None:
        # select_option is only called when len(options) > 1, but it must work
        # correctly with a single-element list: the prompt shows [1-1] and
        # entering "1" returns the sole option.
        with patch("builtins.input", return_value="1"):
            selected = cli.select_option(
                [{"number": "1", "command": "pwd", "body": "1. pwd"}]
            )

        self.assertEqual(selected, {"number": "1", "command": "pwd", "body": "1. pwd"})

    def test_select_option_accepts_valid_choice_after_retry(self) -> None:
        with patch("builtins.input", side_effect=["x", "2"]):
            selected = cli.select_option(
                [
                    {"number": "1", "command": "pwd", "body": "1. pwd"},
                    {"number": "2", "command": "uname -a", "body": "2. uname -a"},
                ]
            )

        self.assertEqual(selected, {"number": "2", "command": "uname -a", "body": "2. uname -a"})

    def test_select_option_returns_none_and_prints_message_after_exhausting_attempts(self) -> None:
        # After 3 invalid inputs select_option must return None and print a
        # distinct message so the user knows they were cut off, not that they
        # cancelled voluntarily (which would be a silent Enter press).
        stdout = FakeStream(is_tty=True)
        options = [
            {"number": "1", "command": "pwd", "body": "1. pwd"},
            {"number": "2", "command": "uname -a", "body": "2. uname -a"},
        ]

        with patch("builtins.input", side_effect=["x", "x", "x"]), patch("sys.stdout", stdout):
            selected = cli.select_option(options)

        self.assertIsNone(selected)
        self.assertIn("Too many invalid attempts.", stdout.getvalue())


class TestCliMain(unittest.TestCase):
    def test_main_prints_help_and_exits_for_empty_query(self) -> None:
        stdout = FakeStream(is_tty=False)
        stderr = FakeStream(is_tty=False)
        stdin = FakeStream(is_tty=False)

        with patch("sys.argv", ["hey"]), patch("sys.stdin", stdin), patch("sys.stdout", stdout), patch("sys.stderr", stderr):
            with self.assertRaises(SystemExit) as cm:
                cli.main()

        self.assertEqual(cm.exception.code, 1)
        self.assertIn("usage:", stdout.getvalue())

    def test_main_uses_stdin_as_full_query(self) -> None:
        stdout = FakeStream(is_tty=False)
        stderr = FakeStream(is_tty=False)
        stdin = FakeStream("show running docker containers", is_tty=False)

        with patch("sys.argv", ["hey"]), patch("sys.stdin", stdin), patch("sys.stdout", stdout), patch(
            "sys.stderr", stderr
        ), patch("hey.cli.detect_shell", return_value="zsh"), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm", return_value="docker ps"
        ) as query_llm, patch("hey.cli.save_history") as save_history:
            cli.main()

        query_llm.assert_called_once()
        self.assertEqual(query_llm.call_args.kwargs["prompt"], "show running docker containers")
        save_history.assert_called_once_with("show running docker containers", "docker ps", "zsh")

    def test_main_appends_piped_stdin_to_query(self) -> None:
        stdout = FakeStream(is_tty=False)
        stderr = FakeStream(is_tty=False)
        stdin = FakeStream("foo bar baz", is_tty=False)

        with patch("sys.argv", ["hey", "sort these words"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("hey.cli.detect_shell", return_value="zsh"), patch(
            "hey.cli.detect_platform", return_value="macOS"
        ), patch("hey.cli.query_llm", return_value="sort") as query_llm, patch(
            "hey.cli.save_history"
        ) as save_history:
            cli.main()

        self.assertEqual(query_llm.call_args.kwargs["prompt"], "sort these words\nfoo bar baz")
        save_history.assert_called_once_with("sort these words\nfoo bar baz", "sort", "zsh")

    def test_main_history_flag_prints_history_and_exits(self) -> None:
        with patch("sys.argv", ["hey", "--history", "--history-n", "5"]), patch("hey.cli.print_history") as print_history:
            with self.assertRaises(SystemExit) as cm:
                cli.main()

        self.assertEqual(cm.exception.code, 0)
        print_history.assert_called_once_with(5)

    def test_main_test_flag_prints_success_and_exits(self) -> None:
        stdout = FakeStream(is_tty=False)

        with patch("sys.argv", ["hey", "--test"]), patch("sys.stdout", stdout), patch(
            "hey.cli.load_config", return_value={}
        ), patch(
            "hey.cli.ping_llm", return_value={"ok": True, "elapsed_ms": 312, "model": "llama3", "error": None}
        ) as ping_llm:
            with self.assertRaises(SystemExit) as cm:
                cli.main()

        self.assertEqual(cm.exception.code, 0)
        self.assertIn("Endpoint: http://localhost:8080/v1/chat/completions", stdout.getvalue())
        self.assertIn("OK  312ms  model=llama3", stdout.getvalue())
        ping_llm.assert_called_once_with("http://localhost:8080/v1/chat/completions", "local")

    def test_main_test_flag_prints_failure_and_exits(self) -> None:
        stdout = FakeStream(is_tty=False)
        stderr = FakeStream(is_tty=False)

        with patch("sys.argv", ["hey", "--test"]), patch("sys.stdout", stdout), patch("sys.stderr", stderr), patch(
            "hey.cli.load_config", return_value={}
        ), patch(
            "hey.cli.ping_llm",
            return_value={"ok": False, "elapsed_ms": None, "model": None, "error": "Could not connect"},
        ):
            with self.assertRaises(SystemExit) as cm:
                cli.main()

        self.assertEqual(cm.exception.code, 1)
        self.assertIn("FAIL  Could not connect", stderr.getvalue())

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

    def test_main_uses_parsed_command_for_fenced_single_option_response(self) -> None:
        # Fenced numbered output must still be parsed as a single selectable
        # option so main() does not fall back to extract_command(response) and
        # save the literal "1. ls -la" line.
        stdout = FakeStream(is_tty=False)
        stderr = FakeStream(is_tty=False)
        stdin = FakeStream(is_tty=False)

        with patch("sys.argv", ["hey", "--no-run", "list files"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("hey.cli.detect_shell", return_value="zsh"), patch(
            "hey.cli.detect_platform", return_value="macOS"
        ), patch(
            "hey.cli.query_llm", return_value="```bash\n1. ls -la\nLists all files.\n```"
        ), patch(
            "hey.cli.save_history"
        ) as save_history:
            cli.main()

        save_history.assert_called_once_with("list files", "ls -la", "zsh")
        self.assertEqual(stderr.getvalue(), "")

    def test_main_run_flag_still_prompts_on_multiple_options(self) -> None:
        # --run does not skip the selection prompt when the model returns
        # multiple options — silently picking an arbitrary option would be
        # surprising.  The user must still choose, then the selected command
        # is executed without the subsequent "Run it?" prompt.
        # Note: side_effect supplies only one input ("1" for the selection
        # prompt).  The "Run it?" prompt is never shown because --run bypasses
        # it via the args.run_now branch in main().
        stdout = FakeStream(is_tty=True)
        stderr = FakeStream(is_tty=True)
        stdin = FakeStream(is_tty=True)

        with patch("sys.argv", ["hey", "--run", "ambiguous query"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("builtins.input", side_effect=["1"]), patch(
            "hey.cli.detect_shell", return_value="zsh"
        ), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm", return_value="1. cat /etc/arch-release\n2. uname -r"
        ), patch("hey.cli.save_history"), patch(
            "hey.cli.shutil.which", return_value="/bin/cat"
        ), patch("hey.cli.run_command", return_value=0) as run_command:
            cli.main()

        run_command.assert_called_once_with("cat /etc/arch-release", "zsh")
        self.assertIn("Selected: cat /etc/arch-release", stdout.getvalue())

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

    def test_main_run_flag_executes_command_without_prompt(self) -> None:
        stdout = FakeStream(is_tty=False)
        stderr = FakeStream(is_tty=False)
        stdin = FakeStream(is_tty=False)

        with patch("sys.argv", ["hey", "--run", "list files"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("hey.cli.detect_shell", return_value="zsh"), patch(
            "hey.cli.detect_platform", return_value="macOS"
        ), patch("hey.cli.query_llm", return_value="ls -la"), patch("hey.cli.save_history"), patch(
            "hey.cli.shutil.which", return_value="/bin/ls"
        ), patch("hey.cli.run_command", return_value=0) as run_command:
            cli.main()

        run_command.assert_called_once_with("ls -la", "zsh")

    def test_main_copy_flag_reports_success(self) -> None:
        stdout = FakeStream(is_tty=False)
        stderr = FakeStream(is_tty=False)
        stdin = FakeStream(is_tty=False)

        with patch("sys.argv", ["hey", "--copy", "--no-run", "list files"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("hey.cli.detect_shell", return_value="zsh"), patch(
            "hey.cli.detect_platform", return_value="macOS"
        ), patch("hey.cli.query_llm", return_value="ls -la"), patch("hey.cli.save_history"), patch(
            "hey.cli.copy_to_clipboard", return_value=True
        ) as copy_to_clipboard:
            cli.main()

        copy_to_clipboard.assert_called_once_with("ls -la")
        self.assertIn("Copied to clipboard.", stdout.getvalue())

    def test_main_copy_flag_reports_failure(self) -> None:
        stdout = FakeStream(is_tty=False)
        stderr = FakeStream(is_tty=False)
        stdin = FakeStream(is_tty=False)

        with patch("sys.argv", ["hey", "--copy", "--no-run", "list files"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("hey.cli.detect_shell", return_value="zsh"), patch(
            "hey.cli.detect_platform", return_value="macOS"
        ), patch("hey.cli.query_llm", return_value="ls -la"), patch("hey.cli.save_history"), patch(
            "hey.cli.copy_to_clipboard", return_value=False
        ):
            cli.main()

        self.assertIn("Could not copy to clipboard.", stderr.getvalue())

    def test_main_prints_error_and_exits_on_llm_exception(self) -> None:
        stderr = FakeStream(is_tty=False)
        stdin = FakeStream(is_tty=False)

        with patch("sys.argv", ["hey", "list files"]), patch("sys.stdin", stdin), patch(
            "sys.stderr", stderr
        ), patch("hey.cli.detect_shell", return_value="zsh"), patch(
            "hey.cli.detect_platform", return_value="macOS"
        ), patch("hey.cli.query_llm", side_effect=RuntimeError("connection refused")):
            with self.assertRaises(SystemExit) as cm:
                cli.main()

        self.assertEqual(cm.exception.code, 1)
        self.assertIn("Error: connection refused", stderr.getvalue())

    def test_main_exits_cleanly_when_option_selection_cancelled(self) -> None:
        stdout = FakeStream(is_tty=True)
        stderr = FakeStream(is_tty=True)
        stdin = FakeStream(is_tty=True)

        with patch("sys.argv", ["hey", "ambiguous query"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("builtins.input", return_value=""), patch(
            "hey.cli.detect_shell", return_value="zsh"
        ), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm", return_value="1. cat /etc/arch-release\n2. uname -r"
        ), patch("hey.cli.save_history") as save_history:
            with self.assertRaises(SystemExit) as cm:
                cli.main()

        self.assertEqual(cm.exception.code, 0)
        self.assertIn("No option selected.", stdout.getvalue())
        save_history.assert_not_called()

    def test_main_interactive_yes_executes_command(self) -> None:
        stdout = FakeStream(is_tty=True)
        stderr = FakeStream(is_tty=True)
        stdin = FakeStream(is_tty=True)

        with patch("sys.argv", ["hey", "list files"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("builtins.input", return_value="y"), patch(
            "hey.cli.detect_shell", return_value="zsh"
        ), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm", return_value="ls -la"
        ), patch("hey.cli.save_history"), patch(
            "hey.cli.shutil.which", return_value="/bin/ls"
        ), patch("hey.cli.run_command", return_value=0) as run_command:
            cli.main()

        run_command.assert_called_once_with("ls -la", "zsh")

    def test_main_interactive_keyboard_interrupt_on_run_prompt_exits_cleanly(self) -> None:
        stdout = FakeStream(is_tty=True)
        stderr = FakeStream(is_tty=True)
        stdin = FakeStream(is_tty=True)

        with patch("sys.argv", ["hey", "list files"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("builtins.input", side_effect=KeyboardInterrupt), patch(
            "hey.cli.detect_shell", return_value="zsh"
        ), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm", return_value="ls -la"
        ), patch("hey.cli.save_history"):
            with self.assertRaises(SystemExit) as cm:
                cli.main()

        self.assertEqual(cm.exception.code, 0)

    def test_main_run_skips_execution_when_command_not_found_and_non_tty(self) -> None:
        # When the suggested command is not on PATH and stdout is not a TTY,
        # run_and_handle returns without calling run_command or offer_install.
        stdout = FakeStream(is_tty=False)
        stderr = FakeStream(is_tty=False)
        stdin = FakeStream(is_tty=False)

        with patch("sys.argv", ["hey", "--run", "list files"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("hey.cli.detect_shell", return_value="zsh"), patch(
            "hey.cli.detect_platform", return_value="macOS"
        ), patch("hey.cli.query_llm", return_value="missing-tool --flag"), patch(
            "hey.cli.save_history"
        ), patch("hey.cli.shutil.which", return_value=None), patch(
            "hey.cli.run_command"
        ) as run_command:
            cli.main()

        run_command.assert_not_called()

    def test_main_run_offers_install_when_command_not_found_and_tty(self) -> None:
        # When the suggested command is not on PATH and stdout IS a TTY,
        # offer_install is invoked; user declines, so run_command is never called.
        stdout = FakeStream(is_tty=True)
        stderr = FakeStream(is_tty=True)
        stdin = FakeStream(is_tty=True)

        with patch("sys.argv", ["hey", "--run", "list files"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("builtins.input", return_value="n"), patch(
            "hey.cli.detect_shell", return_value="zsh"
        ), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm", return_value="missing-tool --flag"
        ), patch("hey.cli.save_history"), patch("hey.cli.shutil.which", return_value=None), patch(
            "hey.cli.run_command"
        ) as run_command:
            cli.main()

        run_command.assert_not_called()

    def test_main_offer_install_runs_install_command_on_yes(self) -> None:
        # User says "y" to install offer, then "y" to run the install command.
        stdout = FakeStream(is_tty=True)
        stderr = FakeStream(is_tty=True)
        stdin = FakeStream(is_tty=True)

        install_response = "brew install missing-tool\nInstalls missing-tool via Homebrew."

        with patch("sys.argv", ["hey", "--run", "do something"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("builtins.input", side_effect=["y", "y"]), patch(
            "hey.cli.detect_shell", return_value="zsh"
        ), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm", side_effect=["missing-tool --flag", install_response]
        ), patch("hey.cli.save_history"), patch(
            "hey.cli.shutil.which", return_value=None
        ), patch("hey.cli.run_command", return_value=0) as run_command:
            cli.main()

        # run_command is called once: for the install command
        run_command.assert_called_once_with("brew install missing-tool", "zsh")

    def test_main_offer_install_declines_run_on_no(self) -> None:
        # User says "y" to install offer but "n" to running the install command.
        stdout = FakeStream(is_tty=True)
        stderr = FakeStream(is_tty=True)
        stdin = FakeStream(is_tty=True)

        install_response = "brew install missing-tool"

        with patch("sys.argv", ["hey", "--run", "do something"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("builtins.input", side_effect=["y", "n"]), patch(
            "hey.cli.detect_shell", return_value="zsh"
        ), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm", side_effect=["missing-tool --flag", install_response]
        ), patch("hey.cli.save_history"), patch("hey.cli.shutil.which", return_value=None), patch(
            "hey.cli.run_command"
        ) as run_command:
            cli.main()

        run_command.assert_not_called()

    def test_main_offer_install_on_exit_code_127(self) -> None:
        # When the command is found but exits with code 127, offer_install fires.
        # User declines, so no install query is made.
        stdout = FakeStream(is_tty=True)
        stderr = FakeStream(is_tty=True)
        stdin = FakeStream(is_tty=True)

        with patch("sys.argv", ["hey", "--run", "list files"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("builtins.input", return_value="n"), patch(
            "hey.cli.detect_shell", return_value="zsh"
        ), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm", return_value="ls -la"
        ), patch("hey.cli.save_history"), patch(
            "hey.cli.shutil.which", return_value="/bin/ls"
        ), patch("hey.cli.run_command", return_value=127):
            cli.main()

        # Completed without error; offer_install was invoked but user declined.
        self.assertEqual(stderr.getvalue(), "")

    def test_main_offer_install_eof_returns_silently(self) -> None:
        # EOFError on the offer_install prompt must not propagate.
        stdout = FakeStream(is_tty=True)
        stderr = FakeStream(is_tty=True)
        stdin = FakeStream(is_tty=True)

        with patch("sys.argv", ["hey", "--run", "list files"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("builtins.input", side_effect=EOFError), patch(
            "hey.cli.detect_shell", return_value="zsh"
        ), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm", return_value="missing-tool --flag"
        ), patch("hey.cli.save_history"), patch("hey.cli.shutil.which", return_value=None), patch(
            "hey.cli.run_command"
        ) as run_command:
            cli.main()

        run_command.assert_not_called()

    def test_main_offer_install_prints_error_on_llm_failure(self) -> None:
        # If query_llm raises inside offer_install, the error is printed and the
        # function returns without crashing.
        stdout = FakeStream(is_tty=True)
        stderr = FakeStream(is_tty=True)
        stdin = FakeStream(is_tty=True)

        with patch("sys.argv", ["hey", "--run", "do something"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch("builtins.input", return_value="y"), patch(
            "hey.cli.detect_shell", return_value="zsh"
        ), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm",
            side_effect=["missing-tool --flag", RuntimeError("install query failed")],
        ), patch("hey.cli.save_history"), patch("hey.cli.shutil.which", return_value=None), patch(
            "hey.cli.run_command"
        ) as run_command:
            cli.main()

        run_command.assert_not_called()
        self.assertIn("Error: install query failed", stderr.getvalue())

    def test_main_offer_install_eof_on_run_prompt_returns_silently(self) -> None:
        # EOFError on the "Run install command?" prompt must not propagate.
        stdout = FakeStream(is_tty=True)
        stderr = FakeStream(is_tty=True)
        stdin = FakeStream(is_tty=True)

        install_response = "brew install missing-tool"

        with patch("sys.argv", ["hey", "--run", "do something"]), patch("sys.stdin", stdin), patch(
            "sys.stdout", stdout
        ), patch("sys.stderr", stderr), patch(
            "builtins.input", side_effect=["y", EOFError()]
        ), patch(
            "hey.cli.detect_shell", return_value="zsh"
        ), patch("hey.cli.detect_platform", return_value="macOS"), patch(
            "hey.cli.query_llm", side_effect=["missing-tool --flag", install_response]
        ), patch("hey.cli.save_history"), patch("hey.cli.shutil.which", return_value=None), patch(
            "hey.cli.run_command"
        ) as run_command:
            cli.main()

        run_command.assert_not_called()


class TestMainModule(unittest.TestCase):
    def test_main_module_entry_point_calls_cli_main(self) -> None:
        import runpy

        with patch("hey.cli.main") as mock_main:
            runpy.run_module("hey", run_name="__main__")

        mock_main.assert_called_once()


if __name__ == "__main__":
    unittest.main()
