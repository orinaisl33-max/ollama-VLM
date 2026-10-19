"""Confirmed, local-only environment reconstruction using version/hash baselines."""

import argparse
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from setup_mac import ROOT, install


def manifest(root=ROOT):
    value = json.loads((Path(root) / "environment.lock.json").read_text())
    if not isinstance(value, dict) or value.get("format") != 1:
        raise ValueError("不支援的環境基準格式")
    models, profiles = value.get("models"), value.get("profiles")
    if (
        not isinstance(models, dict)
        or not isinstance(profiles, dict)
        or set(profiles) != {"basic", "full"}
    ):
        raise ValueError("環境基準缺少模型／方案")
    for name, item in models.items():
        if (
            not isinstance(name, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,200}", name)
            or not isinstance(item, dict)
            or not re.fullmatch(r"[0-9a-f]{64}", str(item.get("digest", "")))
            or type(item.get("bytes")) is not int
            or item["bytes"] <= 0
        ):
            raise ValueError("模型基準欄位不符")
    if any(
        not isinstance(names, list)
        or not names
        or any(not isinstance(name, str) or name not in models for name in names)
        for names in profiles.values()
    ):
        raise ValueError("方案包含不支援的模型")
    whisper = value.get("whisper", {})
    if not isinstance(whisper, dict):
        raise ValueError("Whisper 基準類型無效")
    if (
        whisper.get("url")
        != "https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin"
        or not re.fullmatch(r"[0-9a-f]{64}", str(whisper.get("sha256", "")))
        or type(whisper.get("bytes")) is not int
        or not 0 < whisper["bytes"] <= 1024**3
    ):
        raise ValueError("Whisper 基準不符")
    return value


def api(path):
    connection = http.client.HTTPConnection("127.0.0.1", 11434, timeout=5)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        data = response.read(1024 * 1024 + 1)
        if response.status != 200 or len(data) > 1024 * 1024:
            raise ValueError("本機 Ollama 回應無效")
        value = json.loads(data)
        if not isinstance(value, dict):
            raise ValueError("本機 Ollama JSON 類型無效")
        return value
    finally:
        connection.close()


def model_inventory():
    data = api("/api/tags")
    if not isinstance(data, dict) or not isinstance(data.get("models"), list):
        raise ValueError("本機模型清單格式無效")
    rows = data["models"]
    if any(
        not isinstance(row, dict)
        or not isinstance(row.get("name"), str)
        or not isinstance(row.get("digest"), str)
        for row in rows
    ):
        raise ValueError("本機模型清單欄位無效")
    return {row["name"]: row["digest"].removeprefix("sha256:") for row in rows}


def ollama_env():
    env = dict(os.environ)
    env.update(
        OLLAMA_HOST="127.0.0.1:11434",
        OLLAMA_NO_CLOUD="1",
        OLLAMA_MAX_LOADED_MODELS="1",
        OLLAMA_NUM_PARALLEL="1",
        NO_PROXY="localhost,127.0.0.1,::1",
        no_proxy="localhost,127.0.0.1,::1",
    )
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    return env


def ensure_service(root, env):
    try:
        api("/api/version")
        return
    except (OSError, ValueError, http.client.HTTPException):
        pass
    logs = Path(root) / ".logs"
    logs.mkdir(exist_ok=True)
    # Keep the server running for run.command; never stop an existing service.
    with (logs / "restore-ollama.log").open("ab") as output:
        process = subprocess.Popen(
            [shutil.which("ollama"), "serve"],
            stdin=subprocess.DEVNULL,
            stdout=output,
            stderr=subprocess.STDOUT,
            env=env,
            start_new_session=True,
        )
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        try:
            api("/api/version")
            return
        except (OSError, ValueError, http.client.HTTPException):
            if process.poll() is not None:
                break
            time.sleep(0.5)
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
    raise RuntimeError("無法啟動 Ollama；請查看 .logs/restore-ollama.log，不要開放外網監聽。")


def restore_models(names, baseline, env):
    known = baseline["models"]
    if not names or any(name not in known for name in names):
        raise ValueError("僅允許環境基準中的模型名稱")
    installed = model_inventory()
    for name in names:
        expected = known[name]["digest"]
        if name not in installed:
            print("下載模型：" + name, flush=True)
            subprocess.run(
                [shutil.which("ollama"), "pull", name], check=True, env=env, timeout=3600
            )
            installed = model_inventory()
        if installed.get(name) != expected:
            raise RuntimeError(
                f"{name} 與環境基準 digest 不符；原模型未刪除或覆蓋。請由維護者核對上游版本，不能宣稱完全復刻。"
            )
        print("模型 digest 確認：" + name, flush=True)


