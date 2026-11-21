"""Dialog for adding many links at once."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLineEdit, QPlainTextEdit, QVBoxLayout, QWidget,
)

from app.config import Settings
from app.media_info import all_urls
from ui.widgets import ScrollSafeComboBox, make_label, primary_button, secondary_button

PRESETS: dict[str, tuple[str, int | None, str]] = {
    # label: (kind, max height, audio format)
    "Video · best quality": ("video", None, "MP3"),
    "Video · up to 1080p": ("video", 1080, "MP3"),
    "Video · up to 720p": ("video", 720, "MP3"),
    "Video · up to 480p": ("video", 480, "MP3"),
    "Audio · MP3": ("audio", None, "MP3"),
    "Audio · M4A": ("audio", None, "M4A"),
}


@dataclass(slots=True)
class BatchChoice:
    urls: list[str]
    kind: str
    height: int | None
    audio_format: str
    output_dir: str
    allow_playlists: bool = True   # False: playlist links are skipped (used by clipboard auto-queue)
    quiet: bool = False            # True: no error dialog; the result is summarised on Home


class BatchDialog(QDialog):
    """Paste several links, pick one preset for all of them, and add them to the queue."""

    def __init__(self, settings: Settings, parent: QWidget | None = None, text: str = "") -> None:
        super().__init__(parent)
        self.setWindowTitle("Add several links")
        self.setMinimumWidth(560)
        self.settings = settings
        self.choice: BatchChoice | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 20, 22, 20)
        lay.setSpacing(12)
        lay.addWidget(make_label("Add several links", "CardTitle"))
        lay.addWidget(make_label(
            "Paste one link per line. Each link is checked, then added to the queue with the settings below. "
            "Playlist links are added as whole playlists.", "Dim", wrap=True))
        self.text = QPlainTextEdit()
        self.text.setPlaceholderText("https://…\nhttps://…")
        self.text.setMinimumHeight(150)
        self.text.setPlainText(text)
        lay.addWidget(self.text)
        self.count = make_label("", "Dim")
        lay.addWidget(self.count)

        row = QHBoxLayout()
        row.addWidget(make_label("Download as", "Dim"))
        self.preset = ScrollSafeComboBox()
        self.preset.addItems(list(PRESETS))
        row.addWidget(self.preset, 1)
        lay.addLayout(row)

        folder_row = QHBoxLayout()
        self.folder = QLineEdit(settings.download_dir)
        browse = secondary_button("Browse…", "folder")
        folder_row.addWidget(self.folder, 1)
        folder_row.addWidget(browse)
        lay.addLayout(folder_row)

        self.error = make_label("", "Dim", wrap=True)
        self.error.setProperty("state", "bad")
        self.error.hide()
        lay.addWidget(self.error)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.cancel_btn = secondary_button("Cancel")
        self.add_btn = primary_button("Add to queue")
        buttons.addWidget(self.cancel_btn)
        buttons.addWidget(self.add_btn)
        lay.addLayout(buttons)

        self.text.textChanged.connect(self._update_count)
        browse.clicked.connect(self._browse)
        self.cancel_btn.clicked.connect(self.reject)
        self.add_btn.clicked.connect(self._accept)
        self._update_count()

    def _update_count(self) -> None:
        n = len(all_urls(self.text.toPlainText()))
        self.count.setText(f"{n} link{'s' if n != 1 else ''} found" if n else "No links found yet")
        self.add_btn.setEnabled(n > 0)

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose download folder", self.folder.text())
        if path:
            self.folder.setText(path)

    def _accept(self) -> None:
        urls = all_urls(self.text.toPlainText())
        if not urls:
            return
        folder = self.folder.text().strip()
        if not folder:
            self.error.setText("Choose a download folder.")
            self.error.show()
            return
        kind, height, fmt = PRESETS[self.preset.currentText()]
        self.choice = BatchChoice(urls, kind, height, fmt, folder)
        self.accept()
