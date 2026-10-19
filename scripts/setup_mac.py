"""Create or reuse this project's virtual environment; never replace an existing one."""

import os
import platform
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def install(root=ROOT):
    if sys.platform != "darwin" or sys.version_info[:2] != (3, 11):
        raise RuntimeError("請在 macOS 使用 Python 3.11；參閱 docs/INSTALL_MAC.md。")
    if int((platform.mac_ver()[0] or "0").split(".")[0]) < 14:
        raise RuntimeError("需要 macOS 14 或更新版本，尚未建立或修改環境。")
    root = Path(root).resolve()
    requirements = root / "requirements-macos-hashed.lock.txt"
    if not requirements.is_file() or not (root / "main.py").is_file():
        raise RuntimeError("來源不完整，請重新取得整個專案資料夾。")
    if not shutil.which("ollama"):
        raise RuntimeError(
            "找不到 Ollama，請先安裝並確認 ollama --version，再重新執行 install.command。"
        )
    environment = root / ".venv"
    python = environment / "bin/python"
    if environment.exists():
        if not python.is_file() or not (environment / "pyvenv.cfg").is_file():
            raise RuntimeError("既有 .venv 不完整；已保留未覆蓋。請先備份並依安裝指南處理。")
    else:
        print("正在建立專案專用 .venv…", flush=True)
        venv.EnvBuilder(with_pip=True).create(environment)
    check = subprocess.run(
        [
            str(python),
            "-c",
            "import sys; print(sys.prefix); print('.'.join(map(str,sys.version_info[:2])))",
        ],
        check=True,
        text=True,
        capture_output=True,
        timeout=30,
    ).stdout.splitlines()
    if len(check) != 2 or Path(check[0]).resolve() != environment or check[1] != "3.11":
        raise RuntimeError("既有 .venv 來源或 Python 版本不符；未安裝或覆蓋其中套件。")
    env = dict(os.environ)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    print("從官方 PyPI 安裝鎖定套件；首次下載較大，請等候…", flush=True)
    subprocess.run(
        [
            str(python),
            "-m",
            "pip",
            "--isolated",
            "install",
            "--disable-pip-version-check",
            "--require-hashes",
            "--only-binary=:all:",
            "--index-url",
            "https://pypi.org/simple",
            "-r",
            str(requirements),
        ],
        check=True,
        cwd=root,
        env=env,
    )
    subprocess.run([str(python), "-m", "pip", "check"], check=True, cwd=root, env=env)
    subprocess.run(
        [
            str(python),
            "-c",
            "from PySide6 import QtWidgets, QtNetwork, QtMultimedia; print('Qt 匯入正常')",
        ],
        check=True,
        cwd=root,
        env=env,
        timeout=30,
    )
    print("安裝完成。請雙擊 run.command，再至設定下載第一個模型。", flush=True)


def main():
    try:
        install()
        return 0
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(
            f"安裝未完成：{error}\n既有檔案未被自動刪除。請保留錯誤，依 docs/INSTALL_MAC.md 處理後重試。",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
