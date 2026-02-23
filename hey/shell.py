import os
import platform
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


def detect_platform() -> str:
    system = platform.system()
    if system == "Darwin":
        if shutil.which("brew"):
            return "macOS (use Homebrew for installations)"
        return "macOS"
    if system == "Windows":
        return "Windows"
    # Linux — detect package manager
    if shutil.which("apt") or shutil.which("apt-get"):
        return "Linux (Debian/Ubuntu, use apt)"
    if shutil.which("dnf"):
        return "Linux (Fedora/RHEL, use dnf)"
    if shutil.which("pacman"):
        return "Linux (Arch, use pacman)"
    if shutil.which("zypper"):
        return "Linux (openSUSE, use zypper)"
    return "Linux"


def run_command(command: str, shell: str) -> int:
    executable = shutil.which(shell)
    return subprocess.call(command, shell=True, executable=executable)
