"""Portable Labelme rectangles on the exact embedded, preprocessed PNG."""

import struct
from pathlib import Path

from .attachments import image_bytes, validate_boxes

# Schema compatibility target verified against the official Labelme reader.
LABELME_VERSION = "7.8.1"


def labelme_document(encoded_image, boxes, image_name="annotation.png"):
    png = image_bytes(encoded_image)
    width, height = struct.unpack(">II", png[16:24])
    boxes = validate_boxes(boxes)
    # A display name only: never propagate an original private absolute image path.
    if (
        not isinstance(image_name, str)
        or not image_name
        or image_name in (".", "..")
        or any(char in image_name for char in ("/", "\\", ":", "\x00"))
        or Path(image_name).suffix.lower() != ".png"
    ):
        raise ValueError("Labelme圖片名稱需為不含路徑的PNG檔名。")
    return {
        "version": LABELME_VERSION,
        "flags": {},
        "shapes": [
            {
                "label": box.label,
                "points": [
                    [box.bbox[0] * width / 1000, box.bbox[1] * height / 1000],
                    [box.bbox[2] * width / 1000, box.bbox[3] * height / 1000],
                ],
                "group_id": None,
                "description": (
                    "AI estimate; manual review required."
                    if box.source == "model"
                    else "Manually drawn or edited rectangle."
                ),
                "shape_type": "rectangle",
                "flags": {"ai_suggested": box.source == "model"},
                "mask": None,
            }
            for box in boxes
        ],
        "imagePath": image_name,
        "imageData": encoded_image,
        "imageHeight": height,
        "imageWidth": width,
    }
