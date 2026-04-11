import argparse
import re
import shutil
import sys
from typing import Optional

from hey.clipboard import copy_to_clipboard
from hey.config import load_config, resolve_endpoint
from hey.history import print_history, save_history
from hey.llm import ping_llm, query_llm
from hey.shell import detect_platform, detect_shell, run_command


# Match any non-whitespace character as the start of the command portion so
# that valid shell starters beyond letters/digits are recognised — e.g. the
# test operator ([ -f file ]), subshells ((cd /tmp && ls)), the null command
# (: >file), and PowerShell cmdlets (Get-Process).  Content filtering
# (prose verbs, hyphen-initial flag descriptions) is handled entirely by
# _looks_like_command rather than by this regex.
_NUMBERED_OPTION_RE = re.compile(r"^\s*(\d+)\.\s+(\S.*?)\s*$")

# Characters whose presence in a word indicates a shell token rather than a
# plain-text prose word.  The prose-punctuation gate (gate 4 in
# _looks_like_command) skips any word that contains one of these so that
# shell constructs like awk '{print $1, $2}' or paths like /dir/.hidden are
# not incorrectly rejected because a token happens to end with , or ..
_SHELL_TOKEN_CHARS = frozenset("${}'\"/\\*~[]()<>|&;")


# Words that can open a natural-language sentence but can never be a shell
# command name.  Used (case-insensitively) as the fallback rejection gate in
# _looks_like_command so that explanation lines like "This command lists hidden
# files" or "The option shows output" are not promoted to option headers.
#
# Three categories:
#   • Third-person-singular verb forms LLMs use in explanation text.
#   • Imperative / bare-infinitive forms (base forms of the verbs above) that
#     open numbered explanation steps like "Add -a to include hidden files".
#     These must appear here so they are rejected BEFORE the shell-token check
#     can rescue them via a flag argument on the same line.
#   • English function words (articles, demonstratives, pronouns) that form a
#     closed, finite set and are never valid command names.  These cover
#     sentence starters like "This …", "The …", "An …", "It …" that the verb
#     list alone would miss.
#
# Policy for additions: a word belongs here only if it is provably absent from
# POSIX and common tool namespaces as a standalone first-token command, AND is
# commonly observed opening explanation sentences in LLM output.  Do not add
# words like "run", "get", "set", or "pass" — these are valid command names or
# subcommands that would cause false rejections.
_PROSE_STARTERS = frozenset({
    # Third-person singular verbs
    "adds", "allows", "checks", "closes", "connects", "copies", "creates",
    "deletes", "disables", "disconnects", "displays", "enables", "excludes",
    "executes", "filters", "finds", "generates", "gives", "includes",
    "installs", "lists", "loads", "makes", "moves", "opens", "outputs",
    "parses", "prevents", "prints", "provides", "reads", "receives",
    "removes", "renames", "requires", "returns", "runs", "saves", "searches",
    "sends", "sets", "shows", "sorts", "starts", "stops", "takes",
    "uninstalls", "updates", "writes",
    # Imperative / bare-infinitive forms used in explanation text.
    # Paired with their third-person singular forms above so that both
    # "Uses -a to include hidden files" and "Add -a to include hidden files"
    # are rejected before the shell-token check can rescue them.
    # Only base forms that are NOT standalone POSIX commands are listed here.
    "try", "tries", "use", "uses",
    "add",      # base of "adds";  not a standalone POSIX command
    "note",     # "Note that -v enables verbose" — not a command
    "include",  # "Include -r for recursive" — not a command
    "append",   # "Append --format=json for JSON" — not a command
    # Prepositions that open explanation clauses but are never command names
    # ("To include hidden files …", "By default …", "With the -a flag …")
    "to", "by", "with",
    # Articles
    "a", "an", "the",
    # Demonstratives
    "this", "that", "these", "those",
    # Pronouns that start explanation sentences but are never command names
    "it", "its",
})


