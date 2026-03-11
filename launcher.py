import os
import platform
import subprocess


def launch(path: str) -> None:
    """Launch a game executable or shortcut.

    On Windows, os.startfile handles both .exe and .lnk files.
    .lnk shortcut resolution only works correctly on Windows (shell feature).
    On Mac (dev only), uses 'open' for basic testing.
    """
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)
