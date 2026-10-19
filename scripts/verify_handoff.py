"""Verify extracted source files against the bundled manifest; standard library only."""

import hashlib
import json
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "restore.command",
    "Brewfile",
    "environment.lock.json",
    "requirements-macos-hashed.lock.txt",
    "scripts/restore_environment.py",
    "docs/REBUILD_MAC.md",
    "install.command",
    "scripts/setup_mac.py",
    "scripts/check_install.py",
    "docs/INSTALL_MAC.md",
    "docs/PUBLISHING.md",
    "MAC_MINI_M4_START.md",
    "labchat/service_widgets.py",
    "labchat/timestamps.py",
    "labchat/assistant_activity.py",
    "labchat/model_settings.py",
    "labchat/speech_stream.py",
    "START_HERE.md",
    "VOICE_INPUT.md",
    "LABELME.md",
    "FEATURES.md",
    "scripts/mac_python.py",
    "labchat/dictation.py",
    "labchat/labelme_export.py",
    "labchat/theme.py",
    "CODEX_HANDOFF.md",
    "WINDOWS_SETUP.md",
    "MAC_SETUP.md",
    "MAC_CODEX_HANDOFF.md",
    "MAC_PACKAGE_REVIEW.md",
    "PACKAGE_REVIEW.md",
    "README.md",
    "main.py",
    "logo.png",
    "run_windows.cmd",
    "run.command",
    "requirements.lock.txt",
    "scripts/verify_handoff.py",
}


def verify(root: Path) -> int:
    manifest = json.loads((root / "HANDOFF_MANIFEST.json").read_text(encoding="utf-8"))
    if manifest.get("format") != 1 or not isinstance(manifest.get("files"), dict):
        raise ValueError("Unsupported or invalid manifest")
    files = manifest["files"]
    if not REQUIRED.issubset(files):
        raise ValueError("Required handoff files are missing from the manifest")
    for name, expected in files.items():
        relative = PurePosixPath(name)
        if relative.is_absolute() or ".." in relative.parts or "\\" in name or ":" in name:
            raise ValueError("Unsafe manifest path")
        path = root.joinpath(*relative.parts)
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError(f"Unsafe source path: {name}")
        data = path.read_bytes()
        if len(data) != expected["size"] or hashlib.sha256(data).hexdigest() != expected["sha256"]:
            raise ValueError(f"File content mismatch: {name}")
    return len(files)


if __name__ == "__main__":
    try:
        count = verify(ROOT)
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit(f"Verification failed: {error}") from error
    print(f"Verified {count} source files. No installation or network access performed.")
