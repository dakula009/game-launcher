from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

_RECENT_PATH = Path(os.environ.get("APPDATA", Path.home())) / "MyGameHub" / "recent.json"
_MAX_STORED = 50
_MAX_DISPLAY = 10


def _load_all() -> list:
    try:
        if _RECENT_PATH.exists():
            return json.loads(_RECENT_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_all(records: list) -> None:
    try:
        _RECENT_PATH.parent.mkdir(parents=True, exist_ok=True)
        _RECENT_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")
    except Exception:
        pass


def record_play(path: str, title: str) -> None:
    """Record a play event. Upserts by path, trims to _MAX_STORED records."""
    records = _load_all()
    for r in records:
        if r["path"] == path:
            r["play_count"] += 1
            r["last_played"] = datetime.now().isoformat()
            r["title"] = title
            break
    else:
        records.append({
            "path": path,
            "title": title,
            "last_played": datetime.now().isoformat(),
            "play_count": 1,
        })
    records.sort(key=lambda r: r["last_played"], reverse=True)
    _save_all(records[:_MAX_STORED])


def remove_entry(path: str) -> None:
    """Remove a path from the recent history permanently."""
    records = _load_all()
    records = [r for r in records if r["path"] != path]
    _save_all(records)


def load_recent() -> list:
    """Return top 10 records sorted by last_played descending."""
    records = _load_all()
    records.sort(key=lambda r: r["last_played"], reverse=True)
    return records[:_MAX_DISPLAY]
