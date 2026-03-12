from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QFileInfo, QMimeData, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QFileIconProvider,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

import launcher
import storage
from models import GameItem, GameTab

_icon_provider = QFileIconProvider()
FAVORITES_NAME = "★ Favorites"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_url_file(path: str) -> tuple:
    url = None
    icon_path = ""
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                lline = line.lower()
                if lline.startswith("url="):
                    candidate = line[4:]
                    if not candidate.lower().startswith(("http://", "https://")):
                        url = candidate
                elif lline.startswith("iconfile="):
                    icon_path = line[9:]
    except Exception:
        pass
    return url, icon_path


def _make_game_item_from_path(path: str) -> Optional[GameItem]:
    lower = path.lower()
    title = path.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
    if lower.endswith((".exe", ".lnk")):
        return GameItem(title=title, path=path)
    if lower.endswith(".url"):
        url, icon_path = _parse_url_file(path)
        if url:
            return GameItem(title=title, path=url, icon_path=icon_path)
    return None


# ---------------------------------------------------------------------------
# Search popup
# ---------------------------------------------------------------------------

class SearchPopup(QListWidget):
    """Floating dropdown that shows search results."""

    result_selected: Signal = Signal(object)  # emits (GameItem, tab_widget_index)

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(
            "QListWidget { background: #2a2a3e; color: #eee; border: 1px solid #7c6af7;"
            "              border-radius: 4px; padding: 2px; outline: none; }"
            "QListWidget::item { padding: 6px 12px; }"
            "QListWidget::item:selected { background: #7c6af7; color: #fff; }"
            "QListWidget::item:hover { background: #3a3a5e; }"
        )
        self.itemClicked.connect(self._on_item_clicked)

    def populate(self, results: list, anchor: QWidget) -> None:
        self.clear()
        for item, tab_name, tab_widget_idx in results:
            li = QListWidgetItem(f"  {item.title}   [{tab_name}]")
            li.setData(Qt.ItemDataRole.UserRole, (item, tab_widget_idx))
            self.addItem(li)
        pos = anchor.mapToGlobal(QPoint(0, anchor.height()))
        w = max(anchor.width(), 320)
        h = min(len(results) * 32 + 4, 240)
        self.setGeometry(pos.x(), pos.y(), w, h)
        self.show()

    def _on_item_clicked(self, li: QListWidgetItem) -> None:
        data = li.data(Qt.ItemDataRole.UserRole)
        self.result_selected.emit(data)
        self.hide()


# ---------------------------------------------------------------------------
# Game card
# ---------------------------------------------------------------------------

