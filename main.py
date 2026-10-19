"""Application entry point. Run with the project's .venv Python."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import QApplication

from labchat.config import APP_TITLE
from labchat.diagnostics import install_qt_diagnostics
from labchat.window import Window


def main() -> int:
    log_dir = Path(__file__).resolve().parent / ".logs"
    log_dir.mkdir(exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "application.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
    )
    logging.basicConfig(
        level=logging.INFO,
        handlers=[handler],
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    restore_qt_diagnostics = install_qt_diagnostics()
    app = QApplication(sys.argv)
    app.setApplicationName(APP_TITLE)
    QImageReader.setAllocationLimit(64)
    window = Window()
    app.aboutToQuit.connect(window.shutdown)
    window.show()
    try:
        return app.exec()
    finally:
        # Qt's event loop has ended: deliver deferred destruction on its owning
        # thread rather than leaving network/process/widgets to Python teardown.
        window.shutdown()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        restore_qt_diagnostics()


if __name__ == "__main__":
    sys.exit(main())
