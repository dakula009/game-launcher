from __future__ import annotations

from typing import List, Optional

from pathlib import Path

from PySide6.QtCore import QFileInfo, QMimeData, QPoint, Qt
from PySide6.QtGui import QAction, QColor, QDrag, QIcon
from PySide6.QtWidgets import (
    QFileDialog,
    QFileIconProvider,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QInputDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QScrollArea,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

import launcher
import storage
from models import GameItem, GameTab

_icon_provider = QFileIconProvider()


def _parse_url_file(path: str) -> tuple:
    """Parse a Windows .url file. Returns (url, icon_path) or (None, '') if unsupported.

    Supports any game launcher protocol (steam://, com.epicgames.launcher://, etc.).
    Skips plain http/https web links.
    """
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
    """Convert a file path to a GameItem, handling .exe, .lnk, and .url files."""
    lower = path.lower()
    title = path.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
    if lower.endswith((".exe", ".lnk")):
        return GameItem(title=title, path=path)
    if lower.endswith(".url"):
        url, icon_path = _parse_url_file(path)
        if url:
            return GameItem(title=title, path=url, icon_path=icon_path)
    return None


class GameCard(QFrame):
    """A fixed-size card representing a single game."""

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

        # Icon — prefer icon_path (from .url IconFile=), then path (for .exe/.lnk)
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

        # Play overlay (child of card, positioned absolutely over the icon area)
        self._play_overlay = QLabel("▶  PLAY", self)
        self._play_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._play_overlay.setStyleSheet(
            "background: rgba(124, 106, 247, 210); color: white; "
            "font-size: 13px; font-weight: bold; border-radius: 4px;"
        )
        self._play_overlay.setGeometry(4, 8, self.CARD_W - 8, 52)
        self._play_overlay.hide()

        self._set_idle_style()

    # ------------------------------------------------------------------
    # Styling helpers
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
    # Hover: glow + play overlay
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
    # Mouse: single click to launch, drag to reorder
    # ------------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
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
        # Use a slightly smaller ghost image
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
    # Right-click context menu
    # ------------------------------------------------------------------

    def _rename(self):
        name, ok = QInputDialog.getText(self, "Rename", "New title:", text=self.item.title)
        if ok and name.strip():
            self.item.title = name.strip()
            self._title_label.setText(name.strip())
            self.grid.main_window.save()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        run_action = QAction("▶  Run", self)
        run_action.triggered.connect(lambda: launcher.launch(self.item.path))
        menu.addAction(run_action)
        menu.addSeparator()
        rename_action = QAction("Rename", self)
        rename_action.triggered.connect(self._rename)
        menu.addAction(rename_action)
        remove_action = QAction("Remove", self)
        remove_action.triggered.connect(lambda: self.grid.remove_game(self.item))
        menu.addAction(remove_action)
        menu.exec(event.globalPos())


class _DroppableContainer(QWidget):
    """Inner container that owns all drag-and-drop events for the grid."""

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
        menu = QMenu(self)
        add_action = QAction("+ Add Game", self)
        add_action.triggered.connect(self._grid.main_window._add_game_via_dialog)
        menu.addAction(add_action)
        menu.exec(event.globalPos())


class GameGrid(QScrollArea):
    """Scrollable grid of GameCard widgets for one tab."""

    def __init__(self, tab: GameTab, main_window: "MainWindow", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.tab = tab
        self.main_window = main_window
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

    # ------------------------------------------------------------------
    # Resize: reflow cards when column count changes
    # ------------------------------------------------------------------

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_cols = self._columns()
        if new_cols != self._last_col_count:
            self._last_col_count = new_cols
            self._rebuild_grid()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def add_game(self, item: GameItem):
        self.tab.games.append(item)
        self._add_card(item)
        self.main_window.save()

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

    # ------------------------------------------------------------------
    # Drag-and-drop (called by _DroppableContainer)
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event):
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
        if event.mimeData().hasFormat("application/x-game-card") or event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-game-card"):
            self._handle_card_reorder(event)
        else:
            self._handle_file_drop(event)

    def _find_insert_index(self, drop_pos: QPoint) -> int:
        """Return the index before which a dragged card should be inserted."""
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

        # Adjust target after removing the source card
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
                self.add_game(item)
            else:
                skipped += 1
        event.acceptProposedAction()
        if skipped:
            QMessageBox.warning(
                self,
                "Unsupported file type",
                f"{skipped} file(s) ignored. Supported: .exe, .lnk, Steam .url shortcuts.",
            )


class MainWindow(QMainWindow):
    """Application main window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("My Game Hub")
        self.resize(900, 600)
        icon_path = Path(__file__).parent / "gamehub.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setStyleSheet(
            "QMainWindow { background: #1a1a2e; }"
            "QTabWidget::pane { border: none; background: #1a1a2e; }"
            "QTabWidget::tab-bar { alignment: center; }"
            "QTabBar::tab { background: #2a2a3e; color: #ccc; padding: 6px 16px; "
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
        )

        self._tabs: List[GameTab] = storage.load()
        self._grids: List[GameGrid] = []

        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(False)
        self._tab_widget.setMovable(True)
        self._tab_widget.tabBar().tabMoved.connect(self._on_tab_moved)
        self.setCentralWidget(self._tab_widget)

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

    def _populate_tabs(self):
        self._tab_widget.clear()
        self._grids.clear()
        for tab in self._tabs:
            grid = GameGrid(tab, self)
            self._grids.append(grid)
            self._tab_widget.addTab(grid, tab.name)

    # ------------------------------------------------------------------
    # Game management
    # ------------------------------------------------------------------

    def _add_game_via_dialog(self):
        idx = self._tab_widget.currentIndex()
        if idx < 0:
            return
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
                self._grids[idx].add_game(item)
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
        if ok and name.strip():
            new_tab = GameTab(name=name.strip())
            self._tabs.append(new_tab)
            grid = GameGrid(new_tab, self)
            self._grids.append(grid)
            self._tab_widget.addTab(grid, new_tab.name)
            self._tab_widget.setCurrentIndex(len(self._tabs) - 1)
            self.save()

    def _rename_tab(self):
        idx = self._tab_widget.currentIndex()
        if idx < 0:
            return
        name, ok = QInputDialog.getText(self, "Rename Tab", "New name:", text=self._tabs[idx].name)
        if ok and name.strip():
            self._tabs[idx].name = name.strip()
            self._tab_widget.setTabText(idx, name.strip())
            self.save()

    def _delete_tab(self):
        idx = self._tab_widget.currentIndex()
        if idx < 0:
            return
        tab = self._tabs[idx]
        reply = QMessageBox.question(
            self,
            "Delete Tab",
            f'Delete tab "{tab.name}" and all its games?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._tabs.pop(idx)
            self._grids.pop(idx)
            self._tab_widget.removeTab(idx)
            self.save()

    # ------------------------------------------------------------------
    # Tab reordering
    # ------------------------------------------------------------------

    def _on_tab_moved(self, from_idx: int, to_idx: int):
        self._tabs.insert(to_idx, self._tabs.pop(from_idx))
        self._grids.insert(to_idx, self._grids.pop(from_idx))
        self.save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self):
        storage.save(self._tabs)
