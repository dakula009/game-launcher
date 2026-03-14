# Recent Tab — Design Spec
_Date: 2026-03-13_

## Overview

Add a "Recent" tab pinned at index 1 (after Favorites, before regular tabs) that shows the 10 most recently played games, ordered by last played date descending. Each card shows a play count and a human-readable last-played date. The tab and its cards are read-only — no rename, delete, reorder, or game removal.

---

## 1. Data Layer — `recent.py`

New module at `recent.py`.

**Storage:** `%APPDATA%\MyGameHub\recent.json` — a flat list of records:

```json
[
  {"path": "steam://rungameid/377160", "title": "Fallout 4", "last_played": "2026-03-13T14:32:00", "play_count": 7},
  ...
]
```

Note: `title` is stored so that cards for games deleted from the library can still display a meaningful name.

**API:**

- `record_play(path: str, title: str)` — upserts by path: increments `play_count`, updates `title` (in case the game was renamed), sets `last_played` to `datetime.now().isoformat()`. Trims stored list to 50 records (sorted by `last_played` desc) after each write. Trimmed records are permanently removed — there is no merge-on-re-add.
- `load_recent() -> list[dict]` — returns top 10 records sorted by `last_played` descending. Each dict has `path`, `title`, `last_played`, `play_count`.

**Persistence:** Cross-session. History is recorded regardless of whether the game is still in the library.

---

## 2. Tab Behavior

- **Label:** `"Recent"` (plain text, no icon)
- **Position:** `QTabWidget` index 1, always after Favorites (index 0), always before regular tabs (index 2..n)
- **Index offset shift:** `self._tabs[i]` maps to `QTabWidget` index `i + 2` (was `i + 1`)
- **Protection:** Cannot be renamed, deleted, or reordered
- **Grid:** Reuses `GameGrid(is_favorites=True)` — already disables drag-drop, add-game context menu, and remove option
- **Build on startup:** `MainWindow` calls `recent.load_recent()`, resolves each path to its `GameItem` from the loaded library. If a path is not found in any tab, a minimal `GameItem(title=record["title"], path=record["path"])` is constructed for display
- **Stale within session:** The Recent tab is built once at startup and does not live-refresh during a session. A game launched mid-session will appear in Recent only after the next app start. This is by design.

---

## 3. Card Display

Each `GameCard` in the Recent tab receives `last_played` and `play_count` metadata. The card is constructed normally but with an extra display line.

### Default layout (icon + title)
A faded line added below the title label:
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

### `recent.py` (new)
See Section 1.

### `launcher.py`
`launch(path, title)` — add `title` parameter, call `recent.record_play(path, title)` after opening the game. Import `recent` at the top of `launcher.py`. Failure is silently swallowed — a failed record must never block the game from launching. All call sites in `widgets.py` pass `item.title` alongside `item.path`.

### `widgets.py` — `MainWindow`

**New fields:**
- `self._recent_tab: GameTab`
- `self._recent_grid: GameGrid`

**`_populate_tabs()`:** Insert Recent at index 1, shifting all regular tabs to index 2+.

**Index offset — all `real_idx` derivations change from `idx - 1` to `idx - 2`:**
- `_on_tabs_reordered`: `real_from = from_idx - 2`, `real_to = to_idx - 2`
- `_rename_tab`: `real_idx = idx - 2`
- `_delete_tab_at`: `real_idx = idx - 2`
- `_add_game_via_dialog`: `real_idx = idx - 2`
- `_on_search_result_selected`: `real_idx = tab_widget_idx - 2`

**Search — emit offset:** In `_on_search_text_changed`, results emit `tab_widget_idx = i + 2` (was `i + 1`).

**Protection guards — all expand from `idx == 0` to `idx in (0, 1)`:**
- `_rename_tab`
- `_delete_tab_at`
- `_on_wrap_tab_right_click`: guard changes from `0 < idx < plus` to `1 < idx < plus`
- `WrapTabBar._finish_drag`: guard changes from `target > 0 and target < plus` to `target > 1 and src > 1 and target < plus`

**Grid iteration — add `_recent_grid` to all three sites:**
- `toggle_favorite`: iterate `[self._favorites_grid, self._recent_grid] + self._grids`
- `_sync_card_titles`: same
- `_refresh_card_everywhere`: same

### `models.py` / `storage.py`
No changes required.

---

## 5. Files Changed

| File | Change |
|---|---|
| `recent.py` | **New** — data layer |
| `launcher.py` | Add `title` param; call `recent.record_play(path, title)` |
| `widgets.py` | Recent tab UI, card display, index offsets, guards, grid iteration |
| `CLAUDE.md` | Document new tab and module |

---

## 6. Out of Scope

- Live refresh of Recent tab during a session
- Clearing/resetting play history via UI
- Per-game play history timeline
- Visual distinction between active vs. deleted-from-library games in Recent
