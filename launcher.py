import os
import platform
import subprocess

import recent


def launch(path: str, title: str = "") -> None:
    """Launch a game executable, shortcut, or steam:// URL."""
    system = platform.system()
    if system == "Windows":
        os.startfile(path)
    elif system == "Darwin":
        subprocess.run(["open", path], check=False)
    else:
        subprocess.run(["xdg-open", path], check=False)
    try:
        recent.record_play(path, title)
    except Exception:
        pass


def open_location(path: str) -> None:
    """Open the directory containing the game in the file manager.

    For .lnk shortcuts on Windows, resolves the target first so the
    game's actual install folder is opened (not the shortcut's folder).
    """
    if "://" in path:
        return  # No filesystem location for steam:// and similar URLs

    # Resolve .lnk shortcut to its real target on Windows
    if path.lower().endswith(".lnk") and platform.system() == "Windows":
        try:
            result = subprocess.run(
                [
                    "powershell", "-command",
                    f'(New-Object -ComObject WScript.Shell).CreateShortcut("{path}").TargetPath',
                ],
                capture_output=True, text=True, timeout=5,
            )
            target = result.stdout.strip()
            if target and os.path.exists(target):
                path = target
        except Exception:
            pass

    folder = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(folder):
        return

    system = platform.system()
    if system == "Windows":
        subprocess.Popen(["explorer", folder])
    elif system == "Darwin":
        subprocess.run(["open", folder], check=False)
    else:
        subprocess.run(["xdg-open", folder], check=False)
