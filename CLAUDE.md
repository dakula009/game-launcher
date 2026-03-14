# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
python main.py
```

Requires Python 3.10+ with PySide6 installed (`pip install PySide6`).

## Building for Windows distribution

On Windows, with the `py310` conda environment active:

```bat
build.bat
```

Output is `dist\MyGameHub\` — a folder containing `MyGameHub.exe` and all bundled DLLs. After PyInstaller finishes, `build.bat` copies Qt6 DLLs from the conda env into the dist folder to fix ordinal mismatch errors that occur with PySide6 in conda environments.

The PyInstaller spec is `my_game_hub.spec`. The Inno Setup script `installer.iss` can produce a full Windows installer from the dist folder, but is not part of the regular build workflow yet. Current app version is **1.4**.

To uninstall, run `uninstall.bat` — it removes `%APPDATA%\MyGameHub\` and the app folder after confirmation.

## Architecture

The app is a PySide6 game launcher with 7 source files:

- **`models.py`** — Pure dataclasses: `GameItem` (title, path, icon_path, favorited, use_icon, artwork_path) and `GameTab` (name, list of games). Both have `to_dict`/`from_dict` for JSON serialization. `use_icon=True` forces the filesystem icon instead of fetched art; `artwork_path=""` means no search attempted, `"none"` means searched but found nothing.
- **`storage.py`** — Reads/writes `%APPDATA%\MyGameHub\library.json`. Saves only regular tabs; the Favorites tab is not persisted — it is rebuilt at load time from `GameItem.favorited` flags. On first run, initialises four default tabs: `["RTS", "RPG", "FPS", "Other"]`.
- **`settings.py`** — Reads/writes `%APPDATA%\MyGameHub\settings.json`. Provides `get_rawg_key()` / `set_rawg_key(key)` for the RAWG API key used by non-Steam artwork search.
- **`recent.py`** — Reads/writes `%APPDATA%\MyGameHub\recent.json`. Provides `record_play(path, title)` (called by `launcher.launch()`) and `load_recent()` (returns top 10 records sorted by `last_played` desc). Stores up to 50 records; trims oldest on overflow. Each record: `{path, title, last_played, play_count}`.
- **`launcher.py`** — `launch(path)` opens a game via `os.startfile` / `open` / `xdg-open`. `open_location(path)` opens the game's containing folder, resolving `.lnk` shortcuts on Windows via PowerShell before opening.
- **`main.py`** — Entry point. Creates `QApplication`, sets the window icon from `gamehub.ico`, and starts `MainWindow`.
- **`widgets.py`** — All UI. Key classes:
  - `FlowLayout` — custom `QLayout` subclass that places items left-to-right and wraps to the next row when width is exceeded. Used by `WrapTabBar`. Each row is horizontally centered.
  - `WrapTabBar` — custom tab bar widget using `FlowLayout` of `QPushButton`s. Replaces the native `QTabBar` (which is hidden). Supports drag-to-reorder via event filter. Emits `tab_clicked`, `tab_right_clicked`, `tab_reordered`.
  - `SearchPopup` — frameless `QListWidget` with `WA_ShowWithoutActivating` so it never steals keyboard focus. Shown below the search bar as the user types. Dismissed via an app-level event filter in `MainWindow` when the user clicks outside it.
  - `AddGameCard` — dashed-border `+` placeholder card shown at the end of every regular tab grid. Clicking it opens the add-game dialog.
  - `StarWidget` — custom `QWidget` that draws a rounded 5-pointed star via `QPainterPath` with bezier-curved tips (T=0.3 factor). Gold filled when favorited, white outline when not. Used inside `GameCard` (18×18) and rendered to a `QPixmap` via `_make_star_pixmap()` for the Favorites tab button icon.
  - `GameCard` — fixed 130×130 `QFrame`. `StarWidget` sits at the top-right. Green play overlay appears on hover. Clicking the card body launches the game; dragging reorders within the grid. Has two distinct UI layouts: **default** (icon + title label, used when no art) and **cover art** (full-bleed image + bottom title overlay). `_switch_to_cover_layout()` transitions from default to cover art dynamically. Cover art is rendered with 18px rounded corners via `_round_pixmap()` (transparent corner pixels + `setAutoFillBackground(False)` on the label). The title overlay at the bottom has matching `border-bottom-left/right-radius: 18px`. Icon fallback: tries `icon_path`, then `.lnk` target, then game path; shows 🎮 emoji if nothing resolves. `_resolve_lnk_target()` binary-parses `.lnk` files to extract the real exe path (avoids shortcut arrow in icon), with results cached in `_lnk_target_cache`. `.url` files are parsed by `_parse_url_file()` to extract `URL=` and `IconFile=` entries.
  - `GameGrid` — `QScrollArea` containing a `QGridLayout` that reflows cards on resize. `is_favorites=True` disables drag-and-drop and the "Add Game" context menu. Always appends `AddGameCard` placeholder last.
  - `MainWindow` — owns `self._tabs` (regular `GameTab` list) and `self._grids` (corresponding `GameGrid` list), plus separate `self._favorites_tab` / `self._favorites_grid` and `self._recent_tab` / `self._recent_grid`. The Favorites tab is always at `QTabWidget` index 0; Recent is always at index 1; regular tabs are at index `2..n`; the `＋` pseudo-tab is always last. `self._tabs[i]` maps to `QTabWidget` index `i + 2`.

## Game artwork

Two sources depending on game type:

- **Steam games** (path starts with `steam://rungameid/`) — art is auto-fetched from Steam's CDN (`cdn.akamai.steamstatic.com/steam/apps/{id}/library_600x900.jpg`) via `ArtworkDownloader` (a `QThread`). Triggered automatically when the card is built. Can be cleared via right-click → "Clear artwork" (sets `item.use_icon = True`).
- **Non-Steam games** — art is fetched from the RAWG API (`rawg.io`) via `NonSteamArtworkDownloader` (a `QThread`). Requires a RAWG API key set in Settings. Only triggered manually via right-click → "Search for artwork". Title is cleaned of edition suffixes before querying (`_clean_search_title`). Result path stored in `item.artwork_path`; `"none"` means search ran but found nothing.

