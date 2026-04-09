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


# Command portion must start with a letter, digit, or a path/sigil character
# (/  .  $  ~  !  {).  Uppercase is included for PowerShell-style cmdlets
# (e.g. Get-Process, Set-Location).  Hyphens are still excluded so flag
# descriptions ("-l shows long format") are never promoted to option headers.
# Prose verbs like "Shows all files" are filtered by _looks_like_command via
# the _PROSE_VERBS blocklist (case-insensitive), not by this regex.
NUMBERED_OPTION_RE = re.compile(r"^\s*(\d+)\.\s+([a-zA-Z0-9/.$~!{].*?)\s*$")


# Third-person-singular verb forms that LLMs commonly use in explanation text.
# None of these are plausible command names, so matching the first word of a
# numbered line against this set is a precise way to reject prose without
# producing false positives for real tool names that happen to end in 's'
# (e.g. "rails", "nexus", "travis", "terminus").
_PROSE_VERBS = frozenset({
    "adds", "allows", "checks", "closes", "connects", "copies", "creates",
    "deletes", "disables", "disconnects", "displays", "enables", "excludes",
    "executes", "filters", "finds", "generates", "gives", "includes",
    "installs", "lists", "loads", "makes", "moves", "opens", "outputs",
    "parses", "prevents", "prints", "provides", "reads", "receives",
    "removes", "renames", "requires", "returns", "runs", "saves", "searches",
    "sends", "sets", "shows", "sorts", "starts", "stops", "takes",
    "uninstalls", "updates", "writes",
})


def _looks_like_command(text: str) -> bool:
    """Return True if text resembles a shell command rather than prose.

    A single bare word is always accepted (e.g. "pwd").  For multi-word text
    there are two acceptance paths:

    1. Shell-token path: at least one argument (word after the first) contains
       a flag (-x/--flag), a path (/dir, ./rel, ~/home), a sigil ($VAR), a
       glob (*), a quoted string, or a dotted filename (file.txt, script.sh).
       Accepts "ls -la", "find . -name '*.txt'", "python3 script.py".

    2. Subcommand path: no shell token is present but the first word is not a
       known prose verb.  Accepts "git status", "kubectl get pods", "rails
       server" while rejecting "shows hidden files", "lists all files".
    """
    words = text.split()
    if len(words) == 1:
        return True
    if any(
        w[0] in "-/.$~*\"'"
        or "/" in w
        or (len(w) > 1 and "." in w[1:])
        for w in words[1:]
    ):
        return True
    return words[0].lower() not in _PROSE_VERBS


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

    # Only treat as numbered options if the first non-empty line is "1. <command>".
    # This prevents --explain responses (plain command followed by numbered
    # explanation lines) from being misclassified as ambiguous options.
    first_content = next((l for l in lines if l.strip()), "")
    first_match = NUMBERED_OPTION_RE.match(first_content)
    if not first_match or first_match.group(1) != "1" or not _looks_like_command(first_match.group(2)):
        return []

    options: list[dict[str, str]] = []
    current: Optional[dict[str, str]] = None
    current_body: list[str] = []
    next_expected = 1  # only accept strictly sequential option numbers

    for raw_line in lines:
        match = NUMBERED_OPTION_RE.match(raw_line)
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

    if not options:
        return []

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
