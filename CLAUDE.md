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

The app is a PySide6 game launcher with 5 source files:

- **`models.py`** — Pure dataclasses: `GameItem` (title, path, icon_path, favorited) and `GameTab` (name, list of games). Both have `to_dict`/`from_dict` for JSON serialization.
- **`storage.py`** — Reads/writes `%APPDATA%\MyGameHub\library.json`. Saves only regular tabs; the Favorites tab is not persisted — it is rebuilt at load time from `GameItem.favorited` flags.
- **`launcher.py`** — `launch(path)` opens a game via `os.startfile` / `open` / `xdg-open`. `open_location(path)` opens the game's containing folder, resolving `.lnk` shortcuts on Windows via PowerShell before opening.
- **`main.py`** — Entry point. Creates `QApplication`, sets the window icon from `gamehub.ico`, and starts `MainWindow`.
- **`widgets.py`** — All UI. Key classes:
  - `FlowLayout` — custom `QLayout` subclass that places items left-to-right and wraps to the next row when width is exceeded. Used by `WrapTabBar`. Each row is horizontally centered.
  - `WrapTabBar` — custom tab bar widget using `FlowLayout` of `QPushButton`s. Replaces the native `QTabBar` (which is hidden). Supports drag-to-reorder via event filter. Emits `tab_clicked`, `tab_right_clicked`, `tab_reordered`.
  - `SearchPopup` — frameless `QListWidget` with `WA_ShowWithoutActivating` so it never steals keyboard focus. Shown below the search bar as the user types. Dismissed via an app-level event filter in `MainWindow` when the user clicks outside it.
  - `AddGameCard` — dashed-border `+` placeholder card shown at the end of every regular tab grid. Clicking it opens the add-game dialog.
  - `StarWidget` — custom `QWidget` that draws a rounded 5-pointed star via `QPainterPath` with bezier-curved tips (T=0.3 factor). Gold filled when favorited, white outline when not. Used inside `GameCard` (18×18) and rendered to a `QPixmap` via `_make_star_pixmap()` for the Favorites tab button icon.
  - `GameCard` — fixed 130×130 `QFrame`. `StarWidget` sits at the top-right. Green play overlay appears on hover. Clicking the card body launches the game; dragging reorders within the grid. When game art is shown, cover art is rendered with 18px rounded corners via `_round_pixmap()` (transparent corner pixels + `setAutoFillBackground(False)` on the label). The title overlay at the bottom has matching `border-bottom-left/right-radius: 18px`.
  - `GameGrid` — `QScrollArea` containing a `QGridLayout` that reflows cards on resize. `is_favorites=True` disables drag-and-drop and the "Add Game" context menu. Always appends `AddGameCard` placeholder last.
  - `MainWindow` — owns `self._tabs` (regular `GameTab` list) and `self._grids` (corresponding `GameGrid` list), plus separate `self._favorites_tab` / `self._favorites_grid`. The Favorites tab is always at `QTabWidget` index 0; regular tabs are at index `1..n`; the `＋` pseudo-tab is always last.

## Key conventions

- **Tab index offset**: `self._tabs[i]` maps to `self._tab_widget` index `i + 1`. Any code touching `currentIndex()` must handle index 0 as Favorites and `_plus_tab_idx()` as the `＋` pseudo-tab separately.
- **`＋` pseudo-tab**: Always the last `QTabWidget` index. `_on_tab_changed` intercepts clicks on it via `blockSignals` + snap-back, then calls `_add_tab()`. Use `_plus_tab_idx()` helper everywhere.
- **WrapTabBar sync**: `_rebuild_wrap_tab_bar()` must be called after any structural tab change (add, delete, rename, reorder). It reads current `QTabWidget` state and rebuilds all buttons.
- **Favorites sync**: `MainWindow.toggle_favorite(card)` is the single entry point for starring/unstarring. It updates `item.favorited`, adds/removes from `_favorites_grid`, and calls `sync_star()` on all cards referencing the same `GameItem`.
- **Favorites tab protection**: Cannot be renamed, deleted, or reordered. All tab management methods guard with `if idx == 0`. The `＋` pseudo-tab is similarly protected.
- **Delete tab safety**: `removeTab()` must be wrapped in `blockSignals(True/False)` with an explicit `setCurrentIndex()` to prevent the `＋` pseudo-tab from being selected, which would trigger the add-tab dialog.
- **Storage contract**: `MainWindow.save()` calls `storage.save(self._tabs)` — never passes `_favorites_tab`. Favorites are reconstructed on startup by filtering `item.favorited` across all loaded tabs.
- **Search popup**: Uses `FramelessWindowHint + WA_ShowWithoutActivating` (not `Qt.WindowType.Popup`) to avoid stealing keyboard focus. Outside-click dismissal is handled by a `QApplication`-level event filter in `MainWindow.eventFilter`.
