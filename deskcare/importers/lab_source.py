"""Only a user-selected report page; offline Qt PDF and Windows OCR."""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory


class LabSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class LabSource:
    text: str
    page: int
    page_count: int
    preview: object = None
    method: str = "手动文字"


def _ocr_rows(words):
    if not isinstance(words, list) or len(words) > 5000:
        raise LabSourceError("本机识别结果无效，请手动核对文字。")
    groups = []
    for word in sorted(words, key=lambda item: (float(item["y"]), float(item["x"]))):
        center = float(word["y"]) + float(word["height"])/2
        group = next((item for item in groups if abs(item[0]-center) <= max(6, float(word["height"])*.55)), None)
        if group is None:
            groups.append([center, [word]])
        else:
            group[1].append(word)
    lines = []
    for _, group in sorted(groups):
        parts, previous_right = [], None
        for word in sorted(group, key=lambda item: float(item["x"])):
            if not isinstance(word["text"], str) or len(word["text"]) > 1000:
                raise LabSourceError("本机识别结果无效，请手动核对文字。")
            gap = float(word["x"]) - previous_right if previous_right is not None else 0
            parts.append(("\t" if gap > max(8, float(word["height"])*.6) else "") + word["text"])
            previous_right = float(word["x"]) + float(word["width"])
        lines.append("".join(parts))
    text = "\n".join(lines)
    if len(text) > 40000:
        raise LabSourceError("这一页识别内容过多，请裁剪后重试。")
    return text


def windows_ocr(path, *, runner=None):
    if os.name != "nt":
        raise LabSourceError("当前系统没有本机 Windows OCR，请粘贴或手动录入指标。")
    helper = Path(__file__).resolve().parents[2] / "assets" / "lab_ocr.ps1"
    executable = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
    try:
        response = (runner or subprocess.run)(
            [str(executable), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(helper)],
            input=json.dumps({"path": str(Path(path).resolve())}, ensure_ascii=False),
            encoding="utf-8", capture_output=True, timeout=35, check=False,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if response.returncode != 0 or len(response.stdout.encode("utf-8")) > 700000:
            raise ValueError
        data = json.loads(response.stdout.lstrip("\ufeff"))
        return _ocr_rows(data["words"])
    except Exception:
        raise LabSourceError("本机 OCR 不可用、图片过大或识别超时。可换清晰小图，或手动录入；未上传原件。") from None


def read_selected_lab_source(path, page=0, *, ocr=None):
    """Read at most one selected page; no scanning folders or model calls."""
    selected = Path(path)
    suffix = selected.suffix.lower()
    if suffix not in {".txt", ".csv", ".pdf", ".png", ".jpg", ".jpeg", ".bmp"}:
        raise LabSourceError("请选择 PDF、图片或 UTF-8 文字文件。")
    try:
        if not selected.is_file() or selected.stat().st_size > 8_000_000:
            raise LabSourceError("文件不可用或超过 8 MB，请换一个较小的文件。")
        if suffix in {".txt", ".csv"}:
            text = selected.read_bytes().decode("utf-8-sig")
            if len(text) > 40000:
                raise LabSourceError("文字超过 4 万字，请分次核对。")
            return LabSource(text, 0, 1)
        from PySide6.QtGui import QImageReader
        if suffix != ".pdf":
            reader = QImageReader(str(selected))
            reader.setAutoTransform(True)
            size = reader.size()
            if not size.isValid() or size.width()*size.height() > 20_000_000:
                raise LabSourceError("图片无效或超过 2000 万像素，请换清晰的小图。")
            image = reader.read()
            if image.isNull():
                raise LabSourceError("图片无法解码，请换一种格式。")
            try:
                text = (ocr or windows_ocr)(selected)
                method = "Windows 本机 OCR，必须核对原件"
            except LabSourceError:
                text, method = "", "本机 OCR 未完成；请对照图片手动录入"
            return LabSource(text, 0, 1, image, method)
        from PySide6.QtCore import QSize
        from PySide6.QtPdf import QPdfDocument
        document = QPdfDocument()
        try:
            error = document.load(str(selected))
            if error != QPdfDocument.Error.None_:
                raise LabSourceError("PDF 无法读取、已加密或需要密码；本工具不尝试破解。")
            count = document.pageCount()
            if not 1 <= count <= 10 or type(page) is not int or not 0 <= page < count:
                raise LabSourceError("一次支持最多 10 页的 PDF，请选择其中一页核对。")
            text = document.getAllText(page).text()
            size = document.pagePointSize(page)
            if size.width() <= 0 or size.height() <= 0:
                raise LabSourceError("PDF 页尺寸无效。")
            factor = min(1600/size.width(), 2200/size.height())
            image = document.render(page, QSize(max(1, round(size.width()*factor)), max(1, round(size.height()*factor))))
            method = "PDF 本机文字提取，必须核对列顺序"
            if not text.strip():
                # Only a derived rendering is temporary, never retained as report history.
                try:
                    with TemporaryDirectory(prefix="deskcare-lab-ocr-") as temporary:
                        raster = Path(temporary) / "page.png"
                        if not image.save(str(raster)):
                            raise LabSourceError("无法准备本机 OCR。")
                        text = (ocr or windows_ocr)(raster)
                    method = "扫描 PDF 本机 OCR，必须核对原件"
                except LabSourceError:
                    method = "扫描 PDF 本机 OCR 未完成；请对照预览手动录入"
            if len(text) > 40000:
                raise LabSourceError("这一页文字过多，请只录入本次需要的指标。")
            return LabSource(text, page, count, image, method)
        finally:
            document.close()
    except LabSourceError:
        raise
    except Exception:
        raise LabSourceError("文件没有读完，请换一个文件或手动录入；未上传原件。") from None
