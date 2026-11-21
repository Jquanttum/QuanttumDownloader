"""Reusable themed widgets: icons, cards, toggle switch, thumbnail, page scaffold."""

from __future__ import annotations

import math

from PySide6.QtCore import QMimeData, QPoint, QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (
    QBrush, QColor, QDrag, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QAbstractButton, QApplication, QButtonGroup, QComboBox, QFrame, QGraphicsDropShadowEffect, QHBoxLayout, QLabel,
    QPushButton, QScrollArea, QSizePolicy, QVBoxLayout, QWidget,
)

from app.signals import signals
from ui.styles import get_palette

# --------------------------------------------------------------------------
# Vector icons (24x24 canvas, stroked paths)
# --------------------------------------------------------------------------
def _arc(cx: float, cy: float, r: float, a0: float, a1: float, n: int = 16) -> list[tuple[float, float]]:
    """Points along a circular arc (degrees, screen coordinates)."""
    return [
        (cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
         cy + r * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
        for i in range(n + 1)
    ]


_ICONS: dict[str, list[tuple]] = {
    "home": [
        ("poly", [(3, 11), (12, 3), (21, 11)], False),
        ("poly", [(5.5, 9.5), (5.5, 20.5), (18.5, 20.5), (18.5, 9.5)], False),
        ("poly", [(10, 20.5), (10, 15), (14, 15), (14, 20.5)], False),
    ],
    "download": [
        ("poly", [(12, 4), (12, 15)], False),
        ("poly", [(7, 10.5), (12, 15.5), (17, 10.5)], False),
        ("poly", [(5, 20), (19, 20)], False),
    ],
    "queue": [
        ("poly", [(4, 6), (20, 6)], False),
        ("poly", [(4, 12), (20, 12)], False),
        ("poly", [(4, 18), (12, 18)], False),
        ("poly", [(16, 15.5), (16, 20.5), (20.5, 18)], True),
    ],
    "history": [
        ("circle", 12, 12, 8.5),
        ("poly", [(12, 7), (12, 12), (15.5, 14)], False),
    ],
    "settings": [
        ("poly", [(4, 8), (20, 8)], False),
        ("poly", [(4, 16), (20, 16)], False),
        ("circle", 9, 8, 2.4),
        ("circle", 15, 16, 2.4),
    ],
    "info": [
        ("circle", 12, 12, 9),
        ("poly", [(12, 11), (12, 16.5)], False),
        ("dot", 12, 7.8, 1.1),
    ],
    "paste": [("rrect", 5.5, 5, 13, 16, 2.5), ("rrect", 9, 3, 6, 4, 1.5)],
    "clipboard": [("rrect", 5.5, 5, 13, 16, 2.5), ("rrect", 9, 3, 6, 4, 1.5)],
    "search": [("circle", 10.5, 10.5, 6.5), ("poly", [(15.3, 15.3), (20, 20)], False)],
    "folder": [("poly", [(3, 7), (10, 7), (12, 9.5), (21, 9.5), (21, 19), (3, 19)], True)],
    "check": [("poly", [(5, 12.5), (10, 17.5), (19, 7)], False)],
    "close": [("poly", [(6, 6), (18, 18)], False), ("poly", [(18, 6), (6, 18)], False)],
    "image": [
        ("rrect", 3, 5, 18, 14, 2.5),
        ("circle", 8.5, 10, 1.6),
        ("poly", [(3.5, 17), (9, 12.5), (13, 16), (16, 13.5), (20.5, 17.5)], False),
    ],
    "video": [
        ("rrect", 3, 6, 13, 12, 2.5),
        ("poly", [(16, 10.5), (21, 7.5), (21, 16.5), (16, 13.5)], True),
    ],
    "grip": [("dot", x, y, 1.6) for x in (9, 15) for y in (6, 12, 18)],
    "up": [("poly", [(12, 19), (12, 6)], False), ("poly", [(6.5, 11.5), (12, 6), (17.5, 11.5)], False)],
    "down": [("poly", [(12, 5), (12, 18)], False), ("poly", [(6.5, 12.5), (12, 18), (17.5, 12.5)], False)],
    "pause": [("poly", [(9, 6), (9, 18)], False), ("poly", [(15, 6), (15, 18)], False)],
    "play": [("poly", [(8, 5.5), (18, 12), (8, 18.5)], True)],
    "retry": [
        ("poly", _arc(12, 12, 7.5, -50, 235), False),
        ("poly", [(12.2, 3.2), (16.2, 5.2), (12.6, 8.6)], False),
    ],
    "trash": [
        ("poly", [(4, 7), (20, 7)], False),
        ("poly", [(6, 7), (7.2, 20), (16.8, 20), (18, 7)], False),
        ("poly", [(9, 7), (9, 4), (15, 4), (15, 7)], False),
    ],
    "open": [
        ("poly", [(14, 4), (20, 4), (20, 10)], False),
        ("poly", [(20, 4), (11, 13)], False),
        ("poly", [(18, 14), (18, 19), (5, 19), (5, 6), (10, 6)], False),
    ],
}

_DPR = 2.0


def make_pixmap(name: str, color: str, size: int = 20) -> QPixmap:
    """Render the named icon in ``color`` at ``size`` logical pixels (crisp at 2x)."""
    pm = QPixmap(int(size * _DPR), int(size * _DPR))
    pm.setDevicePixelRatio(_DPR)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / 24, size / 24)
    pen = QPen(QColor(color), 1.9)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    for item in _ICONS[name]:
        kind = item[0]
        if kind == "poly":
            pts, closed = item[1], item[2]
            path = QPainterPath(QPointF(*pts[0]))
            for pt in pts[1:]:
                path.lineTo(QPointF(*pt))
            if closed:
                path.closeSubpath()
            p.drawPath(path)
        elif kind == "circle":
            p.drawEllipse(QPointF(item[1], item[2]), item[3], item[3])
        elif kind == "rrect":
            p.drawRoundedRect(QRectF(item[1], item[2], item[3], item[4]), item[5], item[5])
        elif kind == "dot":
            p.save()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(color))
            p.drawEllipse(QPointF(item[1], item[2]), item[3], item[3])
            p.restore()
    p.end()
    return pm


