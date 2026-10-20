"""Fictional CBC fixtures, real offline extraction/OCR, no personal report or AI."""
import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
import os
import gc

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase, QImage, QPainter, QPdfWriter, QPageSize
from PySide6.QtWidgets import QApplication

from deskcare.domain.lab_reading import LabRow, parse_lab_text
from deskcare.importers.lab_source import read_selected_lab_source, windows_ocr
from deskcare.services.lab_reading_service import LabReadingService
from deskcare.storage.database import UsageRepository
from deskcare.ui.lab_reading import LabReadingDialog
from deskcare.ui.theme import apply_theme


LINES = ["WBC   10.2   10^9/L   3.5-9.5", "RBC   4.50   10^12/L   3.8-5.1",
         "HGB   130   g/L   120-170", "HCT   0.41   L/L   0.35-0.45",
         "MCV   90   fL   82-100", "PLT   230   10^9/L   125-350"]


def paint_fixture(painter):
    painter.fillRect(0, 0, 1000, 1400, Qt.GlobalColor.white)
    painter.setPen(Qt.GlobalColor.black)
    painter.setFont(QFont("Microsoft YaHei UI", 18))
    painter.drawText(45, 65, "虚构血常规示例 · 仅用于软件测试")
    painter.setFont(QFont("Microsoft YaHei UI", 13))
    painter.drawText(45, 110, "以下数值及范围均为测试数据，不是健康参考标准。")
    painter.drawText(45, 150, "项目      结果      单位      报告参考范围")
    painter.setFont(QFont("Consolas", 18))
    for i, line in enumerate(LINES):
        painter.drawText(45, 210+i*65, line)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/msyh.ttc")
    QFontDatabase.addApplicationFont("C:/Windows/Fonts/consola.ttf")
    apply_theme(app)
    image = QImage(1000, 1400, QImage.Format.Format_RGB32)
    painter = QPainter(image)
    paint_fixture(painter)
    painter.end()
    image.save(str(args.output / "fictional-cbc.png"))
    pdf = QPdfWriter(str(args.output / "fictional-cbc.pdf"))
    pdf.setResolution(120)
    pdf.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    painter = QPainter(pdf)
    paint_fixture(painter)
    painter.end()
    del pdf
    source = read_selected_lab_source(args.output / "fictional-cbc.pdf")
    assert source.page_count == 1 and "WBC" in source.text
    assert source.preview.save(str(args.output / "pdf-render.png"))
    rows, missed = parse_lab_text(source.text)
    assert len(rows) == 6, f"PDF extraction parsed {len(rows)} rows; {missed} unmatched lines"
    ocr_text = windows_ocr(args.output / "fictional-cbc.png")
    assert "WBC" in ocr_text and "HGB" in ocr_text
    ocr_rows, ocr_missed = parse_lab_text(ocr_text)
    print(f"Real local Windows OCR: {len(ocr_rows)} unverified rows, {ocr_missed} unmatched numeric lines; original required.")
    with TemporaryDirectory(prefix="fictional-ui13-", dir=args.output.resolve()) as temporary:
        service = LabReadingService(UsageRepository(Path(temporary) / "fictional.sqlite3"))
        service.set_enabled(True)
        dialog = LabReadingDialog(service)
        dialog.show()
        dialog._source_done(source)
        app.processEvents()
        dialog.grab().save(str(args.output / "lab-source.png"))
        for row in rows:
            dialog.add_row(row)
        dialog.tabs.setCurrentIndex(1)
        app.processEvents()
        dialog.grab().save(str(args.output / "lab-unverified.png"))
        for i in range(dialog.table.rowCount()):
            dialog.table.item(i, 0).setCheckState(Qt.CheckState.Checked)
        dialog.show_reading()
        app.processEvents()
        dialog.grab().save(str(args.output / "lab-reading.png"))
        dialog.tabs.setCurrentIndex(1)
        app.processEvents()
        dialog.grab().save(str(args.output / "lab-verified.png"))
        dialog.reject()
        assert service.rows == () and dialog.raw.toPlainText() == "" and dialog.table.rowCount() == 0
        dialog.deleteLater()
        app.processEvents()
        gc.collect()
    print("Rendered PDF page and 4 UI13 screens. All data fictional. No AI request or personal database.")


if __name__ == "__main__":
    main()
