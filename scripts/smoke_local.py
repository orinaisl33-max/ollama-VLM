"""Opt-in real-model check. Run from the project root; never part of unit tests."""

import argparse
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QTextDocument
from PySide6.QtWidgets import QApplication

from labchat.config import MODELS, find_model
from labchat.images import prepare_image
from labchat.reader import LocalDocument
from labchat.window import Window


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", choices=[m.identifier for m in MODELS], default="qwen3.5:2b")
    args = parser.parse_args()
    configuration = find_model(args.model)
    app = QApplication([])
    temp = tempfile.TemporaryDirectory()
    window = Window(history_path=Path(temp.name) / "history.sqlite3")
    window.model.setCurrentIndex(window.model.findData(args.model))
    started = time.monotonic()
    stage = 0
    timer = QTimer()
    timer.setInterval(100)

    def check():
        nonlocal stage
        if time.monotonic() - started > 300:
            print("FAIL: overall timeout", flush=True)
            window.close()
            app.exit(1)
            return
        if window.client.active:
            return
        if window.failed or not window.answer.strip():
            print("FAIL: " + window.status.text(), flush=True)
            window.close()
            app.exit(1)
            return
        rendered = LocalDocument()
        rendered.setMarkdown(
            window.answer,
            QTextDocument.MarkdownFeature.MarkdownDialectGitHub
            | QTextDocument.MarkdownFeature.MarkdownNoHTML,
        )
        if rendered.toPlainText().strip() not in window.chat.toPlainText():
            print("FAIL: completed answer missing from visible transcript", flush=True)
            window.close()
            app.exit(1)
            return
        print(f"{('TEXT', 'IMAGE')[stage]}: {window.answer}", flush=True)
        if stage == 0 and configuration.vision:
            stage = 1
            window.reset()
            image = QImage(512, 256, QImage.Format.Format_RGB32)
            image.fill(QColor("red"))
            painter = QPainter(image)
            painter.fillRect(0, 0, 256, 256, QColor("blue"))
            painter.end()
            path = Path(temp.name) / "two-colors.png"
            assert image.save(str(path))
            window.image = prepare_image(str(path))
            window.input.setPlainText("請分別說出圖片左半邊與右半邊的顏色，簡短回答。")
            window.submit()
        else:
            print(
                f"PASS: {args.model} {'text/image' if configuration.vision else 'text'} transport completed in {time.monotonic() - started:.1f}s. "
                "Review answers above for semantic accuracy.",
                flush=True,
            )
            window.close()
            app.quit()

    window.input.setPlainText("這個展示工具是本機還是雲端？目前模型支援圖片理解嗎？簡短回答。")
    window.submit()
    timer.timeout.connect(check)
    timer.start()
    code = app.exec()
    window.shutdown()
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    temp.cleanup()
    return code


if __name__ == "__main__":
    sys.exit(main())
