"""Compare UI14 packaged modules to source, without launching a personal app."""
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader
from scripts.verify_ui11_bundle import shape


def main():
    root = Path(__file__).resolve().parents[1]
    folder = root / "dist/DeskCare-UI14"
    archive = CArchiveReader(str(folder / "DeskCare-UI14.exe"))
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith(".pyz")))
    modules = ("deskcare.app", "deskcare.storage.database", "deskcare.services.task_service", "deskcare.ui.pages",
               "deskcare.ui.task_dialog", "deskcare.importers.task_times", "deskcare.ui.main_window")
    for module in modules:
        source = root.joinpath(*module.split(".")).with_suffix(".py")
        assert shape(pyz.extract(module)) == shape(compile(source.read_text(encoding="utf-8"),str(source),"exec")),module
    assert (folder / "_internal/PySide6/QtPdf.pyd").is_file()
    print(f"UI14 verified {len(modules)} modules and QtPdf; did not launch app.")


if __name__ == "__main__": main()
