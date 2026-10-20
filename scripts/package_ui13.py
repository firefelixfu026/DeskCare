"""Package only the selected runtime and fictional presentation assets."""
from pathlib import Path
import hashlib
import shutil
from zipfile import ZipFile, ZIP_DEFLATED

from scripts.package_submission import check_file

ROOT = Path(__file__).resolve().parents[1]


def put(archive, path, target):
    payload = path.read_bytes()
    check_file(target, payload)
    archive.writestr(target, payload)


def main():
    gallery = ROOT / "docs/images/ui13"
    gallery.mkdir(parents=True, exist_ok=True)
    sources = {"today": "ui13-gallery/today", "usage": "ui13-gallery/usage",
               "settings-reminders": "ui13-gallery/settings-reminders", "journal": "ui13-gallery/journal",
               "assistant": "ui13-assistant/assistant-confirm-action", "mascot": "ui13-gallery/mascot-comfortable",
               "lab-source": "ui13-preview/lab-source", "lab-verified": "ui13-preview/lab-verified",
               "lab-reading": "ui13-preview/lab-reading"}
    for name, source in sources.items():
        shutil.copyfile(ROOT / "build" / (source + ".png"), gallery / (name + ".png"))
    release = ROOT / "release/UI13"
    release.mkdir(parents=True, exist_ok=True)
    runtime = ROOT / "dist/DeskCare-UI13"
    with ZipFile(release / "DeskCare-UI13-Windows-x64.zip", "w", ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(runtime.rglob("*")):
            if path.is_file():
                put(archive, path, "DeskCare-UI13/" + path.relative_to(runtime).as_posix())
        put(archive, ROOT / "submission/UI13_Demo.cmd", "DeskCare-UI13/START-DEMO.cmd")
        put(archive, ROOT / "submission/UI13_README.md", "DeskCare-UI13/README.md")
        for name in ("fictional-cbc.pdf", "fictional-cbc.png"):
            put(archive, ROOT / "build/ui13-preview" / name, "DeskCare-UI13/examples/" + name)
    with ZipFile(release / "DeskCare-UI13-Demo-Screenshots.zip", "w", ZIP_DEFLATED) as archive:
        put(archive, ROOT / "docs/产品演示_UI13.md", "产品演示_UI13.md")
        for path in sorted(gallery.glob("*.png")):
            put(archive, path, "images/ui13/" + path.name)
    shutil.copyfile(ROOT / "output/pdf/DeskCare-Business-Plan-UI13.pdf", release / "DeskCare-Business-Plan-UI13.pdf")
    lines = []
    for name in ("DeskCare-UI13-Windows-x64.zip", "DeskCare-UI13-Demo-Screenshots.zip", "DeskCare-Business-Plan-UI13.pdf"):
        path = release / name
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        lines.append(digest + "  " + name)
        if path.suffix == ".zip":
            with ZipFile(path) as archive:
                assert archive.testzip() is None
                assert not any(part in {".git", ".venv", "__pycache__"} for entry in archive.namelist() for part in Path(entry).parts)
        print(f"{name}: {path.stat().st_size} bytes; SHA256 {digest}")
    (release / "SHA256SUMS.txt").write_text("\n".join(lines)+"\n", encoding="ascii")


if __name__ == "__main__":
    main()