def logo_pixmap(size: int = 40) -> QPixmap:
    """The Quanttum logo: gradient rounded square with a download arrow."""
    pm = QPixmap(int(size * _DPR), int(size * _DPR))
    pm.setDevicePixelRatio(_DPR)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, size, size)
    grad.setColorAt(0, QColor("#4C8DFF"))
    grad.setColorAt(1, QColor("#8B5CF6"))
    p.setBrush(QBrush(grad))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.28, size * 0.28)
    p.scale(size / 24, size / 24)
    pen = QPen(QColor("#FFFFFF"), 2.2)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.BrushStyle.NoBrush)
    p.drawLine(QPointF(12, 5.5), QPointF(12, 14.5))
    arrow = QPainterPath(QPointF(8, 11))
    arrow.lineTo(QPointF(12, 15))
    arrow.lineTo(QPointF(16, 11))
    p.drawPath(arrow)
    p.drawLine(QPointF(6.5, 18.5), QPointF(17.5, 18.5))
    p.end()
    return pm


def repolish(widget: QWidget) -> None:
    """Re-apply the stylesheet after a dynamic property or object name changed."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)
    widget.update()


# --------------------------------------------------------------------------
# Labels and buttons
# --------------------------------------------------------------------------
def make_label(text: str, object_name: str = "", wrap: bool = False) -> QLabel:
    """Create a QLabel with an optional QSS object name and word wrap."""
    label = QLabel(text)
    if object_name:
        label.setObjectName(object_name)
    label.setWordWrap(wrap)
    return label


class IconLabel(QLabel):
    """A label showing a themed vector icon that recolours on theme change."""

    def __init__(self, name: str, size: int = 20, role: str = "text_dim", parent: QWidget | None = None):
        super().__init__(parent)
        self._name, self._size, self._role = name, size, role
        self.setFixedSize(size, size)
        signals.theme_changed.connect(self.refresh)
        self.refresh()

    def set_icon(self, name: str) -> None:
        self._name = name
        self.refresh()

    def refresh(self, *_: object) -> None:
        self.setPixmap(make_pixmap(self._name, get_palette()[self._role], self._size))


class IconPushButton(QPushButton):
    """A QPushButton with a themed vector icon."""

    def __init__(
        self, text: str = "", icon_name: str = "", role: str = "text",
        object_name: str = "", icon_size: int = 18, parent: QWidget | None = None,
    ):
        super().__init__(text, parent)
        self._icon_name, self._role, self._icon_size = icon_name, role, icon_size
        if object_name:
            self.setObjectName(object_name)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(icon_size, icon_size))
        signals.theme_changed.connect(self.refresh_icon)
        self.refresh_icon()

    def icon_role(self) -> str:
        """Palette token used to colour the icon (overridable)."""
        return self._role

    def refresh_icon(self, *_: object) -> None:
        if self._icon_name:
            pm = make_pixmap(self._icon_name, get_palette()[self.icon_role()], self._icon_size)
            self.setIcon(QIcon(pm))


def primary_button(text: str, icon: str = "") -> IconPushButton:
    return IconPushButton(text, icon, role="on_accent", object_name="Primary")


def secondary_button(text: str, icon: str = "") -> IconPushButton:
    return IconPushButton(text, icon, role="text", object_name="")


def ghost_button(text: str, icon: str = "") -> IconPushButton:
    return IconPushButton(text, icon, role="text_dim", object_name="Ghost")


# --------------------------------------------------------------------------
# Surfaces
# --------------------------------------------------------------------------
class Card(QFrame):
    """A rounded surface; optionally with a soft drop shadow."""

    def __init__(self, shadow: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Card")
        if shadow:
            effect = QGraphicsDropShadowEffect(self)
            effect.setBlurRadius(24)
            effect.setOffset(0, 4)
            effect.setColor(QColor(0, 0, 0, 38))
            self.setGraphicsEffect(effect)


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFixedHeight(1)
    return line


class ToggleSwitch(QAbstractButton):
    """A painted on/off switch."""

    def __init__(self, checked: bool = False, parent: QWidget | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(44, 24)

    def sizeHint(self) -> QSize:
        return QSize(44, 24)

    def paintEvent(self, _event: object) -> None:
        pal = get_palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setOpacity(1.0 if self.isEnabled() else 0.4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal["accent"] if self.isChecked() else pal["toggle_off"]))
        p.drawRoundedRect(QRectF(0, 0, 44, 24), 12, 12)
        p.setBrush(QColor("#FFFFFF"))
        x = 23.0 if self.isChecked() else 3.0
        p.drawEllipse(QRectF(x, 3, 18, 18))
        p.end()


class ScrollSafeComboBox(QComboBox):
    """Combo box that lets the mouse wheel scroll the page unless it has keyboard focus."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self.hasFocus():
            super().wheelEvent(event)
        else:
            event.ignore()   # propagates to the scroll area


