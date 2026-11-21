"""Home dashboard: URL entry, drag-and-drop, clipboard detection, media analysis preview."""

from __future__ import annotations

from PySide6.QtCore import QThreadPool, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QGuiApplication, QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QLineEdit, QStackedLayout, QVBoxLayout, QWidget,
)

from app.config import Settings, get_ytdlp_version, resolve_ffmpeg
from app.manager import DownloadManager
from app.media_info import (
    MediaInfo, first_url, format_duration, host_of, is_valid_url, normalise_url, shorten,
)
from app.signals import signals
from app.workers import AnalyseSignals, AnalyseWorker
from ui.options_panel import OptionsPanel
from ui.sidebar import Page
from ui.widgets import (
    BasePage, Card, EmptyState, IconLabel, IconPushButton, ThumbnailLabel, ghost_button,
    logo_pixmap, make_label, primary_button, repolish, secondary_button,
)

INVALID_URL_MESSAGE = (
    "That doesn't look like a valid link. Paste a full address, "
    "for example https://www.youtube.com/watch?v=…"
)
MISSING_YTDLP_MESSAGE = "yt-dlp isn't installed. Run: pip install -U yt-dlp"


class PreviewCard(Card):
    """Shows the analysed media (thumbnail, title, channel, duration, qualities)."""

    def __init__(self) -> None:
        super().__init__(shadow=True)
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._empty = EmptyState(
            "video", "Nothing analysed yet",
            "Paste a link above and press Analyse to preview the title, "
            "thumbnail and available formats.",
        )
        self._stack.addWidget(self._empty)

        details = QWidget()
        row = QHBoxLayout(details)
        row.setContentsMargins(22, 20, 22, 20)
        row.setSpacing(22)
        self.thumb = ThumbnailLabel(288, 162)
        row.addWidget(self.thumb, 0)

        col = QVBoxLayout()
        col.setSpacing(8)
        self.title = make_label("", "MediaTitle", wrap=True)
        self.channel = make_label("", "Subtitle")
        self.chips = QHBoxLayout()
        self.chips.setSpacing(8)
        self.formats_title = make_label("", "Dim", wrap=True)
        self.formats = QHBoxLayout()
        self.formats.setSpacing(8)
        col.addWidget(self.title)
        col.addWidget(self.channel)
        col.addLayout(self.chips)
        col.addSpacing(6)
        col.addWidget(self.formats_title)
        col.addLayout(self.formats)
        col.addStretch(1)
        row.addLayout(col, 1)
        self._stack.addWidget(details)

    @staticmethod
    def _fill_chips(layout: QHBoxLayout, items: list[tuple[str, str]]) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for text, state in items:
            chip = make_label(text, "Chip")
            chip.setProperty("state", state)
            repolish(chip)
            layout.addWidget(chip)
        layout.addStretch(1)

    def show_empty(self) -> None:
        self._stack.setCurrentIndex(0)

    def show_loading(self, url: str) -> None:
        """Analysis in progress."""
        self.thumb.set_pixmap(None)
        self.title.setText(shorten(url, 80))
        self.channel.setText(host_of(url))
        self._fill_chips(self.chips, [("Analysing…", "")])
        self.formats_title.setText("Fetching title, thumbnail and available formats.")
        self._fill_chips(self.formats, [])
        self._stack.setCurrentIndex(1)

    def show_media(self, info: MediaInfo, thumbnail: QPixmap | None = None) -> None:
        """Display analysed media information."""
        self.thumb.set_pixmap(thumbnail)
        self.title.setText(info.title)
        self.channel.setText(info.channel or host_of(info.url))

        chips: list[tuple[str, str]] = []
        if info.is_playlist:
            chips.append((f"Playlist · {info.entry_count} videos", ""))
        else:
            chips.append((format_duration(info.duration_seconds), ""))
            if info.has_audio:
                chips.append(("Audio available", "ok"))
            if info.subtitle_langs:
                n = len(info.subtitle_langs)
                chips.append((f"{n} subtitle language{'s' if n != 1 else ''}", ""))
        self._fill_chips(self.chips, chips)

        if info.is_playlist:
            self.formats_title.setText("Quality is chosen per video when the playlist is downloaded.")
            self._fill_chips(self.formats, [])
        elif info.video_heights:
            self.formats_title.setText("Available video qualities")
            self._fill_chips(self.formats, [(f"{h}p", "") for h in info.video_heights])
        else:
            self.formats_title.setText("No video streams — this is an audio-only source.")
            self._fill_chips(self.formats, [])
        self._stack.setCurrentIndex(1)