class GameCard(QFrame):
    CARD_W = 120
    CARD_H = 140
    _DRAG_THRESHOLD = 12

    def __init__(self, item: GameItem, grid: "GameGrid", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.item = item
        self.grid = grid
        self._drag_start_pos: Optional[QPoint] = None
        self._dragging = False

        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setFrameShape(QFrame.Shape.Box)
        self.setToolTip(item.path)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(6)

        # Icon
        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setFixedHeight(52)
        icon_source = item.icon_path if item.icon_path else (
            item.path if "://" not in item.path else ""
        )
        pixmap = _icon_provider.icon(QFileInfo(icon_source)).pixmap(48, 48) if icon_source else None
        if pixmap and not pixmap.isNull():
            self._icon_label.setPixmap(pixmap)
        else:
            self._icon_label.setText("🎮")
            self._icon_label.setStyleSheet("font-size: 36px;")
        layout.addWidget(self._icon_label)

        # Title
        self._title_label = QLabel(item.title)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        self._title_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #eee;")
        layout.addWidget(self._title_label)

        # Play overlay
        self._play_overlay = QLabel("▶  PLAY", self)
        self._play_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._play_overlay.setStyleSheet(
            "background: rgba(124, 106, 247, 210); color: white;"
            "font-size: 13px; font-weight: bold; border-radius: 4px;"
        )
        self._play_overlay.setGeometry(4, 8, self.CARD_W - 8, 52)
        self._play_overlay.hide()

        # Star (top-right corner, always visible)
        self._star = QLabel(self)
        self._star.setGeometry(self.CARD_W - 29, self.CARD_H - 29, 27, 27)
        self._star.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._refresh_star()

        self._set_idle_style()

    # ------------------------------------------------------------------
    # Star
    # ------------------------------------------------------------------

    def _refresh_star(self) -> None:
        if self.item.favorited:
            self._star.setText("★")
            self._star.setStyleSheet("color: #ffd700; font-size: 20px; background: transparent;")
        else:
            self._star.setText("☆")
            self._star.setStyleSheet("color: #555; font-size: 20px; background: transparent;")

    def sync_star(self) -> None:
        self._refresh_star()

    # ------------------------------------------------------------------
    # Search highlight
    # ------------------------------------------------------------------

    def highlight(self) -> None:
        self.setStyleSheet(
            "GameCard { background: #3d2e6b; border: 2px solid #fff; border-radius: 6px; }"
        )
        QTimer.singleShot(900, self._set_idle_style)

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------

    def _set_idle_style(self):
        self.setStyleSheet(
            "GameCard { background: #2a2a3e; border: 1px solid #444; border-radius: 6px; }"
        )

    def _set_hover_style(self):
        self.setStyleSheet(
            "GameCard { background: #32324a; border: 2px solid #7c6af7; border-radius: 6px; }"
        )

    # ------------------------------------------------------------------
    # Hover
    # ------------------------------------------------------------------

    def enterEvent(self, event):
        effect = QGraphicsDropShadowEffect(self)
        effect.setBlurRadius(20)
        effect.setColor(QColor("#7c6af7"))
        effect.setOffset(0, 0)
        self.setGraphicsEffect(effect)
        self._set_hover_style()
        self._play_overlay.show()
        self._play_overlay.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setGraphicsEffect(None)
        self._set_idle_style()
        self._play_overlay.hide()
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Mouse: star click, launch, drag
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._star.geometry().contains(event.pos()):
                self.grid.main_window.toggle_favorite(self)
                event.accept()
                return
            self._drag_start_pos = event.pos()
            self._dragging = False
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if (
            event.buttons() & Qt.MouseButton.LeftButton
            and self._drag_start_pos is not None
            and not self._dragging
        ):
            if (event.pos() - self._drag_start_pos).manhattanLength() > self._DRAG_THRESHOLD:
                self._dragging = True
                self._play_overlay.hide()
                self._start_card_drag()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._dragging:
            if self._drag_start_pos is not None:
                launcher.launch(self.item.path)
        self._dragging = False
        self._drag_start_pos = None
        super().mouseReleaseEvent(event)

    def _start_card_drag(self):
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData("application/x-game-card", b"")
        mime.setText(str(self.grid._cards.index(self)))
        pixmap = self.grab()
        small = pixmap.scaled(
            pixmap.width() * 3 // 4,
            pixmap.height() * 3 // 4,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        drag.setPixmap(small)
        drag.setHotSpot(QPoint(small.width() // 2, small.height() // 2))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.MoveAction)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _rename(self):
        name, ok = QInputDialog.getText(self, "Rename", "New title:", text=self.item.title)
        if ok and name.strip():
            self.item.title = name.strip()
            self.grid.main_window._sync_card_titles(self.item)
            self.grid.main_window.save()

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        run_action = QAction("▶  Run", self)
        run_action.triggered.connect(lambda: launcher.launch(self.item.path))
        menu.addAction(run_action)

        if "://" not in self.item.path:
            loc_action = QAction("Open Game Location", self)
            loc_action.triggered.connect(lambda: launcher.open_location(self.item.path))
            menu.addAction(loc_action)

        menu.addSeparator()

        if self.grid.is_favorites:
            unfav_action = QAction("☆  Remove from Favorites", self)
            unfav_action.triggered.connect(lambda: self.grid.main_window.toggle_favorite(self))
            menu.addAction(unfav_action)
        else:
            rename_action = QAction("Rename", self)
            rename_action.triggered.connect(self._rename)
            menu.addAction(rename_action)

            remove_action = QAction("Remove", self)
            remove_action.triggered.connect(lambda: self.grid.remove_game(self.item))
            menu.addAction(remove_action)

        menu.exec(event.globalPos())


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

class _DroppableContainer(QWidget):
    def __init__(self, grid: "GameGrid", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._grid = grid
        self.setAcceptDrops(True)
        self.setStyleSheet("background: #1a1a2e;")

    def dragEnterEvent(self, event):
        self._grid.dragEnterEvent(event)

    def dragMoveEvent(self, event):
        self._grid.dragMoveEvent(event)

    def dropEvent(self, event):
        self._grid.dropEvent(event)

    def contextMenuEvent(self, event):
        if self._grid.is_favorites:
            return
        menu = QMenu(self)
        add_action = QAction("+ Add Game", self)
        add_action.triggered.connect(self._grid.main_window._add_game_via_dialog)
        menu.addAction(add_action)
        menu.exec(event.globalPos())


class GameGrid(QScrollArea):
    def __init__(
        self,
        tab: GameTab,
        main_window: "MainWindow",
        is_favorites: bool = False,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.tab = tab
        self.main_window = main_window
        self.is_favorites = is_favorites
        self._cards: List[GameCard] = []

        self.setWidgetResizable(True)
        self.setStyleSheet("background: #1a1a2e; border: none;")

        self._container = _DroppableContainer(self)
        self._layout = QGridLayout(self._container)
        self._layout.setContentsMargins(16, 16, 16, 16)
        self._layout.setSpacing(12)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setWidget(self._container)
        self._last_col_count = 0

        for item in tab.games:
            self._add_card(item)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_cols = self._columns()
        if new_cols != self._last_col_count:
            self._last_col_count = new_cols
            self._rebuild_grid()

    def _columns(self) -> int:
        return max(1, (self.viewport().width() - 16) // (GameCard.CARD_W + 12))

    def _rebuild_grid(self):
        while self._layout.count():
            self._layout.takeAt(0)
        cols = self._columns()
        for i, card in enumerate(self._cards):
            self._layout.addWidget(card, i // cols, i % cols)

    def _add_card(self, item: GameItem):
        card = GameCard(item, self)
        self._cards.append(card)
        idx = len(self._cards) - 1
        cols = self._columns()
        self._layout.addWidget(card, idx // cols, idx % cols)

    def add_game(self, item: GameItem) -> bool:
        if any(g.path.lower() == item.path.lower() for g in self.tab.games):
            QMessageBox.warning(
                self,
                "Duplicate Game",
                f'"{item.title}" is already in this tab.',
            )
            return False
        self.tab.games.append(item)
        self._add_card(item)
        self.main_window.save()
        return True

    def remove_game(self, item: GameItem):
        card = next((c for c in self._cards if c.item is item), None)
        if card is None:
            return
        self._layout.removeWidget(card)
        card.deleteLater()
        self._cards.remove(card)
        self.tab.games.remove(item)
        self._rebuild_grid()
        self.main_window.save()

    def scroll_to_card(self, card: GameCard) -> None:
        self.ensureWidgetVisible(card)

    # ------------------------------------------------------------------
    # Drag-and-drop (disabled for favorites)
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event):
        if self.is_favorites:
            event.ignore()
            return
        if event.mimeData().hasFormat("application/x-game-card"):
            event.acceptProposedAction()
        elif event.mimeData().hasUrls():
            if any(
                url.toLocalFile().lower().endswith((".exe", ".lnk", ".url"))
                for url in event.mimeData().urls()
            ):
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self.is_favorites:
            event.ignore()
            return
        if event.mimeData().hasFormat("application/x-game-card") or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if self.is_favorites:
            event.ignore()
            return
        if event.mimeData().hasFormat("application/x-game-card"):
            self._handle_card_reorder(event)
        else:
            self._handle_file_drop(event)

    def _find_insert_index(self, drop_pos: QPoint) -> int:
        for i, card in enumerate(self._cards):
            rect = card.geometry()
            if drop_pos.y() < rect.center().y():
                return i
            if drop_pos.y() <= rect.bottom() and drop_pos.x() < rect.center().x():
                return i
        return len(self._cards)

    def _handle_card_reorder(self, event):
        src_idx = int(event.mimeData().text())
        if src_idx < 0 or src_idx >= len(self._cards):
            event.ignore()
            return
        drop_pos = event.position().toPoint()
        target_idx = self._find_insert_index(drop_pos)
        event.acceptProposedAction()
        final_idx = target_idx if target_idx <= src_idx else target_idx - 1
        if final_idx == src_idx:
            return
        card = self._cards.pop(src_idx)
        game = self.tab.games.pop(src_idx)
        self._cards.insert(final_idx, card)
        self.tab.games.insert(final_idx, game)
        self._rebuild_grid()
        self.main_window.save()

    def _handle_file_drop(self, event):
        skipped = 0
        for url in event.mimeData().urls():
            item = _make_game_item_from_path(url.toLocalFile())
            if item:
                self.add_game(item)  # shows its own warning if duplicate
            else:
                skipped += 1
        event.acceptProposedAction()
        if skipped:
            QMessageBox.warning(
                self,
                "Unsupported file type",
                f"{skipped} file(s) ignored. Supported: .exe, .lnk, Steam .url shortcuts.",
            )


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("My Game Hub (ver. 1.0)")
        self.resize(900, 600)
        icon_path = Path(__file__).parent / "gamehub.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setStyleSheet(
            "QMainWindow { background: #1a1a2e; }"
            "QTabWidget::pane { border: none; background: #1a1a2e; }"
            "QTabWidget::tab-bar { alignment: center; }"
            "QTabBar::tab { background: #2a2a3e; color: #ccc; padding: 6px 16px;"
            "               border-radius: 4px 4px 0 0; margin-right: 2px; }"
            "QTabBar::tab:selected { background: #7c6af7; color: #fff; }"
            "QTabBar::tab:hover { background: #3a3a5e; }"
            "QToolBar { background: #12122a; border: none; spacing: 6px; padding: 4px; }"
            "QToolBar QToolButton { color: #ccc; padding: 4px 10px; border-radius: 4px; }"
            "QToolBar QToolButton:hover { background: #2a2a3e; }"
            "QMenu { background-color: #6c5ce7; color: #ffffff;"
            "        border: 4px solid #7c6af7; border-radius: 6px; }"
            "QMenu::item { padding: 7px 22px; }"
            "QMenu::item:selected { background-color: #a29bfe; color: #1a1a2e; }"
            "QMenu::separator { height: 1px; background: #a29bfe; margin: 4px 8px; }"
            "QDialog { background: #1a1a2e; color: #eee; }"
            "QDialog QLabel { color: #eee; }"
            "QDialog QLineEdit { background: #2a2a3e; color: #eee; border: 1px solid #444;"
            "                    border-radius: 4px; padding: 4px 8px; }"
            "QDialog QPushButton { background: #2a2a3e; color: #eee; padding: 4px 14px;"
            "                      border: 1px solid #444; border-radius: 4px; }"
            "QDialog QPushButton:hover { background: #7c6af7; color: #fff; border-color: #7c6af7; }"
        )

        self._tabs: List[GameTab] = storage.load()
        self._grids: List[GameGrid] = []

        # Build favorites tab from favorited flags across all regular tabs
        self._favorites_tab = GameTab(
            name=FAVORITES_NAME,
            games=[g for tab in self._tabs for g in tab.games if g.favorited],
        )
        self._favorites_grid: Optional[GameGrid] = None

        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(False)
        self._tab_widget.setMovable(True)
        self._tab_widget.tabBar().tabMoved.connect(self._on_tab_moved)
        self._tab_widget.tabBar().installEventFilter(self)
        self.setCentralWidget(self._tab_widget)

        self._search_popup = SearchPopup()
        self._search_popup.result_selected.connect(self._on_search_result_selected)

        self._build_toolbar()
        self._populate_tabs()

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------

    def _build_toolbar(self):
        toolbar = QToolBar("Actions")
        self.addToolBar(toolbar)

        add_game_action = QAction("+ Add Game", self)
        add_game_action.triggered.connect(self._add_game_via_dialog)
        toolbar.addAction(add_game_action)

        toolbar.addSeparator()

        add_tab_action = QAction("+ Add Tab", self)
        add_tab_action.triggered.connect(self._add_tab)
        toolbar.addAction(add_tab_action)

        rename_tab_action = QAction("Rename Tab", self)
        rename_tab_action.triggered.connect(self._rename_tab)
        toolbar.addAction(rename_tab_action)

        delete_tab_action = QAction("Delete Tab", self)
        delete_tab_action.triggered.connect(self._delete_tab)
        toolbar.addAction(delete_tab_action)

        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        toolbar.addAction(about_action)

        # Push search bar to the right
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("🔍  Search games...")
        self._search_bar.setFixedWidth(200)
        self._search_bar.setStyleSheet(
            "QLineEdit { background: #2a2a3e; color: #eee; border: 1px solid #444;"
            "            border-radius: 4px; padding: 4px 8px; }"
            "QLineEdit:focus { border-color: #7c6af7; }"
        )
        self._search_bar.textChanged.connect(self._on_search_text_changed)
        toolbar.addWidget(self._search_bar)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self._tab_widget.tabBar() and event.type() == QEvent.Type.ContextMenu:
            idx = self._tab_widget.tabBar().tabAt(event.pos())
            if idx > 0:  # 0 is Favorites — protected
                menu = QMenu(self)
                rename_action = QAction("Rename Tab", self)
                rename_action.triggered.connect(lambda: self._rename_tab(idx))
                menu.addAction(rename_action)
                menu.exec(event.globalPos())
            return True
        return super().eventFilter(obj, event)

    def _populate_tabs(self):
        self._tab_widget.clear()
        self._grids.clear()

        # Favorites always first, pinned
        self._favorites_grid = GameGrid(self._favorites_tab, self, is_favorites=True)
        self._tab_widget.addTab(self._favorites_grid, FAVORITES_NAME)

        for tab in self._tabs:
            grid = GameGrid(tab, self)
            self._grids.append(grid)
            self._tab_widget.addTab(grid, tab.name)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def _on_search_text_changed(self, text: str) -> None:
        text = text.strip().lower()
        if not text:
            self._search_popup.hide()
            return
        results = []
        for i, (tab, grid) in enumerate(zip(self._tabs, self._grids)):
            for item in tab.games:
                if text in item.title.lower():
                    results.append((item, tab.name, i + 1))  # +1: offset for favorites tab
        if results:
            self._search_popup.populate(results, self._search_bar)
        else:
            self._search_popup.hide()

    def _on_search_result_selected(self, data: tuple) -> None:
        item, tab_widget_idx = data
        self._search_bar.clear()
        self._tab_widget.setCurrentIndex(tab_widget_idx)
        real_idx = tab_widget_idx - 1
        if 0 <= real_idx < len(self._grids):
            grid = self._grids[real_idx]
            card = next((c for c in grid._cards if c.item is item), None)
            if card:
                grid.scroll_to_card(card)
                card.highlight()

    # ------------------------------------------------------------------
    # Favorites
    # ------------------------------------------------------------------

    def toggle_favorite(self, card: GameCard) -> None:
        item = card.item
        item.favorited = not item.favorited

        if item.favorited:
            self._favorites_tab.games.append(item)
            self._favorites_grid._add_card(item)
        else:
            fav_card = next(
                (c for c in self._favorites_grid._cards if c.item is item), None
            )
            if fav_card:
                self._favorites_grid._layout.removeWidget(fav_card)
                fav_card.deleteLater()
                self._favorites_grid._cards.remove(fav_card)
                if item in self._favorites_tab.games:
                    self._favorites_tab.games.remove(item)
                self._favorites_grid._rebuild_grid()

        # Sync star on all cards showing this item
        for grid in self._grids:
            for c in grid._cards:
                if c.item is item:
                    c.sync_star()
        for c in self._favorites_grid._cards:
            if c.item is item:
                c.sync_star()

        self.save()

    def _sync_card_titles(self, item: GameItem) -> None:
        """Refresh title label on every card referencing this item."""
        for grid in [self._favorites_grid] + self._grids:
            for card in grid._cards:
                if card.item is item:
                    card._title_label.setText(item.title)

    # ------------------------------------------------------------------
    # Game management
    # ------------------------------------------------------------------

    def _show_about(self):
        QMessageBox.information(
            self,
            "About",
            "My Game Hub (ver. 1.0)\n\n"
            "A personal game launcher for organizing and launching your game library.\n\n"
            "© 2026 RL. All rights reserved.\n"
            "Contact: kula009@gmail.com",
        )

    def _add_game_via_dialog(self):
        idx = self._tab_widget.currentIndex()
        if idx == 0:
            QMessageBox.information(
                self, "Favorites", "Switch to a regular tab to add games."
            )
            return
        real_idx = idx - 1
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "Select Game Executable or Shortcut",
            "",
            "Games (*.exe *.lnk *.url)",
        )
        skipped = 0
        for path in paths:
            item = _make_game_item_from_path(path)
            if item:
                self._grids[real_idx].add_game(item)
            else:
                skipped += 1
        if skipped:
            QMessageBox.warning(
                self,
                "Unsupported file",
                f"{skipped} file(s) skipped. Only .exe, .lnk, and Steam .url files are supported.",
            )

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    def _add_tab(self):
        name, ok = QInputDialog.getText(self, "New Tab", "Tab name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name.lower() in [t.name.lower() for t in self._tabs]:
            QMessageBox.warning(self, "Duplicate Tab", f'A tab named "{name}" already exists.')
            return
        new_tab = GameTab(name=name)
        self._tabs.append(new_tab)
        grid = GameGrid(new_tab, self)
        self._grids.append(grid)
        self._tab_widget.addTab(grid, new_tab.name)
        self._tab_widget.setCurrentIndex(self._tab_widget.count() - 1)
        self.save()

    def _rename_tab(self, idx: int = -1):
        if idx < 0:
            idx = self._tab_widget.currentIndex()
        if idx == 0:
            QMessageBox.information(self, "Favorites", "The Favorites tab cannot be renamed.")
            return
        real_idx = idx - 1
        name, ok = QInputDialog.getText(
            self, "Rename Tab", "New name:", text=self._tabs[real_idx].name
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        existing = [t.name.lower() for i, t in enumerate(self._tabs) if i != real_idx]
        if name.lower() in existing:
            QMessageBox.warning(self, "Duplicate Tab", f'A tab named "{name}" already exists.')
            return
        self._tabs[real_idx].name = name
        self._tab_widget.setTabText(idx, name)
        self.save()

    def _delete_tab(self):
        idx = self._tab_widget.currentIndex()
        if idx == 0:
            QMessageBox.information(self, "Favorites", "The Favorites tab cannot be deleted.")
            return
        real_idx = idx - 1
        tab = self._tabs[real_idx]
        reply = QMessageBox.question(
            self,
            "Delete Tab",
            f'Delete tab "{tab.name}" and all its games?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            # Remove any favorited games in this tab from the favorites grid
            for item in list(tab.games):
                if item.favorited:
                    item.favorited = False
                    fav_card = next(
                        (c for c in self._favorites_grid._cards if c.item is item), None
                    )
                    if fav_card:
                        self._favorites_grid._layout.removeWidget(fav_card)
                        fav_card.deleteLater()
                        self._favorites_grid._cards.remove(fav_card)
                        if item in self._favorites_tab.games:
                            self._favorites_tab.games.remove(item)
            self._favorites_grid._rebuild_grid()
            self._tabs.pop(real_idx)
            self._grids.pop(real_idx)
            self._tab_widget.removeTab(idx)
            self.save()

    # ------------------------------------------------------------------
    # Tab reordering — favorites at index 0 is pinned
    # ------------------------------------------------------------------

    def _on_tab_moved(self, from_idx: int, to_idx: int):
        if from_idx == 0 or to_idx == 0:
            # Snap favorites back to position 0
            self._tab_widget.tabBar().blockSignals(True)
            self._tab_widget.tabBar().moveTab(to_idx, from_idx)
            self._tab_widget.tabBar().blockSignals(False)
            return
        real_from = from_idx - 1
        real_to = to_idx - 1
        self._tabs.insert(real_to, self._tabs.pop(real_from))
        self._grids.insert(real_to, self._grids.pop(real_from))
        self.save()

    # ------------------------------------------------------------------
    # Persistence — saves only regular tabs; favorites rebuilt on load
    # ------------------------------------------------------------------

    def save(self):
        storage.save(self._tabs)