QUEUE_MIME = "application/x-quanttum-job"


class DragHandle(IconLabel):
    """Grip icon that starts a drag of its row (used to reorder the queue)."""

    def __init__(self, job_id: int, row: QWidget) -> None:
        super().__init__("grip", 20, "text_dim")
        self.job_id, self._row = job_id, row
        self._press: QPoint | None = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self.setToolTip("Drag to reorder")
        self.setFixedSize(22, 40)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._press = event.position().toPoint()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._press = None

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._press is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if (event.position().toPoint() - self._press).manhattanLength() < QApplication.startDragDistance():
            return
        self._press = None
        mime = QMimeData()
        mime.setData(QUEUE_MIME, str(self.job_id).encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        pixmap = self._row.grab()
        faded = QPixmap(pixmap.size())
        faded.setDevicePixelRatio(pixmap.devicePixelRatio())
        faded.fill(Qt.GlobalColor.transparent)
        painter = QPainter(faded)
        painter.setOpacity(0.75)
        painter.drawPixmap(0, 0, pixmap)
        painter.end()
        drag.setPixmap(faded)
        drag.setHotSpot(QPoint(24, faded.height() // (2 * max(1, int(faded.devicePixelRatio())))))
        drag.exec(Qt.DropAction.MoveAction)


class ElidedLabel(QLabel):
    """A single-line label that truncates long text in the middle and shows it fully as a tooltip."""

    def __init__(self, text: str = "", object_name: str = "", parent: QWidget | None = None):
        super().__init__(parent)
        if object_name:
            self.setObjectName(object_name)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setMinimumWidth(40)
        self._full = ""
        self.setText(text)

    def setText(self, text: str) -> None:  # noqa: N802
        self._full = text
        self.setToolTip(text)
        self._elide()

    def resizeEvent(self, event: object) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._elide()

    def _elide(self) -> None:
        shown = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideMiddle, max(10, self.width()))
        super().setText(shown)


class SegmentedControl(QFrame):
    """A pill-shaped exclusive choice, e.g. Video | Audio."""

    changed = Signal(int)

    def __init__(self, labels: list[str], parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("SegmentBar")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[QPushButton] = []
        for i, text in enumerate(labels):
            button = QPushButton(text)
            button.setObjectName("Segment")
            button.setCheckable(True)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            self._group.addButton(button, i)
            lay.addWidget(button)
            self._buttons.append(button)
        self._buttons[0].setChecked(True)
        self._group.idClicked.connect(self.changed)

    def current(self) -> int:
        return self._group.checkedId()

    def set_current(self, index: int) -> None:
        self._buttons[index].setChecked(True)
        self.changed.emit(index)

    def set_segment_enabled(self, index: int, enabled: bool) -> None:
        self._buttons[index].setEnabled(enabled)


class ThumbnailLabel(QWidget):
    """Rounded 16:9 thumbnail with a themed placeholder."""

    def __init__(self, width: int = 288, height: int = 162, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(width, height)
        self._pixmap: QPixmap | None = None
        signals.theme_changed.connect(lambda *_: self.update())

    def set_pixmap(self, pixmap: QPixmap | None) -> None:
        self._pixmap = pixmap if pixmap and not pixmap.isNull() else None
        self.update()

    def paintEvent(self, _event: object) -> None:
        pal = get_palette()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, 12, 12)
        p.setClipPath(clip)
        p.fillRect(rect, QColor(pal["thumb_bg"]))
        if self._pixmap:
            scaled = self._pixmap.scaled(
                self.size(), Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(QPointF((self.width() - scaled.width()) / 2, (self.height() - scaled.height()) / 2), scaled)
        else:
            icon = make_pixmap("image", pal["text_dim"], 40)
            p.drawPixmap(QPointF((self.width() - 40) / 2, (self.height() - 40) / 2), icon)
        p.setClipping(False)
        p.setPen(QPen(QColor(pal["border"]), 1))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), 12, 12)
        p.end()


class EmptyState(QWidget):
    """Centered icon + title + explanatory text."""

    def __init__(self, icon: str, title: str, text: str, parent: QWidget | None = None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 36, 20, 36)
        lay.setSpacing(8)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label = IconLabel(icon, 44, "text_dim")
        lay.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignHCenter)
        lay.addSpacing(6)
        heading = make_label(title, "CardTitle")
        heading.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        body = make_label(text, "Subtitle", wrap=True)
        body.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        # The wrapped text must get its width from the layout (not from its own size hint), otherwise
        # it collapses to a narrow column and its height is computed for the wrong width -> clipped.
        body.setMaximumWidth(440)
        body.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.MinimumExpanding)
        body_row = QHBoxLayout()
        body_row.setContentsMargins(0, 0, 0, 0)
        body_row.addStretch(1)
        body_row.addWidget(body, 100)
        body_row.addStretch(1)
        lay.addWidget(heading)
        lay.addLayout(body_row)
        self._heading, self._body = heading, body

    def set_texts(self, title: str, text: str) -> None:
        self._heading.setText(title)
        self._body.setText(text)


