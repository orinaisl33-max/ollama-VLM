"""Read-only installation doctor: no model downloads, recording or account access."""

import argparse
import http.client
import importlib.metadata
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def local_models():
    connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=5)
    try:
        connection.request("GET", "/api/tags")
        response = connection.getresponse()
        data = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(data) > 1024 * 1024:
            raise ValueError("本機模型清單回應無效")
        value = json.loads(data)
        if not isinstance(value, dict) or not isinstance(value.get("models"), list):
            raise ValueError("本機模型清單格式無效")
        if any(
            not isinstance(row, dict) or not isinstance(row.get("name"), str)
            for row in value["models"]
        ):
            raise ValueError("本機模型清單包含無效項目")
        return {row["name"] for row in value["models"]}
    finally:
        connection.close()


def inspect(root=ROOT, *, offline=False, require_model=False):
    root = Path(root).resolve()
    rows = []

    def add(check, passed, detail, *, optional=False):
        rows.append(
            {
                "check": check,
                "status": "PASS" if passed else ("WARN" if optional else "FAIL"),
                "detail": detail,
            }
        )

    add(
        "Python",
        sys.version_info[:2] == (3, 11),
        "本輪支援基線為 Python 3.11；目前 " + platform.python_version(),
    )
    add(
        "系統",
        sys.platform == "darwin" and int((platform.mac_ver()[0] or "0").split(".")[0]) >= 14,
        "需 macOS 14 以上；目前 " + (platform.mac_ver()[0] or sys.platform),
    )
    add(
        "架構",
        platform.machine() == "arm64",
        platform.machine() + "；Apple Silicon 為本輪實測範圍",
        optional=True,
    )
    add(
        "虛擬環境", Path(sys.prefix).resolve() == root / ".venv", "請使用專案 .venv/bin/python 執行"
    )
    for name in ("main.py", "run.command", "scripts/mac_python.py", "logo.png"):
        add("來源 " + name, (root / name).is_file(), "必要來源檔案")
    lock = root / "requirements.lock.txt"
    add("套件清單", lock.is_file(), "requirements.lock.txt")
    if lock.is_file():
        for line in lock.read_text().splitlines():
            if "==" not in line or line.startswith("#"):
                continue
            name, expected = line.strip().split("==", 1)
            try:
                actual = importlib.metadata.version(name)
            except importlib.metadata.PackageNotFoundError:
                actual = "未安裝"
            add(name, actual == expected, f"需要 {expected}；目前 {actual}")
    try:
        result = subprocess.run(
            [sys.executable, "-c", "from PySide6 import QtWidgets, QtNetwork, QtMultimedia"],
            capture_output=True,
            timeout=30,
        )
        add(
            "Qt 元件",
            result.returncode == 0,
            "圖形／網路／多媒體載入"
            + ("正常" if result.returncode == 0 else "失敗，請重新執行 install.command"),
        )
    except (OSError, subprocess.SubprocessError):
        add("Qt 元件", False, "元件載入失敗或逾時")
    add("Ollama CLI", bool(shutil.which("ollama")), "缺少時依安裝指南安裝 Ollama")
    if not offline:
        try:
            models = local_models()
            # Read only the fixed catalog, without importing the Qt application.
            import runpy

            catalog = runpy.run_path(str(root / "labchat/config.py"))["MODELS"]
            count = len(models & {m.identifier for m in catalog})
            add("本機服務", True, "127.0.0.1:11434 已連線")
            add(
                "可用模型",
                count > 0,
                f"{count} 個選單模型已安裝；未下載時請開啟程式至設定下載",
                optional=not require_model,
            )
        except (OSError, ValueError, http.client.HTTPException):
            add(
                "本機服務",
                False,
                "尚未連線；run.command 可啟動服務，再重新檢查",
                optional=not require_model,
            )
    add(
        "Whisper（選用）",
        bool(shutil.which("whisper-cli")) and (root / "models/ggml-small.bin").is_file(),
        "不影響打字／圖片聊天；語音另需可用麥克風與權限",
        optional=True,
    )
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--offline", action="store_true", help="略過本機 HTTP 服務檢查")
    parser.add_argument(
        "--require-model", action="store_true", help="驗收時要求至少一個模型及服務已就緒"
    )
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    if args.offline and args.require_model:
        parser.error("--offline 與 --require-model 不能同時使用")
    rows = inspect(offline=args.offline, require_model=args.require_model)
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            print(f"[{row['status']}] {row['check']}：{row['detail']}")
    return int(any(row["status"] == "FAIL" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