class HomePage(BasePage):
    """Landing page: paste a link, analyse it, preview the result."""

    analysed = Signal(object)  # MediaInfo

    def __init__(self, settings: Settings, manager: DownloadManager) -> None:
        super().__init__()
        self.settings = settings
        self.manager = manager
        self._thumb_pixmap: QPixmap | None = None
        self._dismissed: set[str] = set()
        self._clipboard_url = ""
        self._token = 0
        self.current_media: MediaInfo | None = None
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._worker_signals = AnalyseSignals(self)
        self._worker_signals.finished.connect(self._on_analysis_done)
        self._worker_signals.failed.connect(self._on_analysis_failed)
        self.setAcceptDrops(True)

        # header
        header = QHBoxLayout()
        header.setSpacing(14)
        logo = QLabel()
        logo.setPixmap(logo_pixmap(48))
        logo.setFixedSize(48, 48)
        titles = QVBoxLayout()
        titles.setSpacing(0)
        titles.addWidget(make_label("Quanttum Downloader", "Title"))
        titles.addWidget(make_label("Save videos and audio you are authorised to download.", "Subtitle"))
        header.addWidget(logo)
        header.addLayout(titles, 1)
        self.body.addLayout(header)

        # clipboard banner
        self.banner = QFrame()
        self.banner.setObjectName("Banner")
        banner_row = QHBoxLayout(self.banner)
        banner_row.setContentsMargins(14, 8, 8, 8)
        banner_row.setSpacing(10)
        banner_row.addWidget(IconLabel("clipboard", 18, "accent"))
        self.banner_text = QLabel()
        banner_row.addWidget(self.banner_text, 1)
        use_btn = secondary_button("Use link")
        use_btn.clicked.connect(self._use_clipboard_link)
        dismiss_btn = IconPushButton("", "close", role="text_dim", object_name="IconOnly", icon_size=16)
        dismiss_btn.setToolTip("Dismiss")
        dismiss_btn.clicked.connect(self._dismiss_banner)
        banner_row.addWidget(use_btn)
        banner_row.addWidget(dismiss_btn)
        self.banner.hide()
        self.body.addWidget(self.banner)

        # URL card
        hero = Card(shadow=True)
        hero_lay = QVBoxLayout(hero)
        hero_lay.setContentsMargins(22, 20, 22, 18)
        hero_lay.setSpacing(12)
        hero_lay.addWidget(make_label("Paste a link", "CardTitle"))
        url_row = QHBoxLayout()
        url_row.setSpacing(10)
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://www.youtube.com/watch?v=…")
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self._on_analyse)
        self.url_input.textChanged.connect(lambda _t: self._set_error(""))
        paste_btn = secondary_button("Paste", "paste")
        paste_btn.clicked.connect(self._on_paste)
        self.analyse_btn = primary_button("Analyse", "search")
        self.analyse_btn.clicked.connect(self._on_analyse)
        url_row.addWidget(self.url_input, 1)
        url_row.addWidget(paste_btn)
        url_row.addWidget(self.analyse_btn)
        hero_lay.addLayout(url_row)
        self.error_label = make_label("", "Error", wrap=True)
        self.error_label.hide()
        hero_lay.addWidget(self.error_label)
        hero_lay.addWidget(make_label(
            "Tip: drag a link onto this window, or copy one and we'll offer to use it.", "Dim"))
        self.body.addWidget(hero)

        # preview
        self.preview = PreviewCard()
        self.body.addWidget(self.preview)

        # download options (appear after a successful analysis)
        self.options = OptionsPanel(settings)
        self.options.download_requested.connect(self._on_download_requested)
        self.body.addWidget(self.options)

        # environment status
        env = Card()
        env_row = QHBoxLayout(env)
        env_row.setContentsMargins(22, 14, 18, 14)
        env_row.setSpacing(10)
        env_row.addWidget(make_label("Environment", "RowTitle"))
        self.ffmpeg_chip = make_label("", "Chip")
        self.ytdlp_chip = make_label("", "Chip")
        env_row.addWidget(self.ffmpeg_chip)
        env_row.addWidget(self.ytdlp_chip)
        env_row.addStretch(1)
        open_settings = ghost_button("Open settings", "settings")
        open_settings.clicked.connect(lambda: signals.navigate.emit(int(Page.SETTINGS)))
        env_row.addWidget(open_settings)
        self.body.addWidget(env)
        self.body.addStretch(1)

        self.refresh_environment()
        signals.setting_changed.connect(self._on_setting_changed)
        QGuiApplication.clipboard().dataChanged.connect(self._check_clipboard)

    # -- environment -------------------------------------------------------
    def refresh_environment(self) -> None:
        ffmpeg = resolve_ffmpeg(self.settings.ffmpeg_path)
        self.ffmpeg_chip.setText("FFmpeg ready" if ffmpeg else "FFmpeg not found")
        self.ffmpeg_chip.setProperty("state", "ok" if ffmpeg else "bad")
        self.ffmpeg_chip.setToolTip(str(ffmpeg) if ffmpeg else "Needed for merging video/audio and MP3 conversion.")
        version = get_ytdlp_version()
        self.ytdlp_chip.setText(f"yt-dlp {version}" if version else "yt-dlp not installed")
        self.ytdlp_chip.setProperty("state", "ok" if version else "bad")
        repolish(self.ffmpeg_chip)
        repolish(self.ytdlp_chip)

    def _on_setting_changed(self, key: str, _value: object) -> None:
        if key == "ffmpeg_path":
            self.refresh_environment()
        elif key == "clipboard_detection" and not self.settings.clipboard_detection:
            self.banner.hide()

    # -- URL handling ------------------------------------------------------
    def _set_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    def set_url(self, text: str, analyse: bool = False) -> None:
        self.url_input.setText(text)
        if analyse:
            self._on_analyse()

    def _on_paste(self) -> None:
        text = QGuiApplication.clipboard().text().strip()
        if not text:
            self._set_error("Your clipboard is empty.")
            return
        self.url_input.setText(first_url(text) or text[:2048])
        self.url_input.setFocus()

    def _on_analyse(self) -> None:
        url = normalise_url(self.url_input.text())
        if not url or not is_valid_url(url):
            self._set_error(INVALID_URL_MESSAGE)
            return
        if get_ytdlp_version() is None:
            self._set_error(MISSING_YTDLP_MESSAGE)
            return
        self._set_error("")
        self.url_input.setText(url)
        self.banner.hide()
        self.current_media = None
        self.options.hide()
        self._token += 1
        self.preview.show_loading(url)
        self.analyse_btn.setEnabled(False)
        self.analyse_btn.setText("Analysing…")
        self._pool.start(AnalyseWorker(url, self._token, self._worker_signals))
        signals.url_submitted.emit(url)

    def _finish_busy(self) -> None:
        self.analyse_btn.setEnabled(True)
        self.analyse_btn.setText("Analyse")

    def _on_analysis_done(self, token: int, info: MediaInfo, thumb_bytes: object) -> None:
        if token != self._token:  # superseded by a newer request
            return
        self._finish_busy()
        pixmap = None
        if thumb_bytes:
            pixmap = QPixmap()
            if not pixmap.loadFromData(thumb_bytes):
                pixmap = None
        self.current_media = info
        self._thumb_pixmap = pixmap
        self.preview.show_media(info, pixmap)
        self.options.set_media(info, pixmap)
        self.analysed.emit(info)

    def _on_analysis_failed(self, token: int, message: str) -> None:
        if token != self._token:
            return
        self._finish_busy()
        self.preview.show_empty()
        self.options.hide()
        self._set_error(message)

    def _on_download_requested(self, request: object, thumbnail: object, start_now: bool) -> None:
        self.manager.add(request, thumbnail, start_now)  # type: ignore[arg-type]
        if start_now:
            signals.navigate.emit(int(Page.DOWNLOADS))
        else:
            position = len(self.manager.queue_jobs())
            self.options.show_queued(position)

    def shutdown(self) -> None:
        """Stop accepting work and wait briefly for the worker to finish."""
        self._token += 1  # discard any in-flight result
        self._pool.clear()
        self._pool.waitForDone(3000)

    # -- clipboard detection ----------------------------------------------
    def _check_clipboard(self) -> None:
        if not self.settings.clipboard_detection:
            return
        url = first_url(QGuiApplication.clipboard().text())
        if not url or url in self._dismissed or url == self.url_input.text().strip():
            return
        self._clipboard_url = url
        self.banner_text.setText(f"Link on your clipboard: {shorten(url, 64)}")
        self.banner.show()

    def _use_clipboard_link(self) -> None:
        self._dismissed.add(self._clipboard_url)
        self.banner.hide()
        self.set_url(self._clipboard_url)

    def _dismiss_banner(self) -> None:
        self._dismissed.add(self._clipboard_url)
        self.banner.hide()

    def showEvent(self, event: object) -> None:  # noqa: N802
        super().showEvent(event)
        self._check_clipboard()

    # -- drag and drop -----------------------------------------------------
    def dragEnterEvent(self, event: QDragEnterEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        if mime.hasUrls() or mime.hasText():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:  # noqa: N802
        mime = event.mimeData()
        text = mime.urls()[0].toString() if mime.hasUrls() else mime.text()
        url = first_url(text) or text.strip()
        if url:
            event.acceptProposedAction()
            self.set_url(url, analyse=True)
