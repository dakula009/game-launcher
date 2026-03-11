import json
from pathlib import Path
from typing import List

from models import GameTab

DATA_FILE = Path(__file__).parent / "data" / "library.json"

DEFAULT_TAB_NAMES = ["RTS", "RPG", "FPS", "Other"]


def load() -> List[GameTab]:
    if not DATA_FILE.exists():
        return [GameTab(name=name) for name in DEFAULT_TAB_NAMES]
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [GameTab.from_dict(t) for t in data.get("tabs", [])]


def save(tabs: List[GameTab]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump({"tabs": [t.to_dict() for t in tabs]}, f, indent=2)
