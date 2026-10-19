"""Preserve Qt stderr diagnostics and record cursor call sites without chat text."""

import logging
import sys
import traceback

from PySide6.QtCore import qFormatLogMessage, qInstallMessageHandler

logger = logging.getLogger(__name__)


def install_qt_diagnostics():
    previous = None

    def handler(kind, context, message):
        if message.startswith("QTextCursor::setPosition:"):
            logger.warning(
                "Qt cursor position warning; call stack (no conversation contents):\n%s",
                "".join(traceback.format_stack(limit=8)),
            )
        if previous is not None:
            previous(kind, context, message)
        else:
            sys.stderr.write(qFormatLogMessage(kind, context, message) + "\n")
            sys.stderr.flush()

    previous = qInstallMessageHandler(handler)

    def restore():
        qInstallMessageHandler(previous)

    return restore