def file_hash(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


class HTTPSOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if not newurl.startswith("https://"):
            raise ValueError("拒絕非 HTTPS 重新導向")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def restore_whisper(root, specification):
    target = Path(root) / "models" / "ggml-small.bin"
    expected = specification["sha256"]
    if target.exists():
        if file_hash(target) != expected:
            raise RuntimeError("既有 Whisper 模型校驗失敗，已保留未覆蓋；請備份檢查後重試。")
        print("Whisper SHA256 確認", flush=True)
        return
    target.parent.mkdir(exist_ok=True)
    print("正在下載 Whisper small，約 488MB；完成後會核對 SHA256…", flush=True)
    if not specification["url"].startswith("https://"):
        raise ValueError("僅允許 HTTPS 模型下載")
    fd, temporary = tempfile.mkstemp(prefix=".ggml-small-", suffix=".part", dir=target.parent)
    os.close(fd)
    part = Path(temporary)
    # A .part file is never activated until size and SHA256 both match.
    try:
        request = urllib.request.Request(
            specification["url"], headers={"User-Agent": "labchat-environment-restore/1"}
        )
        opener = urllib.request.build_opener(HTTPSOnlyRedirect())
        with opener.open(request, timeout=30) as source, part.open("wb") as output:
            if not source.geturl().startswith("https://"):
                raise ValueError("拒絕非 HTTPS 模型下載")
            received = 0
            deadline = time.monotonic() + 1800
            while chunk := source.read(1024 * 1024):
                received += len(chunk)
                if received > specification["bytes"] or time.monotonic() > deadline:
                    raise ValueError("模型超出容量或下載時間限制")
                output.write(chunk)
                if received // (32 * 1024 * 1024) != (received - len(chunk)) // (32 * 1024 * 1024):
                    print(f"Whisper 下載 {received * 100 // specification['bytes']}%", flush=True)
        if part.stat().st_size != specification["bytes"] or file_hash(part) != expected:
            raise ValueError("Whisper 下載大小或 SHA256 不符，未啟用")
        os.link(part, target)
        part.unlink()
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    print("Whisper 下載與 SHA256 確認", flush=True)


def rebuild(profile, *, yes=False, verify_only=False, root=ROOT):
    root = Path(root).resolve()
    baseline = manifest(root)
    names = baseline["profiles"][profile]
    if profile == "full" and not shutil.which("whisper-cli"):
        raise RuntimeError(
            "完整模式缺少 whisper-cli。請先依 docs/REBUILD_MAC.md 安裝系統工具，再重試。"
        )
    amount = sum(baseline["models"][name]["bytes"] for name in names)
    print(
        f"復刻方案：{profile}；{len(names)} 個模型，模型標示容量合計約 {amount / 1e9:.2f} GB（既有校驗通過者略過）。",
        flush=True,
    )
    print(
        "Python/Qt 套件約需額外 2GB 工作空間。系統工具不會自動安裝或降版，麥克風權限不會自動更改。",
        flush=True,
    )
    if verify_only:
        installed = model_inventory()
        for name in names:
            if installed.get(name) != baseline["models"][name]["digest"]:
                raise RuntimeError("模型不存在或 digest 不符：" + name)
        if profile == "full":
            target = root / "models/ggml-small.bin"
            if not target.is_file() or file_hash(target) != baseline["whisper"]["sha256"]:
                raise RuntimeError("Whisper 模型尚未下載或校驗不符")
    else:
        if not yes:
            if (
                not sys.stdin.isatty()
                or input("將建立／檢查 venv、連線下載套件與模型。繼續請輸入 YES：").strip() != "YES"
            ):
                raise RuntimeError("未確認，未開始重建。可重新執行並確認；自動化使用 --yes。")
        install(root)
        env = ollama_env()
        ensure_service(root, env)
        version = api("/api/version").get("version", "unknown")
        print(
            f"Ollama {version}；已驗證引擎基線為 {baseline['platform']['tested_ollama']}，本流程不會自動更改引擎版本。",
            flush=True,
        )
        restore_models(names, baseline, env)
        if profile == "full":
            restore_whisper(root, baseline["whisper"])
    python = root / ".venv/bin/python"
    subprocess.run(
        [str(python), str(root / "scripts/check_install.py"), "--require-model"],
        check=True,
        cwd=root,
        env=ollama_env(),
    )
    if not verify_only:
        validation_env = ollama_env()
        validation_env["QT_QPA_PLATFORM"] = "offscreen"
        print("正在以暫存資料驗證文字／圖片聊天與顯示，不讀取私人對話…", flush=True)
        subprocess.run(
            [str(python), str(root / "scripts/smoke_local.py")],
            check=True,
            cwd=root,
            env=validation_env,
            timeout=330,
        )
        if profile == "full":
            print("正在以合成音訊驗證 TTS 與 Whisper；不錄音、不播放喇叭…", flush=True)
            subprocess.run(
                [str(python), str(root / "scripts/smoke_dictation.py")],
                check=True,
                cwd=root,
                env=validation_env,
                timeout=220,
            )
    print(
        "復刻基準檢查通過。請用 run.command 開啟並實測；麥克風收音與音色聽感仍需人工確認。",
        flush=True,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("basic", "full"))
    parser.add_argument("--yes", action="store_true", help="明確同意套件與模型下載")
    parser.add_argument("--verify-only", action="store_true", help="只檢查，不下載或啟動服務")
    args = parser.parse_args()
    profile = args.profile
    try:
        if profile is None:
            if not sys.stdin.isatty():
                raise RuntimeError("請指定 --profile basic 或 --profile full")
            choice = input(
                "1：基本圖文（1 模型）　2：完整模型＋Whisper（9 模型）\n請輸入 1 或 2："
            ).strip()
            if choice not in ("1", "2"):
                raise RuntimeError("方案未選定，未開始重建")
            profile = "basic" if choice == "1" else "full"
        rebuild(profile, yes=args.yes, verify_only=args.verify_only)
        return 0
    except (
        OSError,
        RuntimeError,
        ValueError,
        subprocess.SubprocessError,
        http.client.HTTPException,
    ) as error:
        print("復刻未完成：" + str(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已停止；既有環境和模型保留，可稍後重試。", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
