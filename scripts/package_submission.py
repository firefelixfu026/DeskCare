"""Build a new, allowlisted offline submission bundle without touching old releases.

Run from the project root with the build virtualenv after constructing UI6 and
rendering the PDF. No user database, credentials or Git history are collected.
"""

from __future__ import annotations

import argparse
import hashlib
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
from types import CodeType
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
PREFIX = "DeskCare-UI6"
TEXT_SUFFIXES = {".py", ".md", ".txt", ".toml", ".ps1", ".cmd", ".json", ".svg", ".csv", ".spec"}
SOURCE_DIRS = {
    "deskcare": {".py"}, "tests": {".py"}, "scripts": {".py", ".ps1"},
    "docs": {".md"}, "examples": {".md", ".txt", ".csv", ".xlsx", ".json"},
    "assets": {".png", ".svg", ".md", ".ps1"}, "design": {".json"},
    "submission": {".md", ".cmd"},
}
SECRET_PATTERNS = (
    re.compile(rb"sk-(?:proj-)?[A-Za-z0-9_-]{40,}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{36,}"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def check_file(name: str, payload: bytes) -> None:
    path = PurePosixPath(name)
    assert not path.is_absolute() and ".." not in path.parts, name
    assert not any(p.lower() in {".git", ".venv", "__pycache__", ".env"} for p in path.parts), name
    assert path.suffix.lower() not in {".db", ".sqlite3", ".log", ".err", ".key", ".pem"}, name
    if path.suffix.lower() in TEXT_SUFFIXES:
        assert not any(pattern.search(payload) for pattern in SECRET_PATTERNS), f"Possible secret in {name}; inspect locally"


def add(archive: ZipFile, file: Path, name: str) -> None:
    payload = file.read_bytes()
    check_file(name, payload)
    archive.writestr(name, payload)


def validate_zip(path: Path) -> int:
    with ZipFile(path) as archive:
        assert archive.testzip() is None, path.name
        names = archive.namelist()
        assert len(names) == len(set(names)), "Duplicate archive paths"
        for name in names:
            check_file(name, archive.read(name))
        return len(names)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", default="release/DeskCare-UI6-submission-2026-10-20")
    args = parser.parse_args()
    destination = (ROOT / args.destination).resolve()
    release_root = (ROOT / "release").resolve()
    assert destination.is_relative_to(release_root) and destination != release_root, "Use a new subdirectory under release/"
    assert not destination.exists(), "Destination already exists; choose a new name to preserve it"
    executable = ROOT / f"dist/{PREFIX}/{PREFIX}.exe"
    assert hashlib.sha256(executable.read_bytes()).hexdigest().upper() == "F4009AD275606C943C066FA7B5459F1941AEF95BBEE7A69990EA1B3B39344582"
    # This script packages a frozen UI6 snapshot, not newer working sources.
    # Refuse to silently mix an old executable with the UI7 source tree.
    from PyInstaller.archive.readers import CArchiveReader
    def shape(code):
        return (code.co_code, code.co_names, code.co_varnames, code.co_flags,
                tuple(shape(value) if isinstance(value, CodeType) else value for value in code.co_consts))
    embedded = CArchiveReader(str(executable)).open_embedded_archive("PYZ.pyz")
    assert shape(embedded.extract("deskcare.app")) == shape(compile(
        (ROOT / "deskcare/app.py").read_bytes(), "deskcare.app", "exec"
    )), "UI6 packager requires matching frozen UI6 sources; do not mix UI7 sources with UI6 EXE"
    assert (executable.parent / "_internal/PySide6/Qt6Core.dll").is_file()
    destination.mkdir(parents=True)

    licenses = destination / "third_party_licenses"
    licenses.mkdir()
    license_sources = {
        "Python-LICENSE.txt": Path(sys.base_prefix) / "LICENSE.txt",
        "PyInstaller-COPYING.txt": Path(sys.prefix) / "Lib/site-packages/pyinstaller-6.22.3.dist-info/licenses/COPYING.txt",
        "PySide6-LicenseRef-Qt-Commercial.txt": Path(sys.prefix) / "Lib/site-packages/pyside6-6.12.0.dist-info/licenses/LicenseRef-Qt-Commercial.txt",
        "Shiboken6-LicenseRef-Qt-Commercial.txt": Path(sys.prefix) / "Lib/site-packages/shiboken6-6.12.0.dist-info/licenses/LicenseRef-Qt-Commercial.txt",
        "PySide6-Essentials-LicenseRef-Qt-Commercial.txt": Path(sys.prefix) / "Lib/site-packages/pyside6_essentials-6.12.0.dist-info/licenses/LicenseRef-Qt-Commercial.txt",
        "LGPL-3.0-only.txt": ROOT / "build/submission-licenses/LGPL-3.0-only.txt",
        "GPL-3.0-only.txt": ROOT / "build/submission-licenses/GPL-3.0-only.txt",
    }
    for name, source in license_sources.items():
        assert source.is_file(), source
        shutil.copyfile(source, licenses / name)

    for source in sorted((ROOT / "submission").glob("*.md")):
        shutil.copyfile(source, destination / source.name)
    shutil.copyfile(ROOT / "output/pdf/DeskCare_参赛项目说明_UI6.pdf", destination / "DeskCare_参赛项目说明_UI6.pdf")
    shots = destination / "screenshots"
    shots.mkdir()
    for name in ("today.png", "usage.png", "apps.png", "status.png", "report.png", "companion.png", "mascot-comfortable.png"):
        shutil.copyfile(ROOT / "build/ui6-final" / name, shots / name)
    (shots / "README.md").write_text(
        "# 截图来源\n\n当前 UI6 源代码通过 scripts.preview_ui 实际渲染的 Qt 界面，"
        "不是绘制的界面设计稿。使用临时数据库和明确标注的虚构演示数据，不读取真实用户库。"
        "它们用于展示已实现界面，不等同所有原生 Windows 交互已通过。\n", encoding="utf-8")
    historical = destination / "历史商业计划书_UI4快照"
    historical.mkdir()
    shutil.copyfile(ROOT / "output/pdf/DeskCare_商业计划书_2026-10-20.pdf", historical / "DeskCare_商业计划书_UI4快照.pdf")

    portable = destination / f"{PREFIX}-windows-x64-portable.zip"
    with ZipFile(portable, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for file in sorted(executable.parent.rglob("*")):
            if file.is_file():
                add(archive, file, f"{PREFIX}/{file.relative_to(executable.parent).as_posix()}")
        add(archive, ROOT / "submission/Demo.cmd", f"{PREFIX}/Demo.cmd")
        for file in sorted((ROOT / "submission").glob("*.md")):
            add(archive, file, f"{PREFIX}/{file.name}")
        for file in sorted(licenses.iterdir()):
            add(archive, file, f"{PREFIX}/third_party_licenses/{file.name}")

    source_zip = destination / f"{PREFIX}-source.zip"
    root_files = ["pyproject.toml", "requirements-dev.txt", "deskcare_launcher.py", "DeskCare.spec", ".gitattributes", ".gitignore"]
    root_files.extend(file.name for file in ROOT.glob("*.md"))
    with ZipFile(source_zip, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for name in sorted(set(root_files)):
            add(archive, ROOT / name, f"{PREFIX}-source/{name}")
        for directory, extensions in SOURCE_DIRS.items():
            for file in sorted((ROOT / directory).rglob("*")):
                if file.is_file() and file.suffix.lower() in extensions and "__pycache__" not in file.parts:
                    add(archive, file, f"{PREFIX}-source/{file.relative_to(ROOT).as_posix()}")
        for file in sorted(licenses.iterdir()):
            add(archive, file, f"{PREFIX}-source/third_party_licenses/{file.name}")

    counts = {path.name: validate_zip(path) for path in (portable, source_zip)}
    audit = destination / "归档校验记录.md"
    audit.write_text(
        "# 归档校验\n\n" + "\n".join(f"- {name}：{count} 个条目，CRC、路径和高置信密钥格式检查通过。" for name, count in counts.items()) +
        "\n\n来源白名单与完整性检查不是完整安全审计。没有收集 .git、虚拟环境、独立用户库或 .env。"
        "EXE 与最终源码的模块结构比对记录见验收文件。\n", encoding="utf-8")
    sums = []
    for file in sorted(destination.rglob("*")):
        if file.is_file():
            sums.append(f"{hashlib.sha256(file.read_bytes()).hexdigest().upper()}  {file.relative_to(destination).as_posix()}")
    (destination / "SHA256SUMS.txt").write_text("\n".join(sums) + "\n", encoding="utf-8")
    print(destination)
    for path in (portable, source_zip):
        print(path.name, len(path.read_bytes()), "bytes; entries", counts[path.name])


if __name__ == "__main__":
    main()
