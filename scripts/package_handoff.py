"""Create a source-only migration ZIP; exclude local environments and private samples."""

import argparse
import hashlib
import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ("labchat", "assets", "tests", "scripts", "docs")
SUFFIXES = {
    "labchat": {".py"},
    "assets": {".svg"},
    "tests": {".py"},
    "scripts": {".py"},
    "docs": {".md", ".svg", ".png"},
}
FILES = (
    "main.py",
    "logo.png",
    "run.command",
    "run_windows.cmd",
    "pyproject.toml",
    ".gitignore",
    ".gitattributes",
    "install.command",
    "restore.command",
    "Brewfile",
    "environment.lock.json",
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("windows", "mac"), default="windows")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    paths = [ROOT / name for name in FILES]
    paths += list(ROOT.glob("*.md")) + list(ROOT.glob("requirements*.txt"))
    for folder in FOLDERS:
        paths.extend(
            path
            for path in (ROOT / folder).rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix in SUFFIXES[folder]
        )
    output = args.output_dir / f"labchat-{args.target}-handoff.zip"
    output.parent.mkdir(exist_ok=True)
    manifest = {}
    temporary = output.with_suffix(".zip.tmp")
    with ZipFile(temporary, "w", ZIP_DEFLATED) as archive:
        for path in sorted(set(paths)):
            if (
                path.is_symlink()
                or not path.is_file()
                or not path.resolve().is_relative_to(ROOT.resolve())
            ):
                raise ValueError(f"Missing or symbolic source file: {path.name}")
            name = path.relative_to(ROOT).as_posix()
            data = path.read_bytes()
            manifest[name] = {"size": len(data), "sha256": hashlib.sha256(data).hexdigest()}
            info = ZipInfo.from_file(path, "labchat/" + name)
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, data)
        archive.writestr(
            "labchat/HANDOFF_MANIFEST.json",
            json.dumps({"format": 1, "files": manifest}, ensure_ascii=False, indent=2) + "\n",
        )
    temporary.replace(output)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(
        digest + "  " + output.name + "\n", encoding="ascii"
    )
    print(f"Created {output} ({output.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
