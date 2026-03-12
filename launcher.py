import os
import platform
import subprocess


def launch(path: str) -> None:
    """Launch a game executable, shortcut, or steam:// URL.

    steam:// protocol is handled natively by Windows via os.startfile.
    On Mac, 'open' forwards steam:// to the Steam app if installed.
    .lnk shortcut resolution only works correctly on Windows.
    """
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)
