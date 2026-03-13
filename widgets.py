from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import QEvent, QFileInfo, QMimeData, QPoint, QRect, QSize, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QDrag, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFileIconProvider,
    QFrame,
    QGraphicsDropShadowEffect,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLayout,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTabWidget,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

import hashlib
import math
import re

import launcher
import settings
import storage
from models import GameItem, GameTab

_icon_provider = QFileIconProvider()
FAVORITES_NAME = "★ Favorites"
_PLUS_TAB      = "＋"          # sentinel text for the add-tab pseudo-tab

# ---------------------------------------------------------------------------
# Steam artwork helpers
# ---------------------------------------------------------------------------

_ARTWORK_DIR = Path(os.environ.get("APPDATA", Path.home())) / "MyGameHub" / "artwork"


def _steam_app_id(path: str) -> str:
    """Return app ID string if path is a steam://rungameid/... URL, else ''."""
    prefix = "steam://rungameid/"
    if path.lower().startswith(prefix):
        return path[len(prefix):].strip()
    return ""


def _artwork_cache_path(app_id: str) -> Path:
    return _ARTWORK_DIR / f"{app_id}.jpg"


def _round_pixmap(pixmap: QPixmap, radius: int) -> QPixmap:
    """Return a new pixmap with rounded corners; corner pixels are deleted (alpha=0)."""
    result = QPixmap(pixmap.size())
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(0, 0, pixmap.width(), pixmap.height(), radius, radius)
    painter.setClipPath(path)
    painter.drawPixmap(0, 0, pixmap)
    painter.end()
    return result


def _nonsteam_cache_path(title: str) -> Path:
    slug = hashlib.md5(title.lower().encode()).hexdigest()
    return _ARTWORK_DIR / f"ns_{slug}.jpg"


def _clean_search_title(title: str) -> str:
    """Strip common suffixes that confuse RAWG search."""
    title = re.sub(
        r'\s*[-–]\s*(digital|deluxe|gold|goty|edition|remastered).*$',
        '', title, flags=re.IGNORECASE,
    )
    return title.strip()


class ArtworkDownloader(QThread):
    finished = Signal(str, str)  # (app_id, local_cache_path)

    def __init__(self, app_id: str):
        super().__init__()
        self._app_id = app_id

    def run(self):
        url = f"https://cdn.akamai.steamstatic.com/steam/apps/{self._app_id}/library_600x900.jpg"
        dest = _artwork_cache_path(self._app_id)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            import urllib.request
            urllib.request.urlretrieve(url, dest)
            self.finished.emit(self._app_id, str(dest))
        except Exception:
            pass  # silently fall back to icon


class NonSteamArtworkDownloader(QThread):
    finished = Signal(str, str)  # (title, cache_path_or_"none")

    def __init__(self, title: str, api_key: str):
        super().__init__()
        self._title = title
        self._api_key = api_key

    def run(self):
        import urllib.request
        import urllib.parse
        import json as _json

        dest = _nonsteam_cache_path(self._title)
        try:
            query = urllib.parse.urlencode({
                "search": _clean_search_title(self._title),
                "key": self._api_key,
                "page_size": "1",
            })
            url = f"https://api.rawg.io/api/games?{query}"
            with urllib.request.urlopen(url, timeout=10) as r:
                data = _json.loads(r.read())
            results = data.get("results", [])
            img_url = results[0].get("background_image") if results else None
            if not img_url:
                self.finished.emit(self._title, "none")
                return
            dest.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(img_url, dest)
            self.finished.emit(self._title, str(dest))
        except Exception:
            self.finished.emit(self._title, "none")


# ---------------------------------------------------------------------------
# Design tokens
# ---------------------------------------------------------------------------
BG          = "#0d1117"
BG_CARD     = "#161f2e"
BG_HEADER   = "#0d1117"
BG_TABBAR   = "#131c2e"
BG_TOOLBAR  = "#0a0f1a"
ACCENT      = "#3b82f6"
TEXT_PRI    = "#f1f5f9"
TEXT_SEC    = "#64748b"
BORDER      = "#1e2a3a"
GREEN_PLAY  = "#22c55e"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_lnk_target_cache: dict = {}


def _resolve_lnk_target(lnk_path: str) -> str:
    """Parse a .lnk binary to extract the target path (avoids shortcut arrow in icon)."""
    if lnk_path in _lnk_target_cache:
        return _lnk_target_cache[lnk_path]
    target = lnk_path
    try:
        import struct
        with open(lnk_path, "rb") as f:
            data = f.read()
        if len(data) < 76:
            raise ValueError("too short")
        link_flags = struct.unpack_from("<I", data, 20)[0]
        has_idlist = bool(link_flags & 0x01)
        has_link_info = bool(link_flags & 0x02)
        offset = 76
        if has_idlist:
            idlist_size = struct.unpack_from("<H", data, offset)[0]
            offset += 2 + idlist_size
        if has_link_info:
            li_flags = struct.unpack_from("<I", data, offset + 4)[0]
            if li_flags & 0x01:  # VolumeIDAndLocalBasePath
                local_path_off = struct.unpack_from("<I", data, offset + 16)[0]
                path_start = offset + local_path_off
                path_end = data.index(b"\x00", path_start)
                candidate = data[path_start:path_end].decode("latin-1")
                if os.path.exists(candidate):
                    target = candidate
    except Exception:
        pass
    _lnk_target_cache[lnk_path] = target
    return target


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
    result_selected: Signal = Signal(object)
    cancelled: Signal = Signal()

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        # FramelessWindowHint + WA_ShowWithoutActivating = shows without
        # stealing keyboard focus, so the search bar keeps accepting input.
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.NoDropShadowWindowHint |
            Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setStyleSheet(
            f"QListWidget {{ background: {BG_TABBAR}; color: {TEXT_PRI}; border: 1px solid {ACCENT};"
            f"              border-radius: 8px; padding: 4px; outline: none; }}"
            f"QListWidget::item {{ padding: 8px 14px; border-radius: 6px; }}"
            f"QListWidget::item:selected {{ background: {ACCENT}; color: #fff; }}"
            f"QListWidget::item:hover {{ background: {BG_CARD}; }}"
        )
        self._picking = False
        self.itemClicked.connect(self._on_item_clicked)

    def populate(self, results: list, anchor: QWidget) -> None:
        self.clear()
        for item, tab_name, tab_widget_idx in results:
            li = QListWidgetItem(f"  {item.title}   [{tab_name}]")
            li.setData(Qt.ItemDataRole.UserRole, (item, tab_widget_idx))
            self.addItem(li)
        pos = anchor.mapToGlobal(QPoint(0, anchor.height()))
        w = max(anchor.width(), 320)
        h = min(len(results) * 36 + 8, 260)
        self.setGeometry(pos.x(), pos.y(), w, h)
        self.show()

    def _on_item_clicked(self, li: QListWidgetItem) -> None:
        self._picking = True
        self.result_selected.emit(li.data(Qt.ItemDataRole.UserRole))
        self.hide()

    def dismiss(self) -> None:
        if self.isVisible():
            self._picking = False
            self.hide()
            self.cancelled.emit()


