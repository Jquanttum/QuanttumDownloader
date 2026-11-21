"""User-facing dialogs."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget


def show_error(parent: QWidget | None, title: str, message: str, details: str | None = None) -> None:
    """Show a friendly error message (technical detail goes to the log file, not here)."""
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle(title)
    box.setText(message)
    if details:
        box.setInformativeText(details)
    box.exec()


def confirm(parent: QWidget | None, title: str, message: str) -> bool:
    """Ask a yes/no question and return True for Yes."""
    answer = QMessageBox.question(
        parent, title, message,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    )
    return answer == QMessageBox.StandardButton.Yes
