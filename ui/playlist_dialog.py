"""Dialog for choosing which videos of a playlist to download."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QListWidget, QListWidgetItem, QVBoxLayout, QWidget

from app.media_info import format_duration
from ui.widgets import ghost_button, make_label, primary_button, secondary_button


def items_spec(selected: list[int], total: int) -> str:
    """yt-dlp ``playlist_items`` text for 1-based ``selected`` indices ("" when everything is selected)."""
    chosen = sorted(set(selected))
    if not chosen or len(chosen) >= total and chosen == list(range(1, total + 1)):
        return ""
    parts: list[str] = []
    start = prev = chosen[0]
    for n in chosen[1:] + [None]:  # type: ignore[list-item]
        if n is not None and n == prev + 1:
            prev = n
            continue
        parts.append(str(start) if start == prev else f"{start}-{prev}")
        if n is not None:
            start = prev = n
    return ",".join(parts)


class PlaylistDialog(QDialog):
    """Checklist of the playlist's videos."""

    def __init__(self, title: str, entries: list[tuple[str, int | None]], total: int,
                 selected: set[int] | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose videos")
        self.setMinimumSize(520, 520)
        self.total = total
        self.result_items: list[int] | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)
        lay.addWidget(make_label(title, "CardTitle", wrap=True))
        tools = QHBoxLayout()
        self.count = make_label("", "Dim")
        self.all_btn = ghost_button("Select all")
        self.none_btn = ghost_button("Select none")
        tools.addWidget(self.count, 1)
        tools.addWidget(self.all_btn)
        tools.addWidget(self.none_btn)
        lay.addLayout(tools)

        self.list = QListWidget()
        for index, (name, seconds) in enumerate(entries, 1):
            label = f"{index}. {name}" + (f"   ({format_duration(seconds)})" if seconds else "")
            item = QListWidgetItem(label)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if selected is None or index in selected
                               else Qt.CheckState.Unchecked)
            item.setData(Qt.ItemDataRole.UserRole, index)
            self.list.addItem(item)
        lay.addWidget(self.list, 1)
        if total > len(entries):
            lay.addWidget(make_label(
                f"Only the first {len(entries)} of {total} videos are listed here; the rest can't be chosen "
                "individually.", "Dim", wrap=True))

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_btn = secondary_button("Cancel")
        self.ok_btn = primary_button("Use selection")
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.ok_btn)
        lay.addLayout(buttons)

        self.list.itemChanged.connect(self._update)
        self.all_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        self.none_btn.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        self.cancel_btn.clicked.connect(self.reject)
        self.ok_btn.clicked.connect(self._accept)
        self._update()

    def checked(self) -> list[int]:
        return [self.list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.list.count())
                if self.list.item(i).checkState() == Qt.CheckState.Checked]

    def _set_all(self, state: Qt.CheckState) -> None:
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(state)
        self.list.blockSignals(False)
        self._update()

    def _update(self, *_: object) -> None:
        n = len(self.checked())
        self.count.setText(f"{n} of {self.list.count()} selected")
        self.ok_btn.setEnabled(n > 0)

    def _accept(self) -> None:
        self.result_items = self.checked()
        self.accept()
