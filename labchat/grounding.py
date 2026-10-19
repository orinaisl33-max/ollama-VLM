"""Approximate model-proposed regions, never detector confidence scores."""

import json
import re
from copy import deepcopy
from dataclasses import asdict, dataclass

from .security import clean_label

MAX_BOXES = 60
BOX_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["objects"],
    "properties": {
        "objects": {
            "type": "array",
            "maxItems": MAX_BOXES,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["label", "bbox"],
                "properties": {
                    "label": {"type": "string"},
                    "bbox": {
                        "type": "array",
                        "minItems": 4,
                        "maxItems": 4,
                        "items": {"type": "integer", "minimum": 0, "maximum": 1000},
                    },
                },
            },
        }
    },
}


@dataclass(frozen=True)
class Box:
    label: str
    bbox: tuple[int, int, int, int]
    source: str = "model"

    def to_dict(self):
        return asdict(self)


def same_region(first: Box, second: Box) -> bool:
    """Suppress only highly overlapping proposals with the same explicit label."""
    if first.label != second.label:
        return False
    a, b = first.bbox, second.bbox
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return union > 0 and intersection / union >= 0.85


def parse_boxes(text: str) -> list[Box]:
    try:
        text = text.strip()
        fenced = re.fullmatch(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
        if fenced:
            text = fenced[1]
        payload = json.loads(text)
        if isinstance(payload, list):
            payload = {"objects": payload}
    except (ValueError, RecursionError) as error:
        raise ValueError("模型定位資料無法解析，請重試或改用手動畫框。") from error
    if not isinstance(payload, dict) or not isinstance(payload.get("objects"), list):
        raise ValueError("缺少有效的物件清單。")
    if len(payload["objects"]) > MAX_BOXES:
        raise ValueError("物件數量超出上限，請縮小搜尋範圍。")
    result = []
    for item in payload["objects"]:
        if not isinstance(item, dict) or not isinstance(item.get("label"), str):
            raise ValueError("物件名稱格式無效。")
        label = clean_label(item["label"])
        coords = item.get("bbox", item.get("bbox_2d"))
        if not label or len(label) > 60 or not isinstance(coords, list) or len(coords) != 4:
            raise ValueError("物件名稱或框選座標格式無效。")
        if any(type(v) is not int or not 0 <= v <= 1000 for v in coords):
            raise ValueError("模型座標超出圖片範圍，請重試或手動修正。")
        x1, y1, x2, y2 = coords
        if x2 <= x1 or y2 <= y1:
            raise ValueError("模型回傳了無效的框，請重試或手動修正。")
        box = Box(label, tuple(coords))
        if not any(same_region(box, previous) for previous in result):
            result.append(box)
    return result


def grounding_schema(limit=8):
    if type(limit) is not int or not 1 <= limit <= 20:
        raise ValueError("AI 框數上限需為 1–20。")
    schema = deepcopy(BOX_SCHEMA)
    schema["properties"]["objects"]["maxItems"] = limit
    return schema


def grounding_messages(image: str, target: str, limit=8) -> list[dict]:
    grounding_schema(limit)
    target = target.strip()[:120]
    scope = (
        f"請找出並框選：{target}。只輸出這個目標，不列出其他物件。"
        if target
        else "請框選主要可見物件：先找人物，再找大型獨立物件。省略床單、枕頭等細碎局部。"
    )
    return [
        {
            "role": "system",
            "content": '你是圖片定位助手。只輸出 JSON：{"objects":[{"label":"名稱","bbox":[左,上,右,下]}]}。'
            "座標為 0–1000，原點在左上，框住完整可見物件。名稱用繁體中文。"
            f"最多 {limit} 框，不需填滿。同一物件只給一框。找不到目標就輸出空 objects，不以其他物件代替。",
        },
        {
            "role": "user",
            "content": f"{scope} 最多 {limit} 個框；不要為湊數增加物件。",
            "images": [image],
        },
    ]
