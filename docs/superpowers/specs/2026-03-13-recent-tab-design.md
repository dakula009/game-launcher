# Recent Tab — Design Spec
_Date: 2026-03-13_

## Overview

Add a "Recent" tab pinned at index 1 (after Favorites, before regular tabs) that shows the 10 most recently played games, ordered by last played date descending. Each card shows a play count and a human-readable last-played date. The tab and its cards are read-only — no rename, delete, reorder, or game removal.

---

## 1. Data Layer — `recent.py`

New module at `/Users/ranli/game-launcher/recent.py`.

**Storage:** `%APPDATA%\MyGameHub\recent.json` — a flat list of records:

```json
[
  {"path": "steam://rungameid/377160", "last_played": "2026-03-13T14:32:00", "play_count": 7},
  ...
]
```

**API:**

- `record_play(path: str)` — upserts by path: increments `play_count`, sets `last_played` to `datetime.now().isoformat()`. Trims stored list to 50 records (sorted by `last_played` desc) so the file never grows unbounded.
- `load_recent() -> list[dict]` — returns top 10 records sorted by `last_played` descending. Each dict has `path`, `last_played`, `play_count`.

**Persistence:** Cross-session. All play history is recorded regardless of whether the game is still in the library.

---

## 2. Tab Behavior

- **Label:** `"Recent"` (plain text, no icon)
- **Position:** `QTabWidget` index 1, always after Favorites (index 0), always before regular tabs (index 2..n)
- **Index offset shift:** `self._tabs[i]` maps to `QTabWidget` index `i + 2` (was `i + 1`)
- **Protection:** Cannot be renamed, deleted, or reordered. All tab management guards expand from `idx == 0` to `idx in (0, 1)`
- **Grid:** Reuses `GameGrid(is_favorites=True)` — disables drag-drop, add-game context menu, and remove option
- **Build on startup:** `MainWindow` calls `recent.load_recent()`, resolves each path to its `GameItem` from the loaded library. If a game has been deleted from all tabs, a minimal `GameItem` is constructed from the stored path/title for display purposes
- **No live refresh:** The Recent tab rebuilds only on next app start — no need to update in real time during a session

---

## 3. Card Display

Each `GameCard` in the Recent tab receives `last_played` and `play_count` metadata. Display varies by layout:

### Default layout (icon + title)
A faded line is added below the title label:
```
Fallout 4
Today · 4×
```

### Cover art layout (full-bleed image)
Play info sits on the left side of the existing dark title overlay band:
```
[ Today · 4× ]         Fallout 4
```

### Date formatting
| Condition | Display |
|---|---|
| Same calendar day | `"Today"` |
| Previous calendar day | `"Yesterday"` |
| 2–7 days ago | `"3 days ago"` |
| Older, same year | `"Mar 5"` |
| Older, different year | `"Mar 5, 2025"` |

### Styling
- Color: `TEXT_SEC` (`#64748b`)
- Font size: `10px`
- Subtle — visible but not competing with the title

---

## 4. Integration Points

### `launcher.py`
`launch(path)` calls `recent.record_play(path)` after opening the game. Import is lazy (inside the function) to avoid circular imports. Failure is silently swallowed — a failed record must never block the game from launching.

### `MainWindow` (`widgets.py`)
- Add `_recent_tab: GameTab` and `_recent_grid: GameGrid` fields, mirroring `_favorites_tab` / `_favorites_grid`
- `_populate_tabs()` inserts Recent at index 1
- All `idx == 0` guards become `idx in (0, 1)` for rename/delete/reorder protection
- `_tabs[i]` offset changes from `i + 1` to `i + 2` throughout

### `models.py` / `storage.py`
No changes required. Recent history is fully independent of the game library.

---

## 5. Files Changed

| File | Change |
|---|---|
| `recent.py` | **New** — data layer |
| `launcher.py` | Call `recent.record_play(path)` in `launch()` |
| `widgets.py` | Recent tab UI, card display, index offset, guards |
| `CLAUDE.md` | Document new tab and module |

---

## 6. Out of Scope

- Live refresh of Recent tab during a session
- Clearing/resetting play history via UI
- Per-game play history timeline
- Showing games deleted from the library differently from active ones
