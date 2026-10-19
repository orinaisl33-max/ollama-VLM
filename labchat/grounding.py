"""Approximate model-proposed regions, never detector confidence scores."""

import json
import re
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
        if box not in result:
            result.append(box)
    return result


def grounding_messages(image: str, target: str) -> list[dict]:
    target = target.strip()[:120] or "圖片中的主要可見物件"
    return [
        {
            "role": "system",
            "content": '你是圖片物件定位助手。只輸出 JSON，不要 Markdown 或解說。格式為 {"objects":[{"label":"物件名稱","bbox":[左,上,右,下]}]}。找不到時回傳 {"objects":[]}。'
            "bbox 為 [左,上,右,下]，座標使用 0 到 1000 的相對位置，原點在左上。"
            "只定位圖片中可見的物件，不推測被遮擋的數量。不確定的物件可省略。"
            "每個獨立物件各給一框，成串或成堆無法分開者可用群組名稱框選。"
            "每個 label 必須是具體物件名稱（例如香蕉、蘋果），不要全部寫成「水果」或「物件」。名稱使用繁體中文，不提供信心分數。最多 30 個框。",
        },
        {
            "role": "user",
            "content": f"請找出並框選：{target}。框應貼合物件，不要把整張圖片當成物件。",
            "images": [image],
        },
    ]