# ---------------------------------------------------------------------------
# Flow layout — left-to-right, wraps to next row when width is exceeded
# ---------------------------------------------------------------------------

class FlowLayout(QLayout):
    def __init__(self, parent=None, h_spacing: int = 4, v_spacing: int = 4):
        super().__init__(parent)
        self._h_spacing = h_spacing
        self._v_spacing = v_spacing
        self._items: list = []

    def addItem(self, item):
        self._items.append(item)

    def count(self) -> int:
        return len(self._items)

    def itemAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items[index]
        return None

    def takeAt(self, index: int):
        if 0 <= index < len(self._items):
            return self._items.pop(index)
        return None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self) -> bool:
        return True

    def heightForWidth(self, width: int) -> int:
        return self._do_layout(QRect(0, 0, width, 0), test_only=True)

    def setGeometry(self, rect: QRect):
        super().setGeometry(rect)
        self._do_layout(rect, test_only=False)

    def sizeHint(self) -> QSize:
        return self.minimumSize()

    def minimumSize(self) -> QSize:
        size = QSize()
        for item in self._items:
            size = size.expandedTo(item.minimumSize())
        m = self.contentsMargins()
        size += QSize(m.left() + m.right(), m.top() + m.bottom())
        return size

    def _do_layout(self, rect: QRect, test_only: bool) -> int:
        m = self.contentsMargins()
        eff = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        eff_w = eff.width()

        # Pass 1: group items into rows
        rows: list = []
        row: list = []
        row_w = 0
        for item in self._items:
            w = item.sizeHint().width()
            needed = w if not row else w + self._h_spacing
            if row and row_w + needed > eff_w:
                rows.append(row)
                row = [(item, w, item.sizeHint().height())]
                row_w = w
            else:
                row.append((item, w, item.sizeHint().height()))
                row_w += needed
        if row:
            rows.append(row)

        # Pass 2: place each row centered
        y = eff.y()
        for row in rows:
            row_content_w = sum(w for _, w, _ in row) + self._h_spacing * (len(row) - 1)
            x = eff.x() + max(0, (eff_w - row_content_w) // 2)
            row_h = max(h for _, _, h in row)
            for item, w, h in row:
                if not test_only:
                    item.setGeometry(QRect(QPoint(x, y), item.sizeHint()))
                x += w + self._h_spacing
            y += row_h + self._v_spacing

        return y - (self._v_spacing if rows else 0) - rect.y() + m.bottom()


# ---------------------------------------------------------------------------
# Wrapping tab bar — individual buttons laid out with FlowLayout
# ---------------------------------------------------------------------------

class WrapTabBar(QWidget):
    tab_clicked = Signal(int)
    tab_right_clicked = Signal(int)
    tab_reordered = Signal(int, int)   # from_idx, to_idx

    _DRAG_THRESHOLD = 8

    def __init__(self, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._flow = FlowLayout(self, h_spacing=4, v_spacing=4)
        self._flow.setContentsMargins(10, 8, 10, 8)
        self.setLayout(self._flow)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setStyleSheet(f"background: {BG};")
        self._drag_src: int = -1
        self._drag_start: Optional[QPoint] = None
        self._dragging: bool = False
        self._drag_label: Optional[QLabel] = None

    def rebuild(self, names: list, current_idx: int, plus_idx: int) -> None:
        while self._flow.count():
            item = self._flow.takeAt(0)
            if item and item.widget():
                item.widget().deleteLater()

        for i, name in enumerate(names):
            is_plus = (i == plus_idx)
            is_selected = (i == current_idx) and not is_plus
            is_fav = (i == 0)
            display = name.replace("★", "").strip() if is_fav else name
            btn = QPushButton(display)
            if is_fav:
                btn.setIcon(QIcon(_make_star_pixmap(14, "#f5d060")))
                btn.setIconSize(QSize(14, 14))
            btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
            self._style_btn(btn, is_selected, is_plus, is_favorites=is_fav)
            btn.clicked.connect(lambda checked=False, idx=i: self.tab_clicked.emit(idx))
            if not is_plus and i > 0:
                btn.installEventFilter(self)
                btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
                btn.customContextMenuRequested.connect(
                    lambda pos, idx=i: self.tab_right_clicked.emit(idx)
                )
            self._flow.addWidget(btn)

        self.updateGeometry()

    # ------------------------------------------------------------------
    # Drag-to-reorder
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        if not isinstance(obj, QPushButton):
            return super().eventFilter(obj, event)
        etype = event.type()

        if etype == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
            self._drag_src = self._btn_index(obj)
            self._drag_start = event.globalPosition().toPoint()
            self._dragging = False
            return False  # let button handle click normally

        if etype == QEvent.Type.MouseMove and self._drag_src >= 0:
            if not self._dragging:
                dist = (event.globalPosition().toPoint() - self._drag_start).manhattanLength()
                if dist > self._DRAG_THRESHOLD:
                    self._dragging = True
                    self._start_drag_visual(obj)
            if self._dragging:
                self._update_drag_visual(event.globalPosition().toPoint())
                return True
            return False

        if etype == QEvent.Type.MouseButtonRelease and event.button() == Qt.MouseButton.LeftButton:
            if self._dragging:
                local = self.mapFromGlobal(event.globalPosition().toPoint())
                self._finish_drag(local)
                return True  # suppress click signal
            self._reset_drag()
            return False

        return False

    def _btn_index(self, btn: QPushButton) -> int:
        for i in range(self._flow.count()):
            item = self._flow.itemAt(i)
            if item and item.widget() is btn:
                return i
        return -1

    def _btn_at_pos(self, local: QPoint) -> int:
        for i in range(self._flow.count()):
            item = self._flow.itemAt(i)
            if item and item.widget() and item.geometry().contains(local):
                return i
        return -1

    def _start_drag_visual(self, btn: QPushButton):
        self._drag_label = QLabel(btn.text(), self.window())
        self._drag_label.setStyleSheet(
            f"background: {ACCENT}; color: #fff; font-weight: bold;"
            f" border-radius: 8px; padding: 8px 22px; font-size: 13px;"
        )
        self._drag_label.adjustSize()
        self._drag_label.raise_()
        self._drag_label.show()
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def _update_drag_visual(self, global_pos: QPoint):
        if self._drag_label:
            local = self.window().mapFromGlobal(global_pos)
            self._drag_label.move(
                local.x() - self._drag_label.width() // 2,
                local.y() - self._drag_label.height() // 2,
            )

    def _finish_drag(self, local: QPoint):
        target = self._btn_at_pos(local)
        src = self._drag_src
        plus = self._flow.count() - 1
        self._reset_drag()
        if target > 0 and target < plus and target != src:
            self.tab_reordered.emit(src, target)

    def _reset_drag(self):
        if self._drag_label:
            self._drag_label.deleteLater()
            self._drag_label = None
        self._drag_src = -1
        self._drag_start = None
        self._dragging = False
        self.unsetCursor()

    def _style_btn(self, btn: QPushButton, selected: bool, is_plus: bool, is_favorites: bool = False) -> None:
        if is_plus:
            btn.setStyleSheet(
                f"QPushButton {{ background: {BG_TABBAR}; color: {TEXT_SEC};"
                f" border: 1px solid {BORDER}; border-radius: 8px;"
                f" padding: 8px 8px; font-size: 13px; min-width: 28px; max-width: 36px; }}"
                f"QPushButton:hover {{ background: {BG_CARD}; color: {TEXT_PRI}; }}"
            )
        elif selected:
            btn.setStyleSheet(
                f"QPushButton {{ background: {ACCENT}; color: #fff; font-weight: bold;"
                f" border: 1px solid {ACCENT}; border-radius: 8px;"
                f" padding: 8px 22px; font-size: 13px; min-width: 60px; }}"
            )
        elif is_favorites:
            btn.setStyleSheet(
                f"QPushButton {{ background: #3a3010; color: #f5d060;"
                f" border: 1px solid #7a6520; border-radius: 8px;"
                f" padding: 8px 22px; font-size: 13px; min-width: 60px; }}"
                f"QPushButton:hover {{ background: #4a3e18; color: #fde68a; }}"
            )
        else:
            btn.setStyleSheet(
                f"QPushButton {{ background: {BG_TABBAR}; color: {TEXT_SEC};"
                f" border: 1px solid {BORDER}; border-radius: 8px;"
                f" padding: 8px 22px; font-size: 13px; min-width: 60px; }}"
                f"QPushButton:hover {{ background: {BG_CARD}; color: {TEXT_PRI}; }}"
            )


# ---------------------------------------------------------------------------
# Add-game placeholder card
# ---------------------------------------------------------------------------

class AddGameCard(QFrame):
    """Dashed-border '+' card shown at the end of every regular tab."""

    CARD_W = 130
    CARD_H = 130

    def __init__(self, grid: "GameGrid", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.grid = grid
        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("Add a game")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        plus = QLabel("+")
        plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        plus.setStyleSheet(f"color: {TEXT_SEC}; font-size: 52px; background: transparent;")
        layout.addWidget(plus)

        self._set_idle_style()

    def _set_idle_style(self):
        self.setStyleSheet(
            f"AddGameCard {{ background: transparent; border: 2px dashed {BORDER};"
            f"               border-radius: 18px; }}"
        )

    def _set_hover_style(self):
        self.setStyleSheet(
            f"AddGameCard {{ background: {BG_CARD}; border: 2px dashed {ACCENT};"
            f"               border-radius: 18px; }}"
        )

    def enterEvent(self, event):
        self._set_hover_style()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._set_idle_style()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.grid.main_window._add_game_via_dialog()
        super().mouseReleaseEvent(event)


# ---------------------------------------------------------------------------
# Star widget (rounded shape)
# ---------------------------------------------------------------------------

class StarWidget(QWidget):
    """Draws a rounded star using bezier-curved points."""
    _OUTER_R = 7
    _INNER_R = 3.85

    def __init__(self, parent=None):
        super().__init__(parent)
        self._favorited = False
        self.setFixedSize(18, 18)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def set_favorited(self, favorited: bool):
        self._favorited = favorited
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = self._star_path(9, 9, self._OUTER_R, self._INNER_R)
        if self._favorited:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.fillPath(path, QColor("#ffd700"))
        else:
            pen = QPen(QColor("#e2e8f0"))
            pen.setWidthF(1.5)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(path)

    @staticmethod
    def _star_path(cx: float, cy: float, r_outer: float, r_inner: float, points: int = 5) -> QPainterPath:
        """Build a star path with gently rounded tips (t=0.3 bezier factor)."""
        T = 0.3  # how far along each edge the curve starts/ends (lower = sharper)
        n = points * 2
        verts = []
        for i in range(n):
            angle = math.pi / points * i - math.pi / 2
            r = r_outer if i % 2 == 0 else r_inner
            verts.append((cx + r * math.cos(angle), cy + r * math.sin(angle)))

        def lerp(a, b, t):
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)

        path = QPainterPath()
        path.moveTo(*lerp(verts[-1], verts[0], 1 - T))
        for i in range(n):
            v = verts[i]
            nv = verts[(i + 1) % n]
            path.quadTo(v[0], v[1], *lerp(v, nv, T))
            path.lineTo(*lerp(v, nv, 1 - T))
        path.closeSubpath()
        return path


def _make_star_pixmap(size: int, color: str) -> QPixmap:
    """Render a filled rounded star into a QPixmap of the given size."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)
    half = size / 2
    outer = half * 0.85
    inner = outer * (StarWidget._INNER_R / StarWidget._OUTER_R)
    path = StarWidget._star_path(half, half, outer, inner)
    painter = QPainter(px)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.fillPath(path, QColor(color))
    painter.end()
    return px


# Game card
# ---------------------------------------------------------------------------

class GameCard(QFrame):
    CARD_W = 130
    CARD_H = 130
    _DRAG_THRESHOLD = 12
    artwork_updated = Signal(object)

    def __init__(self, item: GameItem, grid: "GameGrid", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.item = item
        self.grid = grid
        self._drag_start_pos: Optional[QPoint] = None
        self._dragging = False
        self._downloader: Optional[ArtworkDownloader] = None
        self._ns_downloader: Optional[NonSteamArtworkDownloader] = None

        self.setFixedSize(self.CARD_W, self.CARD_H)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        app_id = _steam_app_id(item.path)
        if app_id and not item.use_icon:
            self._build_steam_ui(app_id)
        else:
            self._build_default_ui()

        # Search-highlight overlay — transparent border drawn above all children
        self._search_highlight = QFrame(self)
        self._search_highlight.setGeometry(0, 0, self.CARD_W, self.CARD_H)
        self._search_highlight.setStyleSheet(
            "QFrame { border: 3px solid #fff; border-radius: 18px; background: transparent; }"
        )
        self._search_highlight.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._search_highlight.hide()

        # Star — top-right (always present, above highlight overlay)
        self._star = StarWidget(self)
        self._star.setGeometry(self.CARD_W - 24, 6, 18, 18)
        self._refresh_star()

        self.artwork_updated.connect(lambda _: self.grid.main_window.save())

        # Non-Steam artwork (must run after _star is created)
        # Only load from cache if artwork was previously found; never auto-search
        if not app_id and not item.use_icon and item.artwork_path not in ("", "none"):
            self._switch_to_cover_layout()
            self._apply_nonsteam_cover_art(item.artwork_path)

        self._set_idle_style()

    def _build_default_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(6)

        # Icon
        self._icon_label = QLabel()
        self._icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._icon_label.setFixedHeight(72)
        self._icon_label.setStyleSheet("background: transparent;")
        if self.item.icon_path:
            icon_source = self.item.icon_path
        elif self.item.path.lower().endswith(".lnk"):
            icon_source = _resolve_lnk_target(self.item.path)
        elif "://" not in self.item.path:
            icon_source = self.item.path
        else:
            icon_source = ""
        pixmap = _icon_provider.icon(QFileInfo(icon_source)).pixmap(56, 56) if icon_source else None
        if pixmap and not pixmap.isNull():
            self._icon_label.setPixmap(pixmap)
        else:
            self._icon_label.setText("🎮")
            self._icon_label.setStyleSheet("font-size: 38px; background: transparent;")
        layout.addWidget(self._icon_label)

        # Title
        self._title_label = QLabel(self.item.title)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title_label.setWordWrap(True)
        self._title_label.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {TEXT_PRI}; background: transparent;"
        )
        layout.addWidget(self._title_label)
        self._default_title_label = self._title_label

        # Play overlay — green square centered over icon area
        overlay_size = 48
        ox = (self.CARD_W - overlay_size) // 2
        oy = 10 + (72 - overlay_size) // 2
        self._play_overlay = QLabel("▶", self)
        self._play_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._play_overlay.setStyleSheet(
            f"background: {GREEN_PLAY}; color: white; font-size: 36px; border-radius: 8px;"
        )
        self._play_overlay.setGeometry(ox, oy, overlay_size, overlay_size)
        self._play_overlay.hide()

    def _build_steam_ui(self, app_id: str):
        # Cover art label fills the card
        self._cover_label = QLabel(self)
        self._cover_label.setAutoFillBackground(False)
        self._cover_label.setGeometry(0, 0, self.CARD_W, self.CARD_H)
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_label.setText("🎮")
        self._cover_label.setStyleSheet("font-size: 38px; background: transparent;")

        # Title overlay at bottom — also aliased as _title_label for rename compatibility
        _overlay_h = 40
        self._title_overlay = QLabel(self.item.title, self)
        self._title_overlay.setGeometry(0, self.CARD_H - _overlay_h, self.CARD_W, _overlay_h)
        self._title_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self._title_overlay.setWordWrap(True)
        self._title_overlay.setStyleSheet(
            f"background: rgba(0,0,0,160); color: {TEXT_PRI};"
            f" font-size: 12px; font-weight: bold; padding: 2px 4px;"
            f" border-bottom-left-radius: 18px; border-bottom-right-radius: 18px;"
        )
        self._title_label = self._title_overlay  # alias for _sync_card_titles

        # Play overlay — centered on full card
        overlay_size = 48
        ox = (self.CARD_W - overlay_size) // 2
        oy = (self.CARD_H - overlay_size) // 2
        self._play_overlay = QLabel("▶", self)
        self._play_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._play_overlay.setStyleSheet(
            f"background: {GREEN_PLAY}; color: white; font-size: 36px; border-radius: 8px;"
        )
        self._play_overlay.setGeometry(ox, oy, overlay_size, overlay_size)
        self._play_overlay.hide()

        # Check cache or start download
        cache_path = _artwork_cache_path(app_id)
        if cache_path.exists():
            self._apply_cover_art(str(cache_path))
        else:
            self._downloader = ArtworkDownloader(app_id)
            self._downloader.finished.connect(self._on_artwork_ready)
            self._downloader.start()

    def _apply_cover_art(self, cache_path: str):
        """Steam-style: scale to card width, crop top portion."""
        pixmap = QPixmap(cache_path)
        if not pixmap.isNull():
            scaled = pixmap.scaledToWidth(self.CARD_W, Qt.TransformationMode.SmoothTransformation)
            if scaled.height() > self.CARD_H:
                scaled = scaled.copy(0, 0, self.CARD_W, self.CARD_H)
            self._cover_label.setPixmap(_round_pixmap(scaled, 18))
            self._cover_label.setText("")
            self._cover_label.setStyleSheet("background: transparent;")
            self._title_overlay.raise_()

    def _apply_nonsteam_cover_art(self, cache_path: str):
        """Non-Steam: center-crop to fill card (handles landscape RAWG images)."""
        pixmap = QPixmap(cache_path)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self.CARD_W, self.CARD_H,
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            x = (scaled.width() - self.CARD_W) // 2
            y = (scaled.height() - self.CARD_H) // 2
            cropped = scaled.copy(x, y, self.CARD_W, self.CARD_H)
            self._cover_label.setPixmap(_round_pixmap(cropped, 18))
            self._cover_label.setText("")
            self._cover_label.setStyleSheet("background: transparent;")
            self._title_overlay.raise_()

    def _on_artwork_ready(self, app_id: str, cache_path: str):
        self._apply_cover_art(cache_path)

    # ------------------------------------------------------------------
    # Non-Steam artwork
    # ------------------------------------------------------------------

    def _start_nonsteam_search(self, api_key: str):
        self._ns_downloader = NonSteamArtworkDownloader(self.item.title, api_key)
        self._ns_downloader.finished.connect(self._on_nonsteam_artwork_ready)
        self._ns_downloader.start()

    def _on_nonsteam_artwork_ready(self, title: str, path: str):
        if title != self.item.title:
            return
        self.item.artwork_path = path
        if path != "none":
            self._switch_to_cover_layout()
            self._apply_nonsteam_cover_art(path)
        self.artwork_updated.emit(self.item)

    def _switch_to_cover_layout(self):
        """Replace default icon layout with full-bleed cover art layout."""
        # Hide default UI widgets (kept alive for potential switch-back)
        if hasattr(self, '_icon_label'):
            self._icon_label.hide()
        if hasattr(self, '_default_title_label'):
            self._default_title_label.hide()

        # Replace play overlay with version centered on full card
        if hasattr(self, '_play_overlay'):
            self._play_overlay.deleteLater()
        overlay_size = 48
        ox = (self.CARD_W - overlay_size) // 2
        oy = (self.CARD_H - overlay_size) // 2
        self._play_overlay = QLabel("▶", self)
        self._play_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._play_overlay.setStyleSheet(
            f"background: {GREEN_PLAY}; color: white; font-size: 36px; border-radius: 8px;"
        )
        self._play_overlay.setGeometry(ox, oy, overlay_size, overlay_size)
        self._play_overlay.hide()

        # Create cover art label filling the card
        self._cover_label = QLabel(self)
        self._cover_label.setAutoFillBackground(False)
        self._cover_label.setGeometry(0, 0, self.CARD_W, self.CARD_H)
        self._cover_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cover_label.setText("🎮")
        self._cover_label.setStyleSheet("font-size: 38px; background: transparent;")

        # Title overlay at bottom
        _overlay_h = 40
        self._title_overlay = QLabel(self.item.title, self)
        self._title_overlay.setGeometry(0, self.CARD_H - _overlay_h, self.CARD_W, _overlay_h)
        self._title_overlay.setAlignment(Qt.AlignmentFlag.AlignCenter | Qt.AlignmentFlag.AlignVCenter)
        self._title_overlay.setWordWrap(True)
        self._title_overlay.setStyleSheet(
            f"background: rgba(0,0,0,160); color: {TEXT_PRI};"
            f" font-size: 12px; font-weight: bold; padding: 2px 4px;"
            f" border-bottom-left-radius: 18px; border-bottom-right-radius: 18px;"
        )
        self._title_label = self._title_overlay

        self._cover_label.show()
        self._title_overlay.show()
        self._star.raise_()

    def _manual_search_artwork(self):
        api_key = settings.get_rawg_key()
        if not api_key:
            QMessageBox.information(
                self, "No API Key",
                "Set your RAWG API key in Settings first.",
            )
            return
        self.item.artwork_path = ""
        self._start_nonsteam_search(api_key)

    def _clear_artwork(self):
        # Don't delete the cached file — other renamed cards may share history.
        # Just unset the reference so this card reverts to its icon.
        self.item.artwork_path = ""
        self.grid.main_window.save()
        # Recreate the card from scratch so the original icon is reliably shown.
        self.grid.main_window._refresh_card_everywhere(self.item)

    # ------------------------------------------------------------------
    # Star
    # ------------------------------------------------------------------

    def _refresh_star(self) -> None:
        self._star.set_favorited(self.item.favorited)

    def sync_star(self) -> None:
        self._refresh_star()

    # ------------------------------------------------------------------
    # Highlight (search result)
    # ------------------------------------------------------------------

    def highlight(self) -> None:
        self._search_highlight.show()
        self._search_highlight.raise_()
        self._star.raise_()

    def clear_highlight(self) -> None:
        self._search_highlight.hide()

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------

    def _set_idle_style(self):
        self.setStyleSheet(
            f"GameCard {{ background: {BG_CARD}; border: 1px solid {BORDER}; border-radius: 18px; }}"
        )

    def _set_hover_style(self):
        self.setStyleSheet(
            f"GameCard {{ background: #1a2744; border: 2px solid {ACCENT}; border-radius: 18px; }}"
        )

    # ------------------------------------------------------------------
    # Hover
    # ------------------------------------------------------------------

    def enterEvent(self, event):
        self.grid.main_window._clear_search_highlight()
        effect = QGraphicsDropShadowEffect(self)
        effect.setBlurRadius(24)
        effect.setColor(QColor(ACCENT))
        effect.setOffset(0, 0)
        self.setGraphicsEffect(effect)
        self._set_hover_style()
        self._play_overlay.show()
        self._play_overlay.raise_()
        self._star.raise_()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setGraphicsEffect(None)
        self._set_idle_style()
        self._play_overlay.hide()
        super().leaveEvent(event)

    # ------------------------------------------------------------------
    # Mouse
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

    def _steam_search_artwork(self):
        self.item.use_icon = False
        self.grid.main_window.save()
        self.grid.main_window._refresh_card_everywhere(self.item)

    def _steam_clear_artwork(self):
        self.item.use_icon = True
        self.grid.main_window.save()
        self.grid.main_window._refresh_card_everywhere(self.item)

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        run_action = QAction("Run", self)
        run_action.triggered.connect(lambda: launcher.launch(self.item.path))
        menu.addAction(run_action)

        if "://" not in self.item.path:
            loc_action = QAction("Open Game Location", self)
            loc_action.triggered.connect(lambda: launcher.open_location(self.item.path))
            menu.addAction(loc_action)

        menu.addSeparator()

        fav_label = "Remove from Favorites" if self.item.favorited else "Add to Favorites"
        fav_action = QAction(fav_label, self)
        fav_action.triggered.connect(lambda: self.grid.main_window.toggle_favorite(self))
        menu.addAction(fav_action)

        if not self.grid.is_favorites:
            menu.addSeparator()
            rename_action = QAction("Rename", self)
            rename_action.triggered.connect(self._rename)
            menu.addAction(rename_action)

            remove_action = QAction("Remove", self)
            remove_action.triggered.connect(lambda: self.grid.remove_game(self.item))
            menu.addAction(remove_action)

        # Unified artwork options
        menu.addSeparator()
        app_id = _steam_app_id(self.item.path)
        has_artwork = (app_id and not self.item.use_icon) or \
                      (not app_id and self.item.artwork_path not in ("", "none"))

        search_act = QAction("Search for artwork", self)
        search_act.triggered.connect(
            self._steam_search_artwork if app_id else self._manual_search_artwork
        )
        menu.addAction(search_act)

        if has_artwork:
            clear_act = QAction("Clear artwork", self)
            clear_act.triggered.connect(
                self._steam_clear_artwork if app_id else self._clear_artwork
            )
            menu.addAction(clear_act)

        menu.exec(event.globalPos())


# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

class _DroppableContainer(QWidget):
    def __init__(self, grid: "GameGrid", parent: Optional[QWidget] = None):
        super().__init__(parent)
        self._grid = grid
        self.setAcceptDrops(True)
        self.setStyleSheet(f"background: {BG};")

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
        self.setStyleSheet(f"background: {BG}; border: none;")

        self._container = _DroppableContainer(self)
        self._layout = QGridLayout(self._container)
        self._layout.setContentsMargins(20, 20, 20, 20)
        self._layout.setSpacing(16)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.setWidget(self._container)
        self._last_col_count = 0

        # Placeholder card (regular tabs only)
        self._placeholder = AddGameCard(self) if not is_favorites else None

        for item in tab.games:
            self._add_card(item)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        new_cols = self._columns()
        if new_cols != self._last_col_count:
            self._last_col_count = new_cols
            self._rebuild_grid()

    def _columns(self) -> int:
        return max(1, (self.viewport().width() - 20) // (GameCard.CARD_W + 16))

    def _rebuild_grid(self):
        while self._layout.count():
            self._layout.takeAt(0)
        cols = self._columns()
        for i, card in enumerate(self._cards):
            self._layout.addWidget(card, i // cols, i % cols)
        if self._placeholder:
            idx = len(self._cards)
            self._layout.addWidget(self._placeholder, idx // cols, idx % cols)

    def _add_card(self, item: GameItem):
        card = GameCard(item, self)
        self._cards.append(card)
        self._rebuild_grid()

    def add_game(self, item: GameItem) -> bool:
        if any(g.path.lower() == item.path.lower() for g in self.tab.games):
            QMessageBox.warning(self, "Duplicate Game", f'"{item.title}" is already in this tab.')
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

    def _refresh_card(self, card: GameCard) -> None:
        idx = self._cards.index(card)
        self._layout.removeWidget(card)
        card.deleteLater()
        self._cards.pop(idx)
        new_card = GameCard(card.item, self)
        self._cards.insert(idx, new_card)
        self._rebuild_grid()

    def scroll_to_card(self, card: GameCard) -> None:
        self.ensureWidgetVisible(card)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat("application/x-game-card"):
            event.acceptProposedAction()
        elif not self.is_favorites and event.mimeData().hasUrls():
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
        if event.mimeData().hasFormat("application/x-game-card"):
            event.acceptProposedAction()
        elif not self.is_favorites and event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasFormat("application/x-game-card"):
            self._handle_card_reorder(event)
        elif not self.is_favorites:
            self._handle_file_drop(event)
        else:
            event.ignore()

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


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setFixedWidth(380)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("RAWG API Key:"))
        self._key_edit = QLineEdit(settings.get_rawg_key())
        self._key_edit.setPlaceholderText("Paste your free key from rawg.io")
        layout.addWidget(self._key_edit)
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(self._save)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _save(self):
        settings.set_rawg_key(self._key_edit.text().strip())
        self.accept()


# ---------------------------------------------------------------------------
# Main window
# ---------------------------------------------------------------------------

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("My Game Hub (ver. 1.3)")
        self.resize(1400, 720)
        icon_path = Path(__file__).parent / "gamehub.ico"
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))

        self.setStyleSheet(
            f"QMainWindow {{ background: {BG}; }}"
            f"QScrollArea {{ background: {BG}; border: none; }}"
            f"QScrollBar:vertical {{ background: {BG_CARD}; width: 6px; border-radius: 3px; }}"
            f"QScrollBar::handle:vertical {{ background: #2d4a6e; border-radius: 3px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
            f"QToolBar {{ background: {BG_TOOLBAR}; border: none; spacing: 4px; padding: 4px 10px; }}"
            f"QToolBar QToolButton {{ color: {TEXT_SEC}; padding: 4px 10px; border-radius: 4px;"
            f"                        font-size: 12px; }}"
            f"QToolBar QToolButton:hover {{ background: {BG_CARD}; color: {TEXT_PRI}; }}"
            f"QMenu {{ background-color: {BG_TABBAR}; color: {TEXT_PRI};"
            f"         border: 1px solid {BORDER}; border-radius: 8px; padding: 4px; }}"
            f"QMenu::item {{ padding: 7px 22px; border-radius: 4px; }}"
            f"QMenu::item:selected {{ background-color: {ACCENT}; color: #fff; }}"
            f"QMenu::separator {{ height: 1px; background: {BORDER}; margin: 4px 8px; }}"
            f"QDialog {{ background: {BG_TABBAR}; color: {TEXT_PRI}; }}"
            f"QDialog QLabel {{ color: {TEXT_PRI}; }}"
            f"QDialog QLineEdit {{ background: {BG_CARD}; color: {TEXT_PRI}; border: 1px solid {BORDER};"
            f"                    border-radius: 6px; padding: 4px 8px; }}"
            f"QDialog QPushButton {{ background: {BG_CARD}; color: {TEXT_PRI}; padding: 4px 14px;"
            f"                       border: 1px solid {BORDER}; border-radius: 6px; }}"
            f"QDialog QPushButton:hover {{ background: {ACCENT}; color: #fff; border-color: {ACCENT}; }}"
            f"QToolTip {{ background: {BG_CARD}; color: {TEXT_PRI}; border: 1px solid {BORDER};"
            f"            padding: 4px 8px; border-radius: 4px; }}"
        )

        self._tabs: List[GameTab] = storage.load()
        self._grids: List[GameGrid] = []

        self._favorites_tab = GameTab(
            name=FAVORITES_NAME,
            games=[g for tab in self._tabs for g in tab.games if g.favorited],
        )
        self._favorites_grid: Optional[GameGrid] = None

        # Tab widget — no native tab bar; WrapTabBar renders tabs instead
        self._tab_widget = QTabWidget()
        self._tab_widget.setTabsClosable(False)
        self._tab_widget.setMovable(False)
        self._tab_widget.tabBar().hide()
        self._tab_widget.setStyleSheet(
            f"QTabWidget::pane {{ border: none; background: {BG}; }}"
        )
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        # Wrapping tab bar (custom, placed above QTabWidget)
        self._wrap_tab_bar = WrapTabBar()
        self._wrap_tab_bar.tab_clicked.connect(self._tab_widget.setCurrentIndex)
        self._wrap_tab_bar.tab_right_clicked.connect(self._on_wrap_tab_right_click)
        self._wrap_tab_bar.tab_reordered.connect(self._on_tabs_reordered)

        self._highlighted_card: Optional[GameCard] = None
        self._search_popup = SearchPopup()
        self._search_popup.result_selected.connect(self._on_search_result_selected)

        self._build_ui()
        self._search_popup.cancelled.connect(self._search_bar.clear)
        # App-level filter: dismiss popup when user clicks anywhere outside it
        QApplication.instance().installEventFilter(self)

    # ------------------------------------------------------------------
    # Build UI
    # ------------------------------------------------------------------

    def _build_ui(self):
        # Toolbar
        toolbar = QToolBar("Actions")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)

        for label, slot in [
            ("+ Add Game", self._add_game_via_dialog),
            ("+ Add Tab",  self._add_tab),
            ("Rename Tab", self._rename_tab),
            ("Delete Tab", self._delete_tab),
            ("Settings",   self._open_settings),
            ("About",      self._show_about),
        ]:
            action = QAction(label, self)
            action.triggered.connect(slot)
            toolbar.addAction(action)

        # Search bar right-aligned in toolbar
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        toolbar.addWidget(spacer)

        self._search_bar = QLineEdit()
        self._search_bar.setPlaceholderText("🔍  Search game...")
        self._search_bar.setFixedWidth(220)
        self._search_bar.setFixedHeight(28)
        self._search_bar.setStyleSheet(
            f"QLineEdit {{ background: {BG_CARD}; color: {TEXT_PRI}; border: 1px solid {BORDER};"
            f"            border-radius: 14px; padding: 2px 14px; font-size: 12px; }}"
            f"QLineEdit:focus {{ border-color: {ACCENT}; }}"
        )
        self._search_bar.textChanged.connect(self._on_search_text_changed)
        toolbar.addWidget(self._search_bar)

        # Container: WrapTabBar on top, QTabWidget (content) below
        container = QWidget()
        container.setStyleSheet(f"background: {BG};")
        vbox = QVBoxLayout(container)
        vbox.setContentsMargins(0, 0, 0, 0)
        vbox.setSpacing(0)
        vbox.addWidget(self._wrap_tab_bar)
        vbox.addWidget(self._tab_widget)

        self.setCentralWidget(container)
        self._populate_tabs()

    def _populate_tabs(self):
        self._tab_widget.blockSignals(True)
        self._tab_widget.clear()
        self._grids.clear()

        # Index 0: Favorites (pinned)
        self._favorites_grid = GameGrid(self._favorites_tab, self, is_favorites=True)
        self._tab_widget.addTab(self._favorites_grid, FAVORITES_NAME)

        # Index 1..N: Regular tabs
        for tab in self._tabs:
            grid = GameGrid(tab, self)
            self._grids.append(grid)
            self._tab_widget.addTab(grid, tab.name)

        # Last index: "＋" pseudo-tab for adding new tabs
        self._tab_widget.addTab(QWidget(), _PLUS_TAB)

        self._tab_widget.blockSignals(False)
        self._rebuild_wrap_tab_bar()

    def _plus_tab_idx(self) -> int:
        return self._tab_widget.count() - 1

    def _rebuild_wrap_tab_bar(self) -> None:
        current = self._tab_widget.currentIndex()
        names = [self._tab_widget.tabText(i) for i in range(self._tab_widget.count())]
        self._wrap_tab_bar.rebuild(names, current, self._plus_tab_idx())

    # ------------------------------------------------------------------
    # Tab right-click context menu (from WrapTabBar)
    # ------------------------------------------------------------------

    def eventFilter(self, obj, event):
        if (event.type() == QEvent.Type.MouseButtonPress
                and hasattr(self, '_search_popup')
                and self._search_popup.isVisible()):
            gpos = event.globalPosition().toPoint()
            popup_rect = QRect(
                self._search_popup.mapToGlobal(QPoint(0, 0)),
                self._search_popup.size(),
            )
            if not popup_rect.contains(gpos):
                self._search_popup.dismiss()
        return super().eventFilter(obj, event)

    def _on_tabs_reordered(self, from_idx: int, to_idx: int) -> None:
        real_from = from_idx - 1
        real_to = to_idx - 1
        self._tabs.insert(real_to, self._tabs.pop(real_from))
        self._grids.insert(real_to, self._grids.pop(real_from))
        self._tab_widget.blockSignals(True)
        self._tab_widget.tabBar().moveTab(from_idx, to_idx)
        self._tab_widget.setCurrentIndex(to_idx)
        self._tab_widget.blockSignals(False)
        self._rebuild_wrap_tab_bar()
        self.save()

    def _on_wrap_tab_right_click(self, idx: int) -> None:
        if 0 < idx < self._plus_tab_idx():
            menu = QMenu(self)
            rename_action = QAction("Rename Tab", self)
            rename_action.triggered.connect(lambda: self._rename_tab(idx))
            menu.addAction(rename_action)
            delete_action = QAction("Delete Tab", self)
            delete_action.triggered.connect(lambda: self._delete_tab_at(idx))
            menu.addAction(delete_action)
            menu.exec(self._wrap_tab_bar.cursor().pos())

    # ------------------------------------------------------------------
    # Tab change — intercept "＋" pseudo-tab
    # ------------------------------------------------------------------

    def _clear_search_highlight(self) -> None:
        if self._highlighted_card is not None:
            self._highlighted_card.clear_highlight()
            self._highlighted_card = None

    def _on_tab_changed(self, idx: int) -> None:
        self._clear_search_highlight()
        if idx == self._plus_tab_idx():
            self._tab_widget.blockSignals(True)
            self._tab_widget.setCurrentIndex(max(0, idx - 1))
            self._tab_widget.blockSignals(False)
            self._add_tab()
            return
        self._rebuild_wrap_tab_bar()

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
                    results.append((item, tab.name, i + 1))
        if results:
            self._search_popup.populate(results, self._search_bar)
        else:
            self._search_popup.hide()

    def _on_search_result_selected(self, data: tuple) -> None:
        item, tab_widget_idx = data
        self._search_bar.clear()
        self._tab_widget.setCurrentIndex(tab_widget_idx)
        # Flush all pending layout/resize events so the scroll area geometry
        # is fully settled before we try to scroll and highlight.
        QApplication.processEvents()
        real_idx = tab_widget_idx - 1
        if 0 <= real_idx < len(self._grids):
            grid = self._grids[real_idx]
            card = next((c for c in grid._cards if c.item is item), None)
            if card:
                grid.scroll_to_card(card)
                self._clear_search_highlight()
                self._highlighted_card = card
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

        for grid in self._grids:
            for c in grid._cards:
                if c.item is item:
                    c.sync_star()
        for c in self._favorites_grid._cards:
            if c.item is item:
                c.sync_star()

        self.save()

    def _sync_card_titles(self, item: GameItem) -> None:
        for grid in [self._favorites_grid] + self._grids:
            for card in grid._cards:
                if card.item is item:
                    card._title_label.setText(item.title)

    def _refresh_card_everywhere(self, item: GameItem) -> None:
        for grid in [self._favorites_grid] + self._grids:
            card = next((c for c in grid._cards if c.item is item), None)
            if card:
                grid._refresh_card(card)

    # ------------------------------------------------------------------
    # Game management
    # ------------------------------------------------------------------

    def _open_settings(self):
        SettingsDialog(self).exec()

    def _show_about(self):
        QMessageBox.information(
            self, "About",
            "My Game Hub (ver. 1.3)\n\n"
            "A personal game launcher for organizing and launching your game library.\n\n"
            "© 2026 RL. All rights reserved.\n"
            "Contact: kula009@gmail.com",
        )

    def _add_game_via_dialog(self):
        idx = self._tab_widget.currentIndex()
        if idx == 0 or idx == self._plus_tab_idx():
            QMessageBox.information(self, "Info", "Switch to a regular tab to add games.")
            return
        real_idx = idx - 1
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Select Game Executable or Shortcut", "", "Games (*.exe *.lnk *.url)",
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
                self, "Unsupported file",
                f"{skipped} file(s) skipped. Only .exe, .lnk, and Steam .url files are supported.",
            )

    # ------------------------------------------------------------------
    # Tab management
    # ------------------------------------------------------------------

    def _add_tab(self):
        name, ok = QInputDialog.getText(self, "New Tab", "Tab name:")
        if not ok or not name.strip():
            self._rebuild_wrap_tab_bar()
            return
        name = name.strip()
        if name.lower() in [t.name.lower() for t in self._tabs]:
            QMessageBox.warning(self, "Duplicate Tab", f'A tab named "{name}" already exists.')
            self._rebuild_wrap_tab_bar()
            return
        new_tab = GameTab(name=name)
        self._tabs.append(new_tab)
        grid = GameGrid(new_tab, self)
        self._grids.append(grid)
        insert_pos = self._plus_tab_idx()
        self._tab_widget.insertTab(insert_pos, grid, new_tab.name)
        self._tab_widget.setCurrentIndex(insert_pos)
        self._rebuild_wrap_tab_bar()
        self.save()

    def _rename_tab(self, idx: int = -1):
        if idx < 0:
            idx = self._tab_widget.currentIndex()
        if idx == 0 or idx == self._plus_tab_idx():
            QMessageBox.information(self, "Info", "This tab cannot be renamed.")
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
        self._rebuild_wrap_tab_bar()
        self.save()

    def _delete_tab(self):
        idx = self._tab_widget.currentIndex()
        self._delete_tab_at(idx)

    def _delete_tab_at(self, idx: int):
        if idx == 0 or idx == self._plus_tab_idx():
            QMessageBox.information(self, "Info", "This tab cannot be deleted.")
            return
        real_idx = idx - 1
        tab = self._tabs[real_idx]
        reply = QMessageBox.question(
            self, "Delete Tab",
            f'Delete tab "{tab.name}" and all its games?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
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
            self._tab_widget.blockSignals(True)
            self._tab_widget.removeTab(idx)
            new_idx = max(0, idx - 1)
            self._tab_widget.setCurrentIndex(new_idx)
            self._tab_widget.blockSignals(False)
            self._rebuild_wrap_tab_bar()
            self.save()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self):
        storage.save(self._tabs)
