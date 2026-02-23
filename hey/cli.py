import argparse
import shutil
import sys

from hey.clipboard import copy_to_clipboard
from hey.config import load_config, resolve_endpoint
from hey.history import print_history, save_history
from hey.llm import ping_llm, query_llm
from hey.shell import detect_platform, detect_shell, run_command


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

    print(response)

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
    elif sys.stdout.isatty() and not stdin_piped:
        try:
            answer = input("\nRun it? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            sys.exit(0)
        if answer in ("y", "yes"):
            run_and_handle(command)
