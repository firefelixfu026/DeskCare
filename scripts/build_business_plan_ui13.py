"""Render the product-facing business plan with bundled reportlab."""
from pathlib import Path
import re
from html import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

ROOT = Path(__file__).resolve().parents[1]


def main():
    pdfmetrics.registerFont(TTFont("YaHei", "C:/Windows/Fonts/msyh.ttc", subfontIndex=0))
    pdfmetrics.registerFont(TTFont("YaHeiBold", "C:/Windows/Fonts/msyhbd.ttc", subfontIndex=0))
    output = ROOT / "output/pdf"
    output.mkdir(parents=True, exist_ok=True)
    document = SimpleDocTemplate(str(output / "DeskCare-Business-Plan-UI13.pdf"), pagesize=A4,
                                 rightMargin=49, leftMargin=49, topMargin=43, bottomMargin=43,
                                 title="DeskCare 商业计划书", author="DeskCare", subject="轻量化个人 AI 健康小助手")
    body = ParagraphStyle("body", fontName="YaHei", fontSize=10.5, leading=17, textColor=colors.HexColor("#263D3A"),
                          spaceAfter=10, wordWrap="CJK", splitLongWords=True)
    styles = {
        1: ParagraphStyle("title", parent=body, fontName="YaHeiBold", fontSize=27, leading=36, spaceAfter=16, textColor=colors.black),
        2: ParagraphStyle("heading", parent=body, fontName="YaHeiBold", fontSize=16, leading=24, spaceBefore=9, spaceAfter=10, textColor=colors.black, keepWithNext=True),
        3: ParagraphStyle("subheading", parent=body, fontName="YaHeiBold", fontSize=12, leading=20, spaceBefore=5, spaceAfter=7, textColor=colors.black, keepWithNext=True),
    }
    cell = ParagraphStyle("cell", parent=body, fontSize=9, leading=14, spaceAfter=0)
    header = ParagraphStyle("tableheader", parent=cell, fontName="YaHeiBold", textColor=colors.white)
    story, paragraph, table_rows = [], [], []

    def text(value, style=body):
        value = escape(value)
        value = re.sub(r"https://[^\s<]+", lambda match: '<link href="' + match[0] + '">' + match[0] + '</link>', value)
        return Paragraph(value, style)

    def flush_paragraph():
        if paragraph:
            story.append(text(" ".join(paragraph)))
            paragraph.clear()

    def flush_table():
        if not table_rows:
            return
        count = len(table_rows[0])
        available = A4[0]-98
        proportions = {2: [.31, .69], 3: [.20, .37, .43], 6: [.12, .14, .12, .14, .21, .27]}[count]
        rows = [[text(value, header if i == 0 else cell) for value in row] for i, row in enumerate(table_rows)]
        table = Table(rows, colWidths=[available*p for p in proportions], repeatRows=1, hAlign="LEFT")
        commands = [("BACKGROUND", (0,0), (-1,0), colors.HexColor("#285A50")),
                    ("GRID", (0,0), (-1,-1), .4, colors.HexColor("#D9E2DE")),
                    ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
                    ("LEFTPADDING", (0,0), (-1,-1), 8), ("RIGHTPADDING", (0,0), (-1,-1), 8),
                    ("TOPPADDING", (0,0), (-1,-1), 8), ("BOTTOMPADDING", (0,0), (-1,-1), 8)]
        for row in range(1, len(rows)):
            if row % 2 == 0:
                commands.append(("BACKGROUND", (0,row), (-1,row), colors.HexColor("#F2F6F4")))
        table.setStyle(TableStyle(commands))
        story.extend((table, Spacer(1, 12)))
        table_rows.clear()

    for line in (ROOT / "docs/DeskCare_商业计划书_UI13.md").read_text(encoding="utf-8").splitlines()+[""]:
        if line.startswith("|"):
            flush_paragraph()
            values = [value.strip() for value in line.strip("|").split("|")]
            if not all(re.fullmatch(r"[-: ]+", value) for value in values):
                table_rows.append(values)
            continue
        flush_table()
        if not line.strip():
            flush_paragraph()
        elif line == "<!-- pagebreak -->":
            flush_paragraph()
            story.append(PageBreak())
        elif line.startswith("#"):
            flush_paragraph()
            level = len(line)-len(line.lstrip("#"))
            story.append(text(line.lstrip("# "), styles[level]))
        else:
            paragraph.append(line)

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("YaHei", 8)
        canvas.setFillColor(colors.HexColor("#6D817B"))
        canvas.drawString(49, 24, "DeskCare   个人 AI 健康小助手")
        canvas.drawRightString(A4[0]-49, 24, str(doc.page))
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    print(output / "DeskCare-Business-Plan-UI13.pdf")


if __name__ == "__main__":
    main()