def _looks_like_command(text: str) -> bool:
    """Return True if text resembles a shell command rather than prose.

    Checks are applied in this order so that no later heuristic can override
    an earlier rejection:

    1. Single bare word → always a command (e.g. "pwd").
    2. Hyphen-initial multi-word text → flag description, never a command
       (e.g. "-l shows long format").
    3. First word in _PROSE_STARTERS → explanation prose, never a command.
       This gate must come before the shell-token check so that lines like
       "Uses -a to include hidden files" or "Adds -r for recursion" are
       rejected even though they contain flag-like tokens.
    4. Prose-punctuation gate → any plain-text word ending with a comma or a
       sentence-ending period (e.g. "files," or "add -a.") signals an
       explanation clause; reject before the shell-token check so that
       flag-like tokens inside prose ("…, add -a.") don't rescue it.
       Words that contain a shell metacharacter (see _SHELL_TOKEN_CHARS) are
       exempted so that tokens like $1, inside awk '{print $1, $2}' or
       paths ending with . do not trigger a false rejection.
       The bare "." token is also excluded from the period check.
    5. Shell-token path → a remaining argument (words[1:]) starts with a
       flag, path, sigil, glob, quote, or shell operator (>, <, |, &, ;),
       or contains an embedded / or a mid-word dot; accept as a command.
       Note: words[0] is not re-examined here; its path/hyphen signals are
       handled in gate 6 to avoid double-checking after gates 2–4.
    6. Subcommand path → no shell tokens but ≤ 4 words survived all
       rejection gates; accept when the first token is:
       • lowercase (e.g. "git status", "kubectl get pods")
       • a path containing / (e.g. "/usr/bin/kubectl get pods", "./run.sh")
       • a hyphenated tool name (e.g. "docker-compose up")
       • the first of exactly 2 words, allowing Title Case tool+subcommand
         pairs such as "Git status" or "Docker ps".
       Longer all-prose phrases (3+ words, no shell tokens, no path) are
       rejected because genuine subcommand invocations are almost always short.
       Known limitation: 2-word Title Case phrases whose first word is not
       in _PROSE_STARTERS (e.g. "Show output", "Enable debug") are accepted
       here because they are indistinguishable from "Git status" without a
       dictionary.  In practice these are uncommon in option headers.
    """
    words = text.split()
    if len(words) == 1:
        return True
    if words[0].startswith("-"):
        return False
    if words[0].lower() in _PROSE_STARTERS:
        return False
    if any(
        (w.endswith(",") or (w != "." and w.endswith(".")))
        and not any(c in _SHELL_TOKEN_CHARS for c in w)
        for w in words
    ):
        return False
    if any(
        w[0] in "-/.$~*\"'><|&;"
        or "/" in w
        or (len(w) > 1 and "." in w[1:])
        for w in words[1:]
    ):
        return True
    return len(words) <= 4 and (
        words[0][0].islower()
        or "/" in words[0]   # absolute (/usr/bin/cmd) or relative (./cmd) path
        or "-" in words[0]   # hyphenated tool name (e.g. docker-compose)
        or len(words) == 2   # two-word Title Case tool+subcommand (e.g. Git status)
    )


def extract_command(response: str) -> str:
    lines = response.splitlines()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Skip triple code fence markers
        if line.startswith("```"):
            continue
        # Strip surrounding single backticks (inline code)
        if line.startswith("`") and line.endswith("`") and len(line) > 2:
            line = line[1:-1]
        return line
    return lines[0].strip() if lines else response.strip()


def parse_response_options(response: str) -> list[dict[str, str]]:
    lines = response.splitlines()

    # Only treat as numbered options if the first non-empty, non-fence line is
    # "1. <command>".  This prevents --explain responses (plain command followed
    # by numbered explanation lines) from being misclassified as ambiguous options.
    first_content = next((line for line in lines if line.strip() and not line.strip().startswith("```")), "")
    first_match = _NUMBERED_OPTION_RE.match(first_content)
    if not first_match or first_match.group(1) != "1" or not _looks_like_command(first_match.group(2)):
        return []

    # Each option dict has three keys:
    #   "number"  – the option number as a string (e.g. "1")
    #   "command" – the extracted runnable command string
    #   "body"    – the full raw block starting with the "N. <command>" header
    #               line, followed by any explanation lines that belong to this
    #               option.  Preserved for display purposes (printed by main()
    #               before the selection prompt via the top-level print(response)).
    options: list[dict[str, str]] = []
    current: Optional[dict[str, str]] = None
    current_body: list[str] = []
    next_expected = 1  # only accept strictly sequential option numbers

    for raw_line in lines:
        if raw_line.strip().startswith("```"):
            continue
        match = _NUMBERED_OPTION_RE.match(raw_line)
        # Treat as a new option header only if the number is the next expected one.
        # Explanation lines that happen to start with a number (e.g. "1. -l flag")
        # are absorbed into the current option's body instead.
        if match and int(match.group(1)) == next_expected and _looks_like_command(match.group(2)):
            if current is not None:
                current["body"] = "\n".join(current_body).strip()
                options.append(current)
            current = {
                "number": match.group(1),
                "command": extract_command(match.group(2)),
            }
            current_body = [raw_line.rstrip()]
            next_expected += 1
            continue
        if current is not None:
            current_body.append(raw_line.rstrip())

    if current is not None:
        current["body"] = "\n".join(current_body).strip()
        options.append(current)

    return options


def select_option(options: list[dict[str, str]]) -> Optional[dict[str, str]]:
    prompt = f"\nChoose an option [1-{len(options)}] or press Enter to cancel: "
    attempts = 0
    while attempts < 3:
        try:
            answer = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        if not answer:
            return None
        if answer.isdigit():
            choice = int(answer)
            if 1 <= choice <= len(options):
                return options[choice - 1]
        print("Please enter a valid option number.")
        attempts += 1
    print("Too many invalid attempts.")
    return None


