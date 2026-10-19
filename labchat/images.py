"""Validate images before decoding; reduce memory use on 8GB machines."""

import base64
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt
from PySide6.QtGui import QImageReader

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_PIXELS = 16_000_000
MAX_EDGE = 1024


def prepare_image(path: str) -> str:
    source = Path(path)
    try:
        if not source.is_file() or source.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("請選擇 20MB 以內的圖片檔案。")
        reader = QImageReader(str(source))
        reader.setAutoTransform(True)
        if bytes(reader.format()).lower() not in (b"png", b"jpeg", b"webp"):
            raise ValueError("僅支援有效的 PNG、JPEG 或 WebP 圖片。")
        size = reader.size()
        if not size.isValid() or size.width() * size.height() > MAX_PIXELS:
            raise ValueError("圖片解析度超出限制，請縮小至 1600 萬像素以內。")
        if reader.supportsAnimation() and reader.imageCount() != 1:
            raise ValueError("請使用靜態圖片，不支援動畫。")
        if max(size.width(), size.height()) > MAX_EDGE:
            reader.setScaledSize(
                size.scaled(QSize(MAX_EDGE, MAX_EDGE), Qt.AspectRatioMode.KeepAspectRatio)
            )
        image = reader.read()
        if image.isNull():
            raise ValueError("圖片無法解碼，請重新匯出後再試。")
        if max(image.width(), image.height()) > MAX_EDGE:
            image = image.scaled(
                MAX_EDGE,
                MAX_EDGE,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        data = QByteArray()
        buffer = QBuffer(data)
        if not buffer.open(QIODevice.OpenModeFlag.WriteOnly) or not image.save(buffer, "PNG"):
            raise ValueError("圖片轉換失敗，請選擇其他圖片。")
        buffer.close()
        return base64.b64encode(bytes(data)).decode("ascii")
    except OSError as error:
        raise ValueError("無法讀取檔案，請確認檔案存在且有讀取權限。") from error