class BasePage(QWidget):
    """Scrollable, centered page with an optional title/subtitle header."""

    def __init__(self, title: str = "", subtitle: str = "", max_width: int = 980, parent: QWidget | None = None):
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setAutoFillBackground(False)
        outer.addWidget(scroll)

        content = QWidget()
        content.setObjectName("ScrollContent")
        row = QHBoxLayout(content)
        row.setContentsMargins(36, 30, 36, 30)
        column = QWidget()
        column.setMaximumWidth(max_width)
        row.addStretch(1)
        row.addWidget(column, 100)
        row.addStretch(1)
        scroll.setWidget(content)

        self.body = QVBoxLayout(column)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.body.setSpacing(18)
        if title:
            self.body.addWidget(make_label(title, "Title"))
            if subtitle:
                self.body.addWidget(make_label(subtitle, "Subtitle", wrap=True))
            self.body.addSpacing(4)


def setting_row(title: str, description: str, control: QWidget) -> QWidget:
    """A settings row: title + description on the left, control on the right."""
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 10, 0, 10)
    lay.setSpacing(20)
    text = QVBoxLayout()
    text.setSpacing(2)
    text.addWidget(make_label(title, "RowTitle"))
    if description:
        text.addWidget(make_label(description, "Dim", wrap=True))
    lay.addLayout(text, 1)
    lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
    return row
