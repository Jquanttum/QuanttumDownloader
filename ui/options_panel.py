"""Download options shown after a link has been analysed."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget,
)

from app.choices import parse_time
from app.config import AUDIO_FORMATS, VIDEO_QUALITIES, Settings, resolve_ffmpeg
from app.downloader import AUDIO_BITRATES, VIDEO_CONTAINERS, DownloadRequest
from app.media_info import MediaInfo
from app.signals import signals
from ui.playlist_dialog import PlaylistDialog, items_spec
from ui.widgets import (
    ScrollSafeComboBox,
    Card, SegmentedControl, ToggleSwitch, ghost_button, make_label, primary_button, repolish,
    secondary_button,
)

PLAYLIST_HEIGHTS = (2160, 1440, 1080, 720, 480, 360)
COMMON_SUBTITLES = ("en", "fr", "es", "de", "pt", "it", "ja", "ko", "ru", "zh-Hans", "ar", "hi")
LANGUAGE_NAMES = {
    "en": "English", "fr": "French", "es": "Spanish", "de": "German", "pt": "Portuguese",
    "it": "Italian", "ja": "Japanese", "ko": "Korean", "ru": "Russian", "zh-Hans": "Chinese (Simplified)",
    "zh-Hant": "Chinese (Traditional)", "ar": "Arabic", "hi": "Hindi", "nl": "Dutch", "pl": "Polish",
    "tr": "Turkish", "sv": "Swedish", "id": "Indonesian", "vi": "Vietnamese", "th": "Thai",
    "uk": "Ukrainian", "sw": "Swahili", "he": "Hebrew", "el": "Greek", "fa": "Persian",
}


def quality_label(height: int) -> str:
    return "2160p (4K)" if height == 2160 else f"{height}p"


def parse_default_height(label: str) -> int | None:
    """Convert a settings label such as ``1080p`` or ``Best available`` to a height cap."""
    digits = "".join(ch for ch in label.split("p")[0] if ch.isdigit())
    return int(digits) if digits and label != "Best available" else None


def _field(label: str, widget: QWidget) -> QWidget:
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(5)
    lay.addWidget(make_label(label, "Dim"))
    lay.addWidget(widget)
    return box


def _toggle_row(text: str, toggle: ToggleSwitch) -> QWidget:
    row = QWidget()
    lay = QHBoxLayout(row)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(10)
    lay.addWidget(toggle)
    lay.addWidget(make_label(text, ""))
    lay.addStretch(1)
    return row


class OptionsPanel(Card):
    """Choose video/audio, quality, format, subtitles and folder, then start the download."""

    download_requested = Signal(object, object, bool)  # DownloadRequest, QPixmap | None, start now

    def __init__(self, settings: Settings) -> None:
        super().__init__(shadow=True)
        self.s = settings
        self._info: MediaInfo | None = None
        self._thumb: QPixmap | None = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(14)

        head = QHBoxLayout()
        head.addWidget(make_label("Download options", "CardTitle"))
        head.addStretch(1)
        self.mode = SegmentedControl(["Video", "Audio"])
        self.mode.changed.connect(lambda _i: self._refresh())
        head.addWidget(self.mode)
        lay.addLayout(head)

        # video / audio specific fields
        self.quality = ScrollSafeComboBox()
        self.container = ScrollSafeComboBox()
        self.container.addItems(list(VIDEO_CONTAINERS))
        self.audio_fmt = ScrollSafeComboBox()
        self.audio_fmt.addItems(AUDIO_FORMATS)
        self.bitrate = ScrollSafeComboBox()
        for rate in AUDIO_BITRATES:
            self.bitrate.addItem(f"{rate} kbps", rate)
        self.bitrate.setCurrentIndex(1)

        self.video_box = QWidget()
        vl = QHBoxLayout(self.video_box)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(14)
        vl.addWidget(_field("Quality", self.quality), 1)
        vl.addWidget(_field("Format", self.container), 1)
        self.audio_box = QWidget()
        al = QHBoxLayout(self.audio_box)
        al.setContentsMargins(0, 0, 0, 0)
        al.setSpacing(14)
        al.addWidget(_field("Format", self.audio_fmt), 1)
        al.addWidget(_field("Audio quality", self.bitrate), 1)
        lay.addWidget(self.video_box)
        lay.addWidget(self.audio_box)

        # shared fields
        self.subs = ScrollSafeComboBox()
        self.folder = QLineEdit(settings.download_dir)
        self.folder.setReadOnly(True)
        self.folder.setToolTip(settings.download_dir)
        browse = secondary_button("Browse…", "folder")
        browse.clicked.connect(self._browse)
        folder_box = QWidget()
        fl = QHBoxLayout(folder_box)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(8)
        fl.addWidget(self.folder, 1)
        fl.addWidget(browse)
        row = QHBoxLayout()
        row.setSpacing(14)
        row.addWidget(_field("Subtitles", self.subs), 1)
        row.addWidget(_field("Save to", folder_box), 2)
        lay.addLayout(row)

        # toggles
        self.meta_toggle = ToggleSwitch(settings.embed_metadata)
        self.thumb_toggle = ToggleSwitch(True)
        self.playlist_toggle = ToggleSwitch(False)
        toggles = QHBoxLayout()
        toggles.setSpacing(28)
        toggles.addWidget(_toggle_row("Embed metadata", self.meta_toggle))
        toggles.addWidget(_toggle_row("Embed thumbnail", self.thumb_toggle))
        toggles.addStretch(1)
        lay.addLayout(toggles)
        self.playlist_row = _toggle_row(
            "This link is part of a playlist — download the whole playlist instead", self.playlist_toggle)
        lay.addWidget(self.playlist_row)

        # playlist chooser (playlist links only)
        self._selected: set[int] | None = None
        self.skip_toggle = ToggleSwitch(True)
        self.choose_btn = secondary_button("Choose videos…", "queue")
        self.choose_label = make_label("All videos", "Dim")
        self.playlist_tools = QWidget()
        pl = QHBoxLayout(self.playlist_tools)
        pl.setContentsMargins(0, 0, 0, 0)
        pl.setSpacing(14)
        pl.addWidget(self.choose_btn)
        pl.addWidget(self.choose_label)
        pl.addSpacing(10)
        pl.addWidget(_toggle_row("Skip videos I've already downloaded", self.skip_toggle))
        pl.addStretch(1)
        lay.addWidget(self.playlist_tools)
        self.choose_btn.clicked.connect(self._choose_videos)

        # trim (single videos and audio)
        self.trim_start = QLineEdit()
        self.trim_start.setPlaceholderText("Start (0:00)")
        self.trim_end = QLineEdit()
        self.trim_end.setPlaceholderText("End (optional)")
        self.trim_error = make_label("", "Dim")
        self.trim_error.setProperty("state", "bad")
        self.trim_box = QWidget()
        tr = QHBoxLayout(self.trim_box)
        tr.setContentsMargins(0, 0, 0, 0)
        tr.setSpacing(10)
        tr.addWidget(make_label("Save only part:", "Dim"))
        tr.addWidget(self.trim_start, 1)
        tr.addWidget(make_label("to", "Dim"))
        tr.addWidget(self.trim_end, 1)
        tr.addWidget(self.trim_error, 2)
        lay.addWidget(self.trim_box)
        self.trim_start.textChanged.connect(lambda _t: self._refresh())
        self.trim_end.textChanged.connect(lambda _t: self._refresh())

        # footer
        self.warning = make_label("", "Dim", wrap=True)
        lay.addWidget(self.warning)
        foot = QHBoxLayout()
        foot.setSpacing(10)
        self.summary = make_label("", "Dim")
        foot.addWidget(self.summary, 1)
        self.feedback = make_label("", "Dim")
        self.feedback.hide()
        self.view_queue_btn = ghost_button("View queue", "queue")
        self.view_queue_btn.clicked.connect(lambda: signals.navigate.emit(2))
        self.view_queue_btn.hide()
        foot.addWidget(self.feedback)
        foot.addWidget(self.view_queue_btn)
        self.queue_btn = secondary_button("Add to queue", "queue")
        self.queue_btn.setToolTip("Line this download up; it starts when the queue reaches it.")
        self.queue_btn.clicked.connect(lambda: self._emit_request(False))
        self.download_btn = primary_button("Download now", "download")
        self.download_btn.setToolTip("Start right away (waits only if all download slots are busy).")
        self.download_btn.clicked.connect(lambda: self._emit_request(True))
        foot.addWidget(self.queue_btn)
        foot.addWidget(self.download_btn)
        lay.addLayout(foot)

        for combo in (self.quality, self.container, self.audio_fmt, self.bitrate, self.subs):
            combo.currentIndexChanged.connect(lambda _i: self._refresh())
        signals.setting_changed.connect(lambda key, _v: self._refresh() if key == "ffmpeg_path" else None)
        self.hide()

    # -- population ---------------------------------------------------------
    def set_media(self, info: MediaInfo, thumbnail: QPixmap | None) -> None:
        """Populate the controls with only what the analysed media offers."""
        self._info, self._thumb = info, thumbnail
        self.feedback.hide()
        self.view_queue_btn.hide()
        for widget in (self.quality, self.audio_fmt, self.subs, self.container, self.bitrate):
            widget.blockSignals(True)

        heights = list(info.video_heights) if info.video_heights and not info.is_playlist else list(PLAYLIST_HEIGHTS)
        self.quality.clear()
        self.quality.addItem("Best available", None)
        for h in heights:
            self.quality.addItem(quality_label(h), h)
        cap = parse_default_height(self.s.video_quality)
        choice = 0
        if cap is not None:
            fitting = [h for h in heights if h <= cap]
            chosen = max(fitting) if fitting else min(heights)
            choice = self.quality.findData(chosen)
        self.quality.setCurrentIndex(max(0, choice))

        self.audio_fmt.setCurrentText(self.s.audio_format)

        self.subs.clear()
        self.subs.addItem("None", "")
        codes = info.subtitle_langs if info.subtitle_langs and not info.is_playlist else list(COMMON_SUBTITLES)
        for code in codes:
            name = LANGUAGE_NAMES.get(code)
            self.subs.addItem(f"{name} ({code})" if name else code, code)

        for widget in (self.quality, self.audio_fmt, self.subs, self.container, self.bitrate):
            widget.blockSignals(False)

        has_video = bool(info.video_heights) or info.is_playlist
        self.mode.set_segment_enabled(0, has_video)
        self.mode.set_current(0 if has_video else 1)
        self.meta_toggle.setChecked(self.s.embed_metadata)
        self.folder.setText(self.s.download_dir)
        self.folder.setToolTip(self.s.download_dir)
        self.playlist_toggle.setChecked(False)
        self.playlist_row.setVisible(info.part_of_playlist)
        self._selected = None
        self.skip_toggle.setChecked(True)
        self.trim_start.clear()
        self.trim_end.clear()
        self.show()
        self._refresh()

    # -- behaviour ------------------------------------------------------------
    def _is_audio(self) -> bool:
        return self.mode.current() == 1

    def _ffmpeg(self) -> str:
        path = resolve_ffmpeg(self.s.ffmpeg_path)
        return str(path) if path else ""

    def _refresh(self) -> None:
        if self._info is None:
            return
        audio = self._is_audio()
        self.video_box.setVisible(not audio)
        self.audio_box.setVisible(audio)
        self.bitrate.setEnabled(self.audio_fmt.currentText() != "WAV")

        supports = (self.audio_fmt.currentText() in ("MP3", "M4A")) if audio else (
            self.container.currentText() in ("MP4", "MKV"))
        self.thumb_toggle.setEnabled(supports)
        self.thumb_toggle.setToolTip("" if supports else "Thumbnails can't be embedded in this format.")

        have_ffmpeg = bool(self._ffmpeg())
        if not have_ffmpeg:
            text = ("FFmpeg wasn't found. " + (
                "Audio conversion needs it — set its location in Settings." if audio else
                "Video will download as a single file (quality may be lower) and metadata can't be embedded."))
            self.warning.setText(text)
            self.warning.setObjectName("Error")
        else:
            self.warning.setText("")
        repolish(self.warning)
        self.warning.setVisible(not have_ffmpeg)
        self.download_btn.setEnabled(have_ffmpeg or not audio)
        self.queue_btn.setEnabled(have_ffmpeg or not audio)

        if audio:
            fmt = self.audio_fmt.currentText()
            self.summary.setText(f"{fmt} · " + ("lossless" if fmt == "WAV" else f"{self.bitrate.currentData()} kbps"))
        else:
            self.summary.setText(f"{self.container.currentText()} · {self.quality.currentText()}")
        wants_pl = self._wants_playlist()
        self.download_btn.setText("Download playlist now" if wants_pl else "Download now")
        info = self._info
        self.playlist_tools.setVisible(wants_pl)
        self.choose_btn.setVisible(bool(info and info.is_playlist and info.entries))
        if info and wants_pl:
            total = len(info.entries) or info.entry_count
            self.choose_label.setText("All videos" if self._selected is None
                                      else f"{len(self._selected)} of {total} videos")
        # trimming: one video at a time, and FFmpeg must be present
        self.trim_box.setVisible(not wants_pl and have_ffmpeg)
        problem = self._trim_problem()
        self.trim_error.setText(problem)
        trim_ok = not problem
        self.download_btn.setEnabled(self.download_btn.isEnabled() and trim_ok)
        self.queue_btn.setEnabled(self.queue_btn.isEnabled() and trim_ok)

    def _trim_problem(self) -> str:
        if self._info is None or self._wants_playlist():
            return ""
        try:
            start, end = parse_time(self.trim_start.text()), parse_time(self.trim_end.text())
        except ValueError:
            return "Use minutes:seconds, like 1:20"
        if end is not None and end <= (start or 0):
            return "The end must be after the start"
        info = self._info
        if info and info.duration_seconds and start and start >= info.duration_seconds:
            return "The start is past the end of the video"
        return ""

    def _trim_values(self) -> tuple[float, float]:
        """(start, end) seconds to save; (0, 0) when not trimming or the fields are invalid."""
        if self._wants_playlist() or self._trim_problem():
            return 0.0, 0.0
        return (parse_time(self.trim_start.text()) or 0.0), (parse_time(self.trim_end.text()) or 0.0)

    def _choose_videos(self) -> None:
        info = self._info
        if not info or not info.entries:
            return
        total = len(info.entries)
        dialog = PlaylistDialog(info.title, info.entries, info.entry_count, self._selected, self)
        if dialog.exec() == PlaylistDialog.DialogCode.Accepted and dialog.result_items is not None:
            chosen = set(dialog.result_items)
            self._selected = None if len(chosen) == total and total >= info.entry_count else chosen
            self._refresh()

    def _wants_playlist(self) -> bool:
        info = self._info
        return bool(info and (info.is_playlist or (info.part_of_playlist and self.playlist_toggle.isChecked())))

    def _browse(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Choose download folder", self.folder.text())
        if chosen:
            self.folder.setText(chosen)
            self.folder.setToolTip(chosen)

    def build_request(self) -> DownloadRequest | None:
        """Create a request from the current selections."""
        info = self._info
        if info is None:
            return None
        return DownloadRequest(
            url=info.url,
            title=info.title,
            kind="audio" if self._is_audio() else "video",
            height=self.quality.currentData(),
            container=self.container.currentText(),
            audio_format=self.audio_fmt.currentText(),
            audio_bitrate=str(self.bitrate.currentData() or "192"),
            output_dir=self.folder.text(),
            subtitle_lang=str(self.subs.currentData() or ""),
            embed_metadata=self.meta_toggle.isChecked(),
            embed_thumbnail=self.thumb_toggle.isChecked() and self.thumb_toggle.isEnabled(),
            playlist=self._wants_playlist(),
            playlist_items=items_spec(sorted(self._selected), info.entry_count) if self._selected else "",
            skip_downloaded=self._wants_playlist() and self.skip_toggle.isChecked(),
            name_template=self.s.get("name_template"),
            folder_layout=self.s.get("folder_layout"),
            trim_start=self._trim_values()[0],
            trim_end=self._trim_values()[1],
            ffmpeg_path=self._ffmpeg(),
            cookies_browser=self.s.cookie_source[0],
            cookies_file=self.s.cookie_source[1],
            site=info.site,
        )

    def _emit_request(self, start_now: bool) -> None:
        request = self.build_request()
        if request:
            self.download_requested.emit(request, self._thumb, start_now)

    def show_queued(self, position: int) -> None:
        """Confirm that a download was added to the queue."""
        self.feedback.setText(f"Added to the queue (position {position})")
        self.feedback.show()
        self.view_queue_btn.show()
