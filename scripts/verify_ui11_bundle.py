"""Read-only: compare changed bundled Python modules with source bytecode."""
from pathlib import Path
from types import CodeType

from PyInstaller.archive.readers import CArchiveReader


def shape(code):
    return (code.co_code, tuple(shape(value) if isinstance(value, CodeType) else value for value in code.co_consts),
            code.co_names, code.co_varnames, code.co_freevars, code.co_cellvars,
            code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount, code.co_flags)


def main():
    root = Path(__file__).resolve().parents[1]
    package = root / "dist" / "DeskCare-UI11"
    archive = CArchiveReader(str(package / "DeskCare-UI11.exe"))
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith(".pyz")))
    modules = ("deskcare.app", "deskcare.services.personalization_service", "deskcare.services.reminder_advice",
               "deskcare.ai.reminder_advisor", "deskcare.ui.reminder_advice", "deskcare.ui.main_window", "deskcare.ui.pages")
    for module in modules:
        source = root.joinpath(*module.split(".")).with_suffix(".py")
        expected = compile(source.read_text(encoding="utf-8"), str(source), "exec")
        assert shape(pyz.extract(module)) == shape(expected), f"Source mismatch: {module}"
    assert (package / "_internal" / "PySide6" / "QtCore.pyd").is_file()
    print(f"Verified {len(modules)} UI11 bundled modules against source and QtCore dependency; did not launch app.")


if __name__ == "__main__":
    main()
