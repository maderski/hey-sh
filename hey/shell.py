import os
import shutil
import subprocess

KNOWN_SHELLS = {"bash", "zsh", "fish", "sh", "ksh", "dash", "tcsh", "csh"}


def detect_shell() -> str:
    shell_path = os.environ.get("SHELL", "")
    if shell_path:
        name = os.path.basename(shell_path)
        if name in KNOWN_SHELLS:
            return name
    return "bash"


def run_command(command: str, shell: str) -> int:
    executable = shutil.which(shell)
    return subprocess.call(command, shell=True, executable=executable)