def main() -> None:
    config = load_config()
    default_endpoint = resolve_endpoint(config)
    default_model = config.get("model", "local")

    parser = argparse.ArgumentParser(
        prog="hey",
        description="Shell-native natural language CLI assistant",
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Natural language query",
    )
    parser.add_argument(
        "--explain", "-e",
        action="store_true",
        help="Append explanation after command",
    )
    parser.add_argument(
        "--run", "-r",
        action="store_true",
        dest="run_now",
        help="Execute the command without prompting",
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="Never prompt to run the command",
    )
    parser.add_argument(
        "--copy", "-c",
        action="store_true",
        help="Copy the command to clipboard",
    )
    parser.add_argument(
        "--history", "-H",
        action="store_true",
        help="Print recent history and exit",
    )
    parser.add_argument(
        "--history-n",
        type=int,
        default=20,
        metavar="N",
        help="Number of history entries to show (default: 20)",
    )
    parser.add_argument(
        "--endpoint",
        default=default_endpoint,
        metavar="URL",
        help=f"LLM endpoint URL (default: {default_endpoint})",
    )
    parser.add_argument(
        "--model",
        default=default_model,
        metavar="NAME",
        help=f"Model name sent in payload (default: {default_model})",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test the connection to the LLM endpoint and exit",
    )

    args = parser.parse_args()

    if args.test:
        print(f"Endpoint: {args.endpoint}")
        result = ping_llm(args.endpoint, args.model)
        if result["ok"]:
            print(f"OK  {result['elapsed_ms']}ms  model={result['model']}")
            sys.exit(0)
        else:
            print(f"FAIL  {result['error']}", file=sys.stderr)
            sys.exit(1)

    if args.history:
        print_history(args.history_n)
        sys.exit(0)

    stdin_piped = not sys.stdin.isatty()

    # Build query string
    query_parts = list(args.query)
    stdin_text = ""
    if stdin_piped:
        stdin_text = sys.stdin.read().strip()

    if stdin_piped and stdin_text:
        if query_parts:
            # Treat stdin as context appended to query
            full_query = " ".join(query_parts) + "\n" + stdin_text
        else:
            # Stdin IS the query
            full_query = stdin_text
    else:
        full_query = " ".join(query_parts)

    if not full_query.strip():
        parser.print_help()
        sys.exit(1)

    shell = detect_shell()
    os_platform = detect_platform()

    try:
        response = query_llm(
            prompt=full_query,
            explain=args.explain,
            shell=shell,
            platform=os_platform,
            endpoint=args.endpoint,
            model=args.model,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    options = parse_response_options(response)
    interactive = sys.stdin.isatty() and sys.stdout.isatty()

    print(response)

    if len(options) == 1:
        command = options[0]["command"]
    elif len(options) > 1:
        if not interactive:
            print(
                "Multiple command options need an interactive terminal. "
                "Rerun `hey` interactively or make the request more specific.",
                file=sys.stderr,
            )
            sys.exit(1)
        # --run does not skip the selection prompt when there are multiple
        # options: executing an arbitrary choice without user input would be
        # surprising.  The prompt is intentional even with --run.
        selected = select_option(options)
        if selected is None:
            print("No option selected.")
            sys.exit(0)
        command = selected["command"]
        print(f"\nSelected: {command}")
    else:
        command = extract_command(response)

    save_history(full_query, command, shell)

    if args.copy:
        ok = copy_to_clipboard(command)
        if ok:
            print("Copied to clipboard.")
        else:
            print("Could not copy to clipboard.", file=sys.stderr)

    def offer_install(cmd_name: str) -> None:
        try:
            answer = input(f"\n'{cmd_name}' not found. Ask LLM how to install it? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if answer not in ("y", "yes"):
            return
        try:
            install_response = query_llm(
                prompt=f"How do I install '{cmd_name}'?",
                explain=True,
                shell=shell,
                platform=os_platform,
                endpoint=args.endpoint,
                model=args.model,
            )
        except Exception as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return
        print(f"\n{install_response}")
        install_cmd = extract_command(install_response)
        try:
            run_answer = input("\nRun install command? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if run_answer in ("y", "yes"):
            run_command(install_cmd, shell)

    def run_and_handle(cmd: str) -> None:
        cmd_name = cmd.split()[0]
        if shutil.which(cmd_name) is None:
            if sys.stdout.isatty():
                offer_install(cmd_name)
            return
        exit_code = run_command(cmd, shell)
        if exit_code == 127 and sys.stdout.isatty():
            offer_install(cmd_name)

    # Run logic
    if args.run_now:
        run_and_handle(command)
    elif args.no_run:
        pass
    elif interactive and not stdin_piped:
        try:
            answer = input("\nRun it? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if answer in ("y", "yes"):
            run_and_handle(command)
