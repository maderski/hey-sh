import subprocess
import unittest
from unittest.mock import patch

from hey import clipboard


class TestClipboard(unittest.TestCase):
    def test_copy_to_clipboard_uses_pbcopy_on_macos(self) -> None:
        with patch("platform.system", return_value="Darwin"), patch("hey.clipboard.subprocess.run") as run_mock:
            self.assertTrue(clipboard.copy_to_clipboard("hello"))

        run_mock.assert_called_once_with(["pbcopy"], input=b"hello", check=True)

    def test_copy_to_clipboard_falls_back_to_xsel_on_linux(self) -> None:
        with patch("platform.system", return_value="Linux"), patch(
            "hey.clipboard.subprocess.run",
            side_effect=[FileNotFoundError(), None],
        ) as run_mock:
            self.assertTrue(clipboard.copy_to_clipboard("hello"))

        self.assertEqual(run_mock.call_count, 2)

    def test_copy_to_clipboard_returns_false_when_linux_tools_missing(self) -> None:
        with patch("platform.system", return_value="Linux"), patch(
            "hey.clipboard.subprocess.run",
            side_effect=FileNotFoundError(),
        ):
            self.assertFalse(clipboard.copy_to_clipboard("hello"))

    def test_copy_to_clipboard_uses_clip_on_windows(self) -> None:
        with patch("platform.system", return_value="Windows"), patch("hey.clipboard.subprocess.run") as run_mock:
            self.assertTrue(clipboard.copy_to_clipboard("hello"))

        run_mock.assert_called_once_with(["clip"], input="hello".encode("utf-16"), check=True)

    def test_copy_to_clipboard_returns_false_when_command_fails(self) -> None:
        with patch("platform.system", return_value="Darwin"), patch(
            "hey.clipboard.subprocess.run",
            side_effect=subprocess.CalledProcessError(1, "pbcopy"),
        ):
            self.assertFalse(clipboard.copy_to_clipboard("hello"))
