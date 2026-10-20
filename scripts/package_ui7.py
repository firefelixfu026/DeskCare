"""Archive UI7 with matching source code and upstream license copies."""

from pathlib import Path
import hashlib
import shutil
from types import CodeType
from zipfile import ZIP_DEFLATED, ZipFile

from scripts.package_submission import ROOT, SOURCE_DIRS, add, validate_zip


def main():
    from PyInstaller.archive.readers import CArchiveReader

    output = ROOT / "release/DeskCare-UI7-2026-10-20"
    assert not output.exists(), "Preserve existing archives; choose a new output directory in the script"
    program = ROOT / "dist/DeskCare-UI7"
    executable = program / "DeskCare-UI7.exe"
    assert hashlib.sha256(executable.read_bytes()).hexdigest().upper() == "A075F7699C11FBD522E4EC53EA7E0EB96E5CE2B2C6170F3E2CF6F3FFE3F9E415"
    embedded = CArchiveReader(str(executable)).open_embedded_archive("PYZ.pyz")
    def shape(code):
        return (code.co_code, code.co_names, code.co_varnames, code.co_flags,
                tuple(shape(value) if isinstance(value, CodeType) else value for value in code.co_consts))
    for module in ("deskcare.app", "deskcare.ai.cloud_task_assistant", "deskcare.domain.break_policy",
                   "deskcare.domain.types", "deskcare.services.activity_service", "deskcare.services.reminder_service",
                   "deskcare.ui.main_window", "deskcare.ui.pages", "deskcare.ui.reminder_popup"):
        path = ROOT / Path(*module.split(".")).with_suffix(".py")
        assert shape(embedded.extract(module)) == shape(compile(path.read_bytes(), module, "exec")), module
    # Unmodified dependency versions match the frozen UI6 package. A source
    # archive also carries these notices at its root for subsequent reproduction.
    licenses = ROOT / "third_party_licenses"
    if not licenses.is_dir():
        licenses = ROOT / "release/DeskCare-UI6-提交材料-2026-10-20/third_party_licenses"
    assert licenses.is_dir(), "Provide original third_party_licenses before packaging"
    output.mkdir(parents=True)
    guide = ROOT / "docs/UI7_提醒与DeepSeek说明.md"
    shutil.copyfile(guide, output / guide.name)
    for name in ("settings-reminders.png", "reminder-preview.png"):
        shutil.copyfile(ROOT / "build/ui7-preview" / name, output / name)
    portable = output / "DeskCare-UI7-windows-x64-portable.zip"
    with ZipFile(portable, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(program.rglob("*")):
            if path.is_file():
                add(archive, path, "DeskCare-UI7/" + path.relative_to(program).as_posix())
        add(archive, ROOT / "submission/UI7_Demo.cmd", "DeskCare-UI7/Demo.cmd")
        add(archive, guide, "DeskCare-UI7/使用说明.md")
        add(archive, ROOT / "submission/依赖与素材说明.md", "DeskCare-UI7/依赖与素材说明.md")
        for path in sorted(licenses.iterdir()):
            if path.is_file():
                add(archive, path, "DeskCare-UI7/third_party_licenses/" + path.name)
    source = output / "DeskCare-UI7-source.zip"
    with ZipFile(source, "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(ROOT.iterdir()):
            if path.is_file() and (path.suffix == ".md" or path.name in {
                "pyproject.toml", "requirements-dev.txt", "deskcare_launcher.py", "DeskCare.spec", ".gitattributes", ".gitignore"
            }):
                add(archive, path, "DeskCare-UI7-source/" + path.name)
        for directory, extensions in SOURCE_DIRS.items():
            for path in sorted((ROOT / directory).rglob("*")):
                if path.is_file() and path.suffix.lower() in extensions and "__pycache__" not in path.parts:
                    add(archive, path, "DeskCare-UI7-source/" + path.relative_to(ROOT).as_posix())
        for path in sorted(licenses.iterdir()):
            if path.is_file():
                add(archive, path, "DeskCare-UI7-source/third_party_licenses/" + path.name)
    for path in (portable, source):
        print(path.name, len(path.read_bytes()), "bytes; CRC/path/secret-pattern checks passed;", validate_zip(path), "entries")
    checksums = [f"{hashlib.sha256(path.read_bytes()).hexdigest().upper()}  {path.name}"
                 for path in sorted(output.iterdir()) if path.is_file()]
    (output / "SHA256SUMS.txt").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    print(output)


if __name__ == "__main__":
    main()
