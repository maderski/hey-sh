import platform
import subprocess


def copy_to_clipboard(text: str) -> bool:
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.run(
                ["pbcopy"],
                input=text.encode(),
                check=True,
            )
            return True

        if system == "Linux":
            # Try xclip first, then xsel
            for args in (
                ["xclip", "-selection", "clipboard"],
                ["xsel", "--clipboard", "--input"],
            ):
                try:
                    subprocess.run(args, input=text.encode(), check=True)
                    return True
                except (FileNotFoundError, subprocess.CalledProcessError):
                    continue
            return False

        if system == "Windows":
            subprocess.run(
                ["clip"],
                input=text.encode("utf-16"),
                check=True,
            )
            return True

    except (FileNotFoundError, subprocess.CalledProcessError):
        pass

    return False
