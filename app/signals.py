"""Application-wide Qt signal bus.

A single shared ``signals`` instance lets UI components talk to each other (and,
in later phases, receive events from background workers) without importing one
another directly.
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class AppSignals(QObject):
    """Global signals shared across the application."""

    theme_changed = Signal(str)          # new theme name ("dark" | "light")
    setting_changed = Signal(str, object)  # setting key, new value
    navigate = Signal(int)               # request to switch to a page index
    url_submitted = Signal(str)          # a validated URL was submitted for analysis


signals = AppSignals()
