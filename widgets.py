from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import QFileInfo, Qt, QUrl
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFileDialog,
    QFileIconProvider,
    QFrame,
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


class GameCard(QFrame):
    """A fixed-size card representing a single game."""

    CARD_W = 120
    CARD_H = 140

    def __init__(self, item: GameItem, grid: "GameGrid", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.item = item
        self.grid = grid

        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setFrameShape(QFrame.Shape.Box)
        self.setToolTip(item.path)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 8, 4, 8)
        layout.setSpacing(6)

        # System icon via QFileIconProvider (shows real exe/lnk icon on Windows)
        icon_label = QLabel()
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pixmap = _icon_provider.icon(QFileInfo(item.path)).pixmap(48, 48)
        if not pixmap.isNull():
            icon_label.setPixmap(pixmap)
        else:
            icon_label.setText("🎮")
            icon_label.setStyleSheet("font-size: 36px;")
        layout.addWidget(icon_label)

        # Title label
        title_label = QLabel(item.title)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setWordWrap(True)
        title_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #eee;")
        layout.addWidget(title_label)

        self.setStyleSheet(
            "GameCard { background: #2a2a3e; border: 1px solid #444; border-radius: 6px; }"
            "GameCard:hover { border: 1px solid #7c6af7; background: #32324a; }"
        )

    def mouseDoubleClickEvent(self, event):
        launcher.launch(self.item.path)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        remove_action = QAction("Remove", self)
        remove_action.triggered.connect(lambda: self.grid.remove_game(self.item))
        menu.addAction(remove_action)
        menu.exec(event.globalPos())


class _DroppableContainer(QWidget):
    """Inner container widget that owns drag-and-drop, avoiding QScrollArea viewport issues."""

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

        for item in tab.games:
            self._add_card(item)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _columns(self) -> int:
        w = self.viewport().width()
        return max(1, (w - 16) // (GameCard.CARD_W + 12))

    def _rebuild_grid(self):
        for i, card in enumerate(self._cards):
            cols = self._columns()
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
        card_to_remove = next((c for c in self._cards if c.item is item), None)
        if card_to_remove is None:
            return
        self._layout.removeWidget(card_to_remove)
        card_to_remove.deleteLater()
        self._cards.remove(card_to_remove)
        self.tab.games.remove(item)
        self._rebuild_grid()
        self.main_window.save()

    # ------------------------------------------------------------------
    # Drag-and-drop (called by _DroppableContainer)
    # ------------------------------------------------------------------

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            if any(
                url.toLocalFile().lower().endswith((".exe", ".lnk"))
                for url in event.mimeData().urls()
            ):
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        skipped = 0
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith((".exe", ".lnk")):
                title = path.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
                self.add_game(GameItem(title=title, path=path))
            else:
                skipped += 1
        event.acceptProposedAction()
        if skipped:
            QMessageBox.warning(
                self,
                "Unsupported file type",
                f"{skipped} file(s) ignored. Only .exe and .lnk are supported.",
            )


class MainWindow(QMainWindow):
    """Application main window."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Game Launcher")
        self.resize(900, 600)
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
        )

        self._tabs: List[GameTab] = storage.load()
        self._grids: List[GameGrid] = []

        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(False)
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
            "Games (*.exe *.lnk)",
        )
        for path in paths:
            title = path.replace("\\", "/").split("/")[-1].rsplit(".", 1)[0]
            self._grids[idx].add_game(GameItem(title=title, path=path))

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
    # Persistence
    # ------------------------------------------------------------------

    def save(self):
        storage.save(self._tabs)
