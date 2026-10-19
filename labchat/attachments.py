"""Validate small preprocessed PNG attachments and normalized annotation records."""

import base64
import binascii
import struct

from PySide6.QtGui import QImage

from .grounding import MAX_BOXES, Box
from .security import clean_label

MAX_PNG_BYTES = 6 * 1024 * 1024
MAX_ATTACHMENT_BYTES = 100 * 1024 * 1024


def image_bytes(encoded):
    if not isinstance(encoded, str) or len(encoded) > MAX_PNG_BYTES * 4 // 3 + 4:
        raise ValueError("圖片容量超過保存上限。")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("保存圖片編碼無效。") from error
    if (
        len(data) > MAX_PNG_BYTES
        or len(data) < 24
        or data[:8] != b"\x89PNG\r\n\x1a\n"
        or data[12:16] != b"IHDR"
    ):
        raise ValueError("只接受已前處理的PNG圖片。")
    width, height = struct.unpack(">II", data[16:24])
    if not (1 <= width <= 1024 and 1 <= height <= 1024):
        raise ValueError("保存圖片最長邊不可超過1024像素。")
    image = QImage.fromData(data, "PNG")
    if image.isNull() or image.width() != width or image.height() != height:
        raise ValueError("保存圖片無法解碼。")
    return data


def validate_boxes(items):
    if not isinstance(items, list) or len(items) > MAX_BOXES:
        raise ValueError("框選資料超過上限或格式錯誤。")
    result = []
    for item in items:
        if isinstance(item, Box):
            item = item.to_dict()
        if not isinstance(item, dict) or set(item) != {"label", "bbox", "source"}:
            raise ValueError("框選欄位不符。")
        label, coords, source = item["label"], item["bbox"], item["source"]
        if (
            not isinstance(label, str)
            or not 1 <= len(label) <= 200
            or source not in ("model", "manual")
        ):
            raise ValueError("框選名稱或來源無效。")
        label = clean_label(label)
        if not label or not isinstance(coords, (list, tuple)) or len(coords) != 4:
            raise ValueError("框選座標無效。")
        if any(type(value) is not int or not 0 <= value <= 1000 for value in coords):
            raise ValueError("框選座標超出範圍。")
        if coords[2] <= coords[0] or coords[3] <= coords[1]:
            raise ValueError("框選範圍必須大於零。")
        result.append(Box(label, tuple(coords), source))
    return result
