"""Local Mac interpreter wrapper declaring microphone usage; not a distribution bundle."""

import hashlib
import os
import plistlib
import shutil
import site
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def prepare():
    if sys.platform != "darwin":
        raise RuntimeError("This launcher requires macOS")
    app = ROOT / ".runtime" / "LabChat.app"
    executable = app / "Contents" / "MacOS" / "LabChat"
    source = Path(sys.base_prefix) / "Resources" / "Python.app" / "Contents" / "MacOS" / "Python"
    if not source.is_file():
        source = Path(sys._base_executable).resolve()
    info = {
        "CFBundleIdentifier": "org.ai-system-lab.labchat.local",
        "CFBundleName": "人工智慧系統實驗室",
        "CFBundleExecutable": "LabChat",
        "CFBundlePackageType": "APPL",
        "CFBundleVersion": "1.0",
        "NSMicrophoneUsageDescription": "錄製您主動開始的語音輸入，在本機轉為可確認及修改的文字。",
        "NSHighResolutionCapable": True,
    }
    plist = app / "Contents" / "Info.plist"
    expected = plistlib.dumps(info)
    fingerprint = app / "Contents" / "Resources" / "interpreter.sha256"
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    if (
        not executable.is_file()
        or not fingerprint.is_file()
        or fingerprint.read_text() != digest
        or not plist.is_file()
        or plist.read_bytes() != expected
        or subprocess.run(
            ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(app)],
            capture_output=True,
        ).returncode
        != 0
    ):
        executable.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, executable)
        plist.write_bytes(expected)
        fingerprint.parent.mkdir(exist_ok=True)
        fingerprint.write_text(digest)
        subprocess.run(
            ["/usr/bin/codesign", "--force", "--sign", "-", str(app)],
            check=True,
            capture_output=True,
        )
    return executable


def main():
    executable = prepare()
    env = dict(os.environ)
    env.pop("__PYVENV_LAUNCHER__", None)
    env["PYTHONHOME"] = sys.base_prefix
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), *site.getsitepackages()])
    os.execve(str(executable), [str(executable), str(ROOT / "main.py")], env)


if __name__ == "__main__":
    main()
