"""Read-only UI15 package/source comparison; does not launch a personal app."""
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader
from scripts.verify_ui11_bundle import shape


def main():
    root = Path(__file__).resolve().parents[1]
    folder = root / "dist/DeskCare-UI15"
    archive = CArchiveReader(str(folder / "DeskCare-UI15.exe"))
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith(".pyz")))
    modules = ("deskcare.app", "deskcare.domain.task_duplicates", "deskcare.importers.base", "deskcare.importers.task_times",
               "deskcare.services.task_service", "deskcare.storage.database", "deskcare.ui.task_dialog",
               "deskcare.ui.pages", "deskcare.ui.main_window", "deskcare.ai.cloud_task_assistant",
               "deskcare.ai.optional_local_llm")
    for module in modules:
        source = root.joinpath(*module.split(".")).with_suffix(".py")
        assert shape(pyz.extract(module)) == shape(compile(source.read_text(encoding="utf-8"), str(source), "exec")), module
    assert (folder / "_internal/PySide6/QtPdf.pyd").is_file()
    print(f"UI15: {len(modules)} modules and QtPdf verified; did not launch personal app.")


if __name__ == "__main__":
    main()