Artwork is cached locally in `%APPDATA%\MyGameHub\artwork\`. Steam files are named `{app_id}.jpg`; non-Steam files are named `ns_{md5(title)}.jpg`. The `_round_pixmap()` helper clips all fetched art to 18px rounded corners before display.

## Key conventions

- **Tab index offset**: `self._tabs[i]` maps to `self._tab_widget` index `i + 2`. Any code touching `currentIndex()` must handle index 0 as Favorites, index 1 as Recent, and `_plus_tab_idx()` as the `＋` pseudo-tab separately.
- **`＋` pseudo-tab**: Always the last `QTabWidget` index. `_on_tab_changed` intercepts clicks on it via `blockSignals` + snap-back, then calls `_add_tab()`. Use `_plus_tab_idx()` helper everywhere.
- **WrapTabBar sync**: `_rebuild_wrap_tab_bar()` must be called after any structural tab change (add, delete, rename, reorder). It reads current `QTabWidget` state and rebuilds all buttons.
- **Favorites sync**: `MainWindow.toggle_favorite(card)` is the single entry point for starring/unstarring. It updates `item.favorited`, adds/removes from `_favorites_grid`, and calls `sync_star()` on all cards referencing the same `GameItem`.
- **Favorites tab protection**: Cannot be renamed, deleted, or reordered. All tab management methods guard with `if idx == 0`. The `＋` pseudo-tab is similarly protected.
- **Delete tab safety**: `removeTab()` must be wrapped in `blockSignals(True/False)` with an explicit `setCurrentIndex()` to prevent the `＋` pseudo-tab from being selected, which would trigger the add-tab dialog.
- **Storage contract**: `MainWindow.save()` calls `storage.save(self._tabs)` — never passes `_favorites_tab`. Favorites are reconstructed on startup by filtering `item.favorited` across all loaded tabs.
- **Search popup**: Uses `FramelessWindowHint + WA_ShowWithoutActivating` (not `Qt.WindowType.Popup`) to avoid stealing keyboard focus. Outside-click dismissal is handled by a `QApplication`-level event filter in `MainWindow.eventFilter`. Results display as `"  {title}   [{tab_name}]"` with `tab_widget_idx = i + 1` to account for Favorites at index 0.
- **Drag thresholds**: `WrapTabBar._DRAG_THRESHOLD = 8`px; `GameCard._DRAG_THRESHOLD = 12`px. Both exist to prevent accidental reordering from a simple click.
- **Duplicate game prevention**: `GameGrid.add_game()` checks for path duplicates case-insensitively within the same tab only. The same game path can exist in multiple tabs.
- **File drop filtering**: Only `.exe`, `.lnk`, and `.url` files are accepted on drop. Favorites grids reject all drops. `_DroppableContainer` also provides right-click "Add Game" on empty grid space for regular tabs.
- **Grid column calculation**: `max(1, (viewport().width() - 20) // (CARD_W + 16))`. `_rebuild_grid()` is triggered only when the column count actually changes on resize.
- **Title sync**: `MainWindow._sync_card_titles(item)` updates `_title_label` on every card (across all grids) that references the same `GameItem` object — ensures renames propagate to Favorites.
- **artwork_path sentinel**: `""` = never searched; `"none"` = searched RAWG but found nothing (prevents re-querying). Non-Steam artwork cache filenames are `ns_{md5(title.lower())}.jpg` — renaming a card after artwork load orphans the cache file (by design, to avoid breaking other cards with the same old title).
- **Cover art scaling**: Steam art scales to card width then crops top; RAWG art center-crops (scale to fill, crop center). Both are passed through `_round_pixmap(pixmap, 18)` before display.
