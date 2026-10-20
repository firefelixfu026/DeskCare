"""Read-only UI12 bundle/source consistency check, no app launch."""
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader
from scripts.verify_ui11_bundle import shape


def main():
    root = Path(__file__).resolve().parents[1]
    package = root / "dist" / "DeskCare-UI12"
    archive = CArchiveReader(str(package / "DeskCare-UI12.exe"))
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith(".pyz")))
    modules = ("deskcare.app", "deskcare.services.personalization_service", "deskcare.services.reminder_advice", "deskcare.ai.reminder_advisor",
               "deskcare.ai.structured_transport", "deskcare.services.assistant_service",
               "deskcare.ui.assistant", "deskcare.ui.reminder_advice", "deskcare.ui.main_window")
    for module in modules:
        source = root.joinpath(*module.split(".")).with_suffix(".py")
        assert shape(pyz.extract(module)) == shape(compile(source.read_text(encoding="utf-8"), str(source), "exec")), module
    assert (package / "_internal" / "PySide6" / "QtCore.pyd").is_file()
    print(f"Verified {len(modules)} UI12 modules against current source and QtCore dependency; did not launch app.")


if __name__ == "__main__":
    main()
