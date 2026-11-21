"""Opening, revealing and deleting files through the operating system."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path

from PySide6.QtCore import QFile, QUrl
from PySide6.QtGui import QDesktopServices

log = logging.getLogger("quanttum.system")


def open_path(path: str | Path) -> bool:
    """Open a file or folder with its default application."""
    return QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


def reveal_in_folder(path: str | Path) -> bool:
    """Show ``path`` in the file manager (selected, on Windows)."""
    target = Path(path)
    if sys.platform == "win32" and target.exists():
        try:
            subprocess.Popen(["explorer", f"/select,{target}"])  # noqa: S603,S607
            return True
        except OSError:
            pass
    return open_path(target.parent if target.is_file() else target)


def move_to_trash(path: str | Path) -> bool:
    """Move a file to the Recycle Bin / Trash; delete it permanently if no trash is available."""
    target = str(path)
    try:
        if QFile.moveToTrash(target):
            return True
    except Exception:  # noqa: BLE001
        log.debug("moveToTrash failed for %s", target, exc_info=True)
    try:
        os.remove(target)
        return True
    except OSError:
        log.warning("Could not delete %s", target, exc_info=True)
        return False
