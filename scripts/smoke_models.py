"""Opt-in local model checks using generated colors only; no private images or archives."""

import argparse
import http.client
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QColor, QImage, QPainter

from labchat.config import MODELS, build_messages, find_model
from labchat.grounding import BOX_SCHEMA, grounding_messages, parse_boxes
from labchat.images import prepare_image


def post(payload):
    connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=300)
    try:
        connection.request(
            "POST", "/api/chat", json.dumps(payload).encode(), {"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        data = response.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise ValueError("Response exceeds size limit")
        result = json.loads(data)
        if response.status != 200:
            raise ValueError(f"HTTP {response.status}: {result.get('error', 'request failed')}")
        if not result.get("done") or result.get("done_reason") == "length":
            raise ValueError("Reply did not complete within output limit")
        answer = result.get("message", {}).get("content", "")
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("Reply is empty or invalid")
        return answer
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models",
        nargs="+",
        choices=[m.identifier for m in MODELS],
        default=["ministral-3:3b", "gemma3:4b"],
    )
    args = parser.parse_args()
    report = []
    with tempfile.TemporaryDirectory() as directory:
        image = QImage(256, 128, QImage.Format.Format_RGB32)
        image.fill(QColor("red"))
        painter = QPainter(image)
        painter.fillRect(0, 0, 128, 128, QColor("blue"))
        painter.end()
        filename = Path(directory) / "synthetic-colors.png"
        if not image.save(str(filename), "PNG"):
            raise ValueError("Cannot create test image")
        encoded = prepare_image(str(filename))
        for model in args.models:
            configuration = find_model(model)
            stages = [
                (
                    "text",
                    build_messages(
                        [], "請用繁體中文回答：1加1等於多少？只回答結果。", None, model=model
                    ),
                    None,
                ),
            ]
            if configuration.vision:
                stages.extend(
                    [
                        (
                            "image",
                            build_messages(
                                [], "左半邊和右半邊各是什麼顏色？簡短回答。", encoded, model=model
                            ),
                            None,
                        ),
                        (
                            "boxes",
                            grounding_messages(encoded, "左邊藍色區塊和右邊紅色區塊"),
                            BOX_SCHEMA,
                        ),
                    ]
                )
            else:
                for stage in ("image", "boxes"):
                    report.append(
                        {"model": model, "stage": stage, "status": "skipped", "reason": "text-only"}
                    )
            for stage, messages, schema in stages:
                if stage == "boxes" and not configuration.grounding:
                    report.append(
                        {
                            "model": model,
                            "stage": stage,
                            "status": "skipped",
                            "reason": "grounding-not-validated",
                        }
                    )
                    continue
                payload = {
                    "model": model,
                    "messages": messages,
                    "stream": False,
                    "think": False,
                    "keep_alive": 0,
                    "options": {
                        "num_ctx": 4096,
                        "num_predict": 2048 if schema else 1024,
                        "temperature": 0.1,
                    },
                }
                if schema:
                    payload["format"] = schema
                try:
                    answer = post(payload)
                    entry = {"model": model, "stage": stage, "status": "success", "answer": answer}
                    if stage == "boxes":
                        entry["parsed_boxes"] = [box.to_dict() for box in parse_boxes(answer)]
                        entry["manual_geometry_review_required"] = True
                except (OSError, ValueError, http.client.HTTPException) as error:
                    entry = {"model": model, "stage": stage, "status": "error", "error": str(error)}
                report.append(entry)
                print(json.dumps(entry, ensure_ascii=False), flush=True)
    output = Path(__file__).resolve().parents[1] / ".logs" / "new-model-smoke.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "Transport/schema checks complete. Review image answers and box geometry manually.",
        flush=True,
    )
    return int(any(row["status"] == "error" for row in report))


if __name__ == "__main__":
    raise SystemExit(main())
