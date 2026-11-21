"""Left navigation sidebar."""

from __future__ import annotations

from enum import IntEnum

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QVBoxLayout, QWidget

from app.config import APP_VERSION
from ui.widgets import IconPushButton, make_label, logo_pixmap
from PySide6.QtWidgets import QLabel


class Page(IntEnum):
    """Page indices in the main stacked widget."""

    HOME = 0
    DOWNLOADS = 1
    QUEUE = 2
    HISTORY = 3
    SETTINGS = 4
    ABOUT = 5


class NavButton(IconPushButton):
    """Checkable sidebar button whose icon follows its checked state."""

    def __init__(self, text: str, icon_name: str):
        super().__init__(text, icon_name, role="text_dim", object_name="NavButton", icon_size=20)
        self.setCheckable(True)
        self.toggled.connect(self.refresh_icon)

    def icon_role(self) -> str:
        return "accent" if self.isChecked() else "text_dim"


class Sidebar(QFrame):
    """Vertical navigation with brand header and version footer."""

    page_requested = Signal(int)

    ITEMS: tuple[tuple[str, str], ...] = (
        ("Home", "home"),
        ("Downloads", "download"),
        ("Queue", "queue"),
        ("History", "history"),
        ("Settings", "settings"),
        ("About", "info"),
    )

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(232)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 20, 14, 14)
        layout.setSpacing(4)

        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 0)
        brand.setSpacing(10)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(36))
        logo.setFixedSize(36, 36)
        names = QVBoxLayout()
        names.setSpacing(0)
        names.addWidget(make_label("Quanttum", "BrandName"))
        names.addWidget(make_label("Downloader", "BrandSub"))
        brand.addWidget(logo)
        brand.addLayout(names)
        brand.addStretch(1)
        layout.addLayout(brand)
        layout.addSpacing(22)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: list[NavButton] = []
        for index, (text, icon) in enumerate(self.ITEMS):
            button = NavButton(text, icon)
            self._group.addButton(button, index)
            self._buttons.append(button)
            layout.addWidget(button)
        self._group.idClicked.connect(self.page_requested)

        layout.addStretch(1)
        layout.addWidget(make_label(f"Version {APP_VERSION}", "SidebarFooter"))

    def set_current(self, index: int) -> None:
        """Highlight the button for ``index`` without emitting a request."""
        self._buttons[index].setChecked(True)
