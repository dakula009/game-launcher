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

The PyInstaller spec is `my_game_hub.spec`. The Inno Setup script `installer.iss` can produce a full Windows installer from the dist folder, but is not part of the regular build workflow yet.

## Architecture

The app is a PySide6 game launcher with 5 source files:

- **`models.py`** — Pure dataclasses: `GameItem` (title, path, icon_path, favorited) and `GameTab` (name, list of games). Both have `to_dict`/`from_dict` for JSON serialization.
- **`storage.py`** — Reads/writes `%APPDATA%\MyGameHub\library.json`. Saves only regular tabs; the Favorites tab is not persisted here — it is rebuilt at load time from `GameItem.favorited` flags.
- **`launcher.py`** — `launch(path)` opens a game via `os.startfile` / `open` / `xdg-open`. `open_location(path)` opens the game's containing folder, resolving `.lnk` shortcuts on Windows via PowerShell before opening.
- **`main.py`** — Entry point. Creates `QApplication`, sets the window icon from `gamehub.ico`, and starts `MainWindow`.
- **`widgets.py`** — All UI. Key classes:
  - `SearchPopup` — floating `QListWidget` (Popup window flag) shown below the search bar as the user types.
  - `GameCard` — fixed 120×140 `QFrame`. Star (☆/★) sits at the bottom-right and is handled in `mousePressEvent` before drag logic. Clicking the card body launches the game; dragging reorders within the grid.
  - `GameGrid` — `QScrollArea` containing a `QGridLayout` that reflows cards on resize. `is_favorites=True` disables drag-and-drop acceptance and the "Add Game" context menu.
  - `MainWindow` — owns `self._tabs` (regular `GameTab` list) and `self._grids` (corresponding `GameGrid` list), plus separate `self._favorites_tab` / `self._favorites_grid`. The Favorites tab is always at `QTabWidget` index 0; regular tabs are at index `1..n`. All tab-index arithmetic must account for this +1 offset.

## Key conventions

- **Tab index offset**: `self._tabs[i]` maps to `self._tab_widget` index `i + 1`. Any code touching `currentIndex()` must handle index 0 as Favorites separately.
- **Favorites sync**: `MainWindow.toggle_favorite(card)` is the single entry point for starring/unstarring. It updates `item.favorited`, adds/removes from `_favorites_grid`, and calls `sync_star()` on all cards referencing the same `GameItem` object.
- **Favorites tab protection**: The Favorites tab cannot be renamed, deleted, or moved. `_on_tab_moved` snaps it back using `blockSignals`; `_rename_tab` and `_delete_tab` guard with `if idx == 0`.
- **Storage contract**: `MainWindow.save()` calls `storage.save(self._tabs)` — never passes `_favorites_tab`. Favorites are reconstructed on startup by filtering `item.favorited` across all loaded tabs.
