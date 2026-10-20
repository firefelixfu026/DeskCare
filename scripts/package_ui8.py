"""Archive frozen UI8, rejecting stale binaries and private database copies."""

from pathlib import Path
import hashlib
import shutil
from types import CodeType
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.package_submission import ROOT, SOURCE_DIRS, add, validate_zip

EXE_SHA256 = "E6E8E0DE82F22949BC72AA23AD7E3B33E4BA69DEE4809BEBF094986FC181639C"
MODULES = (
    "deskcare.app", "deskcare.demo_scenario", "deskcare.domain.types",
    "deskcare.importers.base", "deskcare.importers.text_importer", "deskcare.importers.task_times",
    "deskcare.ai.optional_local_llm", "deskcare.ai.cloud_task_assistant",
    "deskcare.storage.database", "deskcare.services.activity_service",
    "deskcare.services.task_service", "deskcare.services.reminder_service",
    "deskcare.ui.main_window", "deskcare.ui.pages", "deskcare.ui.task_dialog",
    "deskcare.ui.pagination", "deskcare.ui.charts",
)


def verify_binary():
    from PyInstaller.archive.readers import CArchiveReader
    executable = ROOT / "dist/DeskCare-UI8/DeskCare-UI8.exe"
    assert hashlib.sha256(executable.read_bytes()).hexdigest().upper() == EXE_SHA256
    assert (executable.parent / "_internal/PySide6/Qt6Core.dll").is_file()
    embedded = CArchiveReader(str(executable)).open_embedded_archive("PYZ.pyz")
    def shape(code):
        return (code.co_code, code.co_names, code.co_varnames, code.co_flags,
                tuple(shape(value) if isinstance(value, CodeType) else value for value in code.co_consts))
    for module in MODULES:
        path = ROOT / Path(*module.split(".")).with_suffix(".py")
        assert shape(embedded.extract(module)) == shape(compile(path.read_bytes(), module, "exec")), module
    print(f"EXE hash, QtCore and {len(MODULES)} embedded source modules verified")
    return executable.parent


def main():
    output = ROOT / "release/DeskCare-UI8-2026-10-20"
    assert not output.exists(), "Preserve old archives; choose a new output name"
    program = verify_binary()
    licenses = ROOT / "third_party_licenses"
    if not licenses.is_dir():
        licenses = ROOT / "release/DeskCare-UI6-提交材料-2026-10-20/third_party_licenses"
    assert licenses.is_dir(), "Provide original upstream notices before packaging"
    output.mkdir(parents=True)
    guide = ROOT / "docs/UI8_任务与小时统计说明.md"
    shutil.copyfile(guide, output / guide.name)
    for name in ("today.png", "usage.png", "usage-weekly.png", "import-preview.png"):
        shutil.copyfile(ROOT / "build/ui8-complete-preview" / name, output / name)
    portable = output / "DeskCare-UI8-windows-x64-portable.zip"
    with ZipFile(portable, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(program.rglob("*")):
            if path.is_file():
                assert not path.name.endswith(".before-ui8"), path
                add(archive, path, "DeskCare-UI8/" + path.relative_to(program).as_posix())
        add(archive, ROOT / "submission/UI8_Demo.cmd", "DeskCare-UI8/Demo.cmd")
        add(archive, guide, "DeskCare-UI8/使用说明.md")
        add(archive, ROOT / "submission/依赖与素材说明.md", "DeskCare-UI8/依赖与素材说明.md")
        for path in sorted(licenses.iterdir()):
            if path.is_file():
                add(archive, path, "DeskCare-UI8/third_party_licenses/" + path.name)
    source = output / "DeskCare-UI8-source.zip"
    with ZipFile(source, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.iterdir()):
            if path.is_file() and (path.suffix == ".md" or path.name in {
                "pyproject.toml", "requirements-dev.txt", "deskcare_launcher.py", "DeskCare.spec", ".gitattributes", ".gitignore"
            }):
                add(archive, path, "DeskCare-UI8-source/" + path.name)
        for directory, extensions in SOURCE_DIRS.items():
            for path in sorted((ROOT / directory).rglob("*")):
                if path.is_file() and path.suffix.lower() in extensions and "__pycache__" not in path.parts:
                    add(archive, path, "DeskCare-UI8-source/" + path.relative_to(ROOT).as_posix())
        for path in sorted(licenses.iterdir()):
            if path.is_file():
                add(archive, path, "DeskCare-UI8-source/third_party_licenses/" + path.name)
    for path in (portable, source):
        count = validate_zip(path)
        with ZipFile(path) as archive:
            assert not any(name.endswith(".before-ui8") for name in archive.namelist())
            if path == source:
                for name in archive.namelist():
                    if name.endswith(".py"):
                        assert archive.read(name) == (ROOT / name.split("/", 1)[1]).read_bytes(), name
            else:
                assert hashlib.sha256(archive.read("DeskCare-UI8/DeskCare-UI8.exe")).hexdigest().upper() == EXE_SHA256
        print(path.name, path.stat().st_size, "bytes; CRC/path/secret-pattern/content checks passed;", count, "entries")
    checksums = [f"{hashlib.sha256(path.read_bytes()).hexdigest().upper()}  {path.name}"
                 for path in sorted(output.iterdir()) if path.is_file()]
    (output / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
