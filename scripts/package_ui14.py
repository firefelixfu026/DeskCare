"""Build only the current runtime ZIP, keep independent historical archives."""
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED
import hashlib

from scripts.package_submission import check_file

ROOT=Path(__file__).resolve().parents[1]


def main(version="UI14", document="UI14_任务优化说明.md", image_folder="ui14"):
    output=ROOT/"release"/version
    output.mkdir(parents=True,exist_ok=True)
    runtime=ROOT/"dist"/f"DeskCare-{version}"
    selected=output/f"DeskCare-{version}-Windows-x64.zip"
    with ZipFile(selected,"w",ZIP_DEFLATED,compresslevel=6) as archive:
        for path in sorted(runtime.rglob("*")):
            if path.is_file():
                name=f"DeskCare-{version}/"+path.relative_to(runtime).as_posix()
                data=path.read_bytes()
                check_file(name,data)
                archive.writestr(name,data)
        archive.writestr(f"DeskCare-{version}/START-DEMO.cmd",f'@echo off\r\nstart "" "%~dp0DeskCare-{version}.exe" --demo-scenario\r\n')
        archive.writestr(f"DeskCare-{version}/README.md",(ROOT/"docs"/document).read_bytes())
        for image in sorted((ROOT/"docs/images"/image_folder).glob("*.png")):
            archive.writestr(f"DeskCare-{version}/images/{image_folder}/"+image.name,image.read_bytes())
    with ZipFile(selected) as archive:
        assert archive.testzip() is None
    sha=hashlib.sha256(selected.read_bytes()).hexdigest()
    (output/"SHA256SUMS.txt").write_text(sha+"  "+selected.name+"\n",encoding="ascii")
    print(f"{selected.name}: {selected.stat().st_size} bytes; SHA256 {sha}")


if __name__ == "__main__": main()
