import unittest
from unittest.mock import patch

from hey import shell


class TestShell(unittest.TestCase):
    def test_detect_shell_returns_known_shell_name(self) -> None:
        with patch.dict("os.environ", {"SHELL": "/bin/zsh"}, clear=True):
            self.assertEqual(shell.detect_shell(), "zsh")

    def test_detect_shell_falls_back_for_unknown_shell(self) -> None:
        with patch.dict("os.environ", {"SHELL": "/bin/fancysh"}, clear=True):
            self.assertEqual(shell.detect_shell(), "bash")

    def test_detect_platform_reports_macos_with_brew(self) -> None:
        with patch("platform.system", return_value="Darwin"), patch("hey.shell.shutil.which", return_value="/opt/homebrew/bin/brew"):
            self.assertEqual(shell.detect_platform(), "macOS (use Homebrew for installations)")

    def test_detect_platform_reports_linux_package_manager(self) -> None:
        def fake_which(name: str) -> str | None:
            if name == "apt":
                return "/usr/bin/apt"
            return None

        with patch("platform.system", return_value="Linux"), patch("hey.shell.shutil.which", side_effect=fake_which):
            self.assertEqual(shell.detect_platform(), "Linux (Debian/Ubuntu, use apt)")

    def test_detect_platform_reports_macos_without_brew(self) -> None:
        with patch("platform.system", return_value="Darwin"), patch("hey.shell.shutil.which", return_value=None):
            self.assertEqual(shell.detect_platform(), "macOS")

    def test_detect_platform_reports_windows(self) -> None:
        with patch("platform.system", return_value="Windows"):
            self.assertEqual(shell.detect_platform(), "Windows")

    def test_detect_platform_reports_linux_with_dnf(self) -> None:
        def fake_which(name: str) -> str | None:
            return "/usr/bin/dnf" if name == "dnf" else None

        with patch("platform.system", return_value="Linux"), patch("hey.shell.shutil.which", side_effect=fake_which):
            self.assertEqual(shell.detect_platform(), "Linux (Fedora/RHEL, use dnf)")

    def test_detect_platform_reports_linux_with_pacman(self) -> None:
        def fake_which(name: str) -> str | None:
            return "/usr/bin/pacman" if name == "pacman" else None

        with patch("platform.system", return_value="Linux"), patch("hey.shell.shutil.which", side_effect=fake_which):
            self.assertEqual(shell.detect_platform(), "Linux (Arch, use pacman)")

    def test_detect_platform_reports_linux_with_zypper(self) -> None:
        def fake_which(name: str) -> str | None:
            return "/usr/bin/zypper" if name == "zypper" else None

        with patch("platform.system", return_value="Linux"), patch("hey.shell.shutil.which", side_effect=fake_which):
            self.assertEqual(shell.detect_platform(), "Linux (openSUSE, use zypper)")

    def test_detect_platform_reports_generic_linux_when_no_package_manager(self) -> None:
        with patch("platform.system", return_value="Linux"), patch("hey.shell.shutil.which", return_value=None):
            self.assertEqual(shell.detect_platform(), "Linux")

    def test_run_command_uses_requested_shell_executable(self) -> None:
        with patch("hey.shell.shutil.which", return_value="/bin/zsh") as which_mock, patch(
            "hey.shell.subprocess.call", return_value=0
        ) as call_mock:
            exit_code = shell.run_command("echo hi", "zsh")

        self.assertEqual(exit_code, 0)
        which_mock.assert_called_once_with("zsh")
        call_mock.assert_called_once_with("echo hi", shell=True, executable="/bin/zsh")
