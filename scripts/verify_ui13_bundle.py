"""Read-only UI13 bundle verification; does not launch a personal app."""
from pathlib import Path
from PyInstaller.archive.readers import CArchiveReader
from scripts.verify_ui11_bundle import shape


def main():
    root = Path(__file__).resolve().parents[1]
    package = root / "dist" / "DeskCare-UI13"
    archive = CArchiveReader(str(package / "DeskCare-UI13.exe"))
    pyz = archive.open_embedded_archive(next(name for name in archive.toc if name.endswith(".pyz")))
    modules = ("deskcare.app", "deskcare.domain.durations", "deskcare.domain.lab_reading",
               "deskcare.importers.lab_source", "deskcare.services.lab_reading_service", "deskcare.ui.lab_reading",
               "deskcare.services.assistant_service", "deskcare.ui.main_window", "deskcare.ai.structured_transport")
    for module in modules:
        source = root.joinpath(*module.split(".")).with_suffix(".py")
        assert shape(pyz.extract(module)) == shape(compile(source.read_text(encoding="utf-8"), str(source), "exec")), module
    for name in ("QtCore", "QtPdf"):
        assert (package / "_internal" / "PySide6" / (name + ".pyd")).is_file()
    assert (package / "_internal" / "assets" / "lab_ocr.ps1").read_bytes() == (root / "assets" / "lab_ocr.ps1").read_bytes()
    print(f"Verified {len(modules)} UI13 modules, QtPdf and fixed OCR helper; no app launch.")


if __name__ == "__main__":
    main()
