import json
import os
from pathlib import Path

_SETTINGS_PATH = Path(os.environ.get("APPDATA", Path.home())) / "MyGameHub" / "settings.json"


def load() -> dict:
    try:
        return json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(data: dict) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_rawg_key() -> str:
    return load().get("rawg_api_key", "")


def set_rawg_key(key: str) -> None:
    data = load()
    data["rawg_api_key"] = key
    save(data)
