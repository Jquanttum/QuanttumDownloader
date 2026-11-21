"""Settings page: every control is persisted and takes effect immediately."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget,
)

from app.config import (
    AUDIO_FORMATS, MAX_CONCURRENT_LIMIT, VIDEO_QUALITIES, Settings, get_ytdlp_version,
    resolve_ffmpeg,
)
from app.cookies import BROWSERS as COOKIE_BROWSERS, MODES as COOKIE_MODES, check_cookies_file
from app.signals import signals
from app.updater import CheckWorker, UpdateSignals, UpdateWorker, is_newer
from ui.dialogs import show_error
from ui.styles import apply_theme
from ui.widgets import (
    ScrollSafeComboBox,
    BasePage, Card, ToggleSwitch, divider, make_label, repolish, secondary_button, setting_row,
)

log = logging.getLogger("quanttum.settings")


class SettingsPage(BasePage):
    """Preferences for appearance, downloads, behaviour and external tools."""

    def __init__(self, settings: Settings) -> None:
        super().__init__("Settings", "Changes are saved automatically.")
        self.s = settings
        self.body.addWidget(self._section("Appearance", [
            setting_row("Theme", "Choose between the dark and light interface.", self._theme_combo()),
        ]))
        self.body.addWidget(self._section("Downloads", [
            setting_row("Download folder", "Where finished files are saved.", self._dir_control()),
            setting_row("Default video quality", "Preselected when you analyse a link.",
                        self._combo("video_quality", VIDEO_QUALITIES)),
            setting_row("Default audio format", "Used for audio-only downloads.",
                        self._combo("audio_format", AUDIO_FORMATS)),
            setting_row("Simultaneous downloads",
                        "Lower values use less memory, CPU and bandwidth. Default is 2.",
                        self._concurrency_combo()),
            setting_row("Embed metadata automatically",
                        "Write title, artist and other tags into downloaded files.",
                        self._toggle("embed_metadata")),
        ]))
        self.body.addWidget(self._section("Behaviour", [
            setting_row("Clipboard detection", "Offer to use links you copy while the app is open.",
                        self._toggle("clipboard_detection")),
            setting_row("Notifications", "Notify when downloads finish or fail while the app is in the background.",
                        self._toggle("notifications")),
            setting_row("Keep download history", "Save finished downloads to the History page. "
                        "Turning this off doesn't erase existing history.",
                        self._toggle("keep_history")),
        ]))
        self.body.addWidget(self._section("Tools", [
            self._ffmpeg_row(),
            self._cookies_row(),
            self._ytdlp_row(),
        ]))
        self.body.addStretch(1)

    # -- layout helpers ----------------------------------------------------
    @staticmethod
    def _section(title: str, rows: list[QWidget]) -> Card:
        card = Card()
        lay = QVBoxLayout(card)
        lay.setContentsMargins(22, 18, 22, 10)
        lay.setSpacing(0)
        lay.addWidget(make_label(title, "CardTitle"))
        lay.addSpacing(4)
        for i, row in enumerate(rows):
            if i:
                lay.addWidget(divider())
            lay.addWidget(row)
        return card

    def _save(self, key: str, value: object) -> None:
        self.s.set(key, value)
        signals.setting_changed.emit(key, value)

    # -- controls ----------------------------------------------------------
    def _theme_combo(self) -> QComboBox:
        combo = ScrollSafeComboBox()
        combo.setMinimumWidth(180)
        combo.addItems(["Dark", "Light"])
        combo.setCurrentIndex(0 if self.s.theme == "dark" else 1)

        def changed(index: int) -> None:
            theme = "dark" if index == 0 else "light"
            self._save("theme", theme)
            apply_theme(QApplication.instance(), theme)

        combo.currentIndexChanged.connect(changed)
        return combo

    def _combo(self, key: str, items: list[str]) -> QComboBox:
        combo = ScrollSafeComboBox()
        combo.setMinimumWidth(180)
        combo.addItems(items)
        current = getattr(self.s, key)
        combo.setCurrentText(current)
        combo.currentTextChanged.connect(lambda text: self._save(key, text))
        return combo

    def _concurrency_combo(self) -> QComboBox:
        combo = ScrollSafeComboBox()
        combo.setMinimumWidth(180)
        combo.addItems([str(n) for n in range(1, MAX_CONCURRENT_LIMIT + 1)])
        combo.setCurrentText(str(self.s.max_concurrent))
        combo.currentTextChanged.connect(lambda text: self._save("max_concurrent", int(text)))
        return combo

    def _toggle(self, key: str) -> ToggleSwitch:
        toggle = ToggleSwitch(bool(self.s.get(key)))
        toggle.toggled.connect(lambda on: self._save(key, on))
        return toggle

    def _dir_control(self) -> QWidget:
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        edit = QLineEdit(self.s.download_dir)
        edit.setReadOnly(True)
        edit.setMinimumWidth(260)
        edit.setToolTip(self.s.download_dir)
        browse = secondary_button("Browse…", "folder")

        def pick() -> None:
            chosen = QFileDialog.getExistingDirectory(self, "Choose download folder", self.s.download_dir)
            if not chosen:
                return
            try:
                Path(chosen).mkdir(parents=True, exist_ok=True)
            except OSError:
                log.exception("Cannot use download folder %s", chosen)
                show_error(self, "Folder not usable",
                           "Quanttum Downloader can't write to that folder. Please choose another one.")
                return
            edit.setText(chosen)
            edit.setToolTip(chosen)
            self._save("download_dir", chosen)

        browse.clicked.connect(pick)
        lay.addWidget(edit, 1)
        lay.addWidget(browse)
        return box

    # -- tools -------------------------------------------------------------
    def _ffmpeg_row(self) -> QWidget:
        control = QWidget()
        lay = QHBoxLayout(control)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.ffmpeg_edit = QLineEdit(self.s.ffmpeg_path)
        self.ffmpeg_edit.setPlaceholderText("Auto-detect from PATH")
        self.ffmpeg_edit.setMinimumWidth(240)
        browse = secondary_button("Browse…", "folder")
        auto = secondary_button("Auto-detect")
        lay.addWidget(self.ffmpeg_edit, 1)
        lay.addWidget(browse)
        lay.addWidget(auto)

        self.ffmpeg_status = make_label("", "Dim", wrap=True)
        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        wl.addWidget(setting_row(
            "FFmpeg location",
            "Required to merge video and audio streams and to convert audio to MP3/WAV.",
            control))
        wl.addWidget(self.ffmpeg_status)
        wl.addSpacing(8)

        def commit() -> None:
            self._save("ffmpeg_path", self.ffmpeg_edit.text().strip())
            self._refresh_ffmpeg()

        def pick() -> None:
            path, _ = QFileDialog.getOpenFileName(self, "Select ffmpeg executable", "",
                                                  "Executables (*.exe);;All files (*)")
            if path:
                self.ffmpeg_edit.setText(path)
                commit()

        def detect() -> None:
            self.ffmpeg_edit.clear()
            commit()

        self.ffmpeg_edit.editingFinished.connect(commit)
        browse.clicked.connect(pick)
        auto.clicked.connect(detect)
        self._refresh_ffmpeg()
        return wrapper

    def _refresh_ffmpeg(self) -> None:
        configured = self.s.ffmpeg_path
        found = resolve_ffmpeg(configured)
        if found:
            text, state = f"Found: {found}", "ok"
        elif configured:
            text, state = "That path doesn't point to a valid ffmpeg executable.", "bad"
        else:
            text, state = ("FFmpeg was not found on your PATH. Install it (winget install Gyan.FFmpeg) "
                           "or browse to ffmpeg.exe."), "bad"
        self.ffmpeg_status.setText(text)
        self.ffmpeg_status.setProperty("state", state)
        repolish(self.ffmpeg_status)

    def _cookies_row(self) -> QWidget:
        control = QWidget()
        lay = QHBoxLayout(control)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.cookie_mode = ScrollSafeComboBox()
        self.cookie_mode.addItems(COOKIE_MODES)
        self.cookie_mode.setCurrentText(self.s.get("cookies_mode"))
        self.cookie_browser = ScrollSafeComboBox()
        self.cookie_browser.addItems(COOKIE_BROWSERS)
        self.cookie_browser.setCurrentText(self.s.get("cookies_browser"))
        self.cookie_file = QLineEdit(self.s.get("cookies_file"))
        self.cookie_file.setPlaceholderText("cookies.txt")
        self.cookie_file.setMinimumWidth(160)
        self.cookie_pick = secondary_button("Browse…", "folder")
        for w in (self.cookie_mode, self.cookie_browser, self.cookie_file, self.cookie_pick):
            lay.addWidget(w, 1 if w is self.cookie_file else 0)

        self.cookie_status = make_label("", "Dim", wrap=True)
        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        wl.addWidget(setting_row(
            "Sign-in cookies",
            "For sites that need a login (private, members-only or age-restricted media). Use only your own "
            "account. Cookies are read when needed and never stored by this app.",
            control))
        wl.addWidget(self.cookie_status)
        wl.addSpacing(8)

        def commit() -> None:
            self._save("cookies_mode", self.cookie_mode.currentText())
            self._save("cookies_browser", self.cookie_browser.currentText())
            self._save("cookies_file", self.cookie_file.text().strip())
            self._refresh_cookies()

        def pick() -> None:
            path, _ = QFileDialog.getOpenFileName(self, "Select cookies.txt", "", "Text files (*.txt);;All files (*)")
            if path:
                self.cookie_file.setText(path)
                commit()

        self.cookie_mode.currentTextChanged.connect(lambda _t: commit())
        self.cookie_browser.currentTextChanged.connect(lambda _t: commit())
        self.cookie_file.editingFinished.connect(commit)
        self.cookie_pick.clicked.connect(pick)
        self._refresh_cookies()
        return wrapper

    def _refresh_cookies(self) -> None:
        mode = self.cookie_mode.currentText()
        self.cookie_browser.setVisible(mode == "From browser")
        self.cookie_file.setVisible(mode == "From cookies.txt")
        self.cookie_pick.setVisible(mode == "From cookies.txt")
        problem, text = "", ""
        if mode == "From cookies.txt":
            problem = check_cookies_file(self.cookie_file.text().strip())
            text = problem or "Cookies file looks good."
        elif mode == "From browser":
            text = (f"Cookies will be read from {self.cookie_browser.currentText()}. "
                    "If that fails, close the browser first or use a cookies.txt file instead.")
        self.cookie_status.setText(text)
        self.cookie_status.setVisible(bool(text))
        self.cookie_status.setProperty("state", "bad" if problem else "")
        repolish(self.cookie_status)

    def _ytdlp_row(self) -> QWidget:
        control = QWidget()
        lay = QHBoxLayout(control)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        self.ytdlp_status = make_label("", "Chip")
        self.ytdlp_check = secondary_button("Check for updates")
        self.ytdlp_update = secondary_button("Update")
        self.ytdlp_update.setVisible(False)
        lay.addWidget(self.ytdlp_status)
        lay.addWidget(self.ytdlp_check)
        lay.addWidget(self.ytdlp_update)
        self._update_sig = UpdateSignals(self)
        self._update_sig.checked.connect(self._on_checked)
        self._update_sig.updated.connect(self._on_updated)
        self.ytdlp_check.clicked.connect(self.check_ytdlp_updates)
        self.ytdlp_update.clicked.connect(self.run_ytdlp_update)
        self._refresh_ytdlp()

        wrapper = QWidget()
        wl = QVBoxLayout(wrapper)
        wl.setContentsMargins(0, 0, 0, 0)
        wl.setSpacing(0)
        wl.addWidget(setting_row(
            "yt-dlp", "The download engine. Sites change often, so keep it up to date if downloads start failing.",
            control))
        self.ytdlp_note = make_label("", "Dim", wrap=True)
        self.ytdlp_note.setVisible(False)
        wl.addWidget(self.ytdlp_note)
        wl.addSpacing(8)
        return wrapper

    def _set_ytdlp_note(self, text: str, state: str = "") -> None:
        self.ytdlp_note.setText(text)
        self.ytdlp_note.setVisible(bool(text))
        self.ytdlp_note.setProperty("state", state)
        repolish(self.ytdlp_note)

    def _refresh_ytdlp(self) -> None:
        version = get_ytdlp_version()
        self.ytdlp_status.setText(f"Installed: {version}" if version else "Not installed")
        self.ytdlp_status.setProperty("state", "ok" if version else "bad")
        repolish(self.ytdlp_status)
        signals.setting_changed.emit("ffmpeg_path", self.s.ffmpeg_path)  # refreshes Home status chips

    def check_ytdlp_updates(self) -> None:
        self.ytdlp_check.setEnabled(False)
        self.ytdlp_update.setVisible(False)
        self._set_ytdlp_note("Checking for updates…")
        QThreadPool.globalInstance().start(CheckWorker(self._update_sig))

    def _on_checked(self, latest: object, error: str) -> None:
        self.ytdlp_check.setEnabled(True)
        self._refresh_ytdlp()
        if latest is None:
            self._set_ytdlp_note(error, "bad")
        elif is_newer(str(latest), get_ytdlp_version()):
            self._set_ytdlp_note(f"A newer version is available: {latest}.")
            self.ytdlp_update.setText(f"Update to {latest}")
            self.ytdlp_update.setVisible(True)
        else:
            self._set_ytdlp_note("yt-dlp is up to date.", "ok")

    def run_ytdlp_update(self) -> None:
        self.ytdlp_update.setEnabled(False)
        self.ytdlp_check.setEnabled(False)
        self._set_ytdlp_note("Updating… this can take a minute.")
        QThreadPool.globalInstance().start(UpdateWorker(self._update_sig))

    def _on_updated(self, ok: bool, message: str) -> None:
        self.ytdlp_update.setEnabled(True)
        self.ytdlp_check.setEnabled(True)
        self.ytdlp_update.setVisible(not ok)
        self._set_ytdlp_note(message, "ok" if ok else "bad")
