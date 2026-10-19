"""Build the two dated, editable report sources into readable CJK PDFs.

Use the Codex bundled Python with reportlab. Output is deterministic in content;
page images for QA are produced separately with the bundled Poppler renderer.
"""

import re
from html import escape
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, PageBreak, Table, TableStyle,
)

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "output" / "pdf"
WIDTH = letter[0] - 104


def inline(text):
    pattern = r"\[([^\]]+)\]\((https?://[^\s)]+)\)"
    parts = []
    cursor = 0
    for match in re.finditer(pattern, text):
        parts.append(escape(text[cursor:match.start()]))
        parts.append(f'<link href="{escape(match[2], quote=True)}" color="#285F55">{escape(match[1])}</link>')
        cursor = match.end()
    parts.append(escape(text[cursor:]))
    return "".join(parts)


def build(source):
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    pdfmetrics.registerFont(TTFont("DeskCareCJK", str(font_path), subfontIndex=0))
    styles = {
        "title": ParagraphStyle("title", fontName="DeskCareCJK", fontSize=25, leading=34, spaceAfter=14, textColor=colors.black),
        "meta": ParagraphStyle("meta", fontName="DeskCareCJK", fontSize=10, leading=16, textColor=colors.HexColor("#647572"), spaceAfter=16),
        "h1": ParagraphStyle("h1", fontName="DeskCareCJK", fontSize=17, leading=25, spaceBefore=7, spaceAfter=14, keepWithNext=True, textColor=colors.black),
        "h2": ParagraphStyle("h2", fontName="DeskCareCJK", fontSize=12.5, leading=20, spaceBefore=11, spaceAfter=7, keepWithNext=True, textColor=colors.black),
        "body": ParagraphStyle("body", fontName="DeskCareCJK", fontSize=11, leading=18.5, spaceAfter=10, wordWrap="CJK", alignment=TA_LEFT, textColor=colors.HexColor("#25322F")),
        "cell": ParagraphStyle("cell", fontName="DeskCareCJK", fontSize=9.5, leading=15, wordWrap="CJK", textColor=colors.HexColor("#25322F")),
        "head": ParagraphStyle("head", fontName="DeskCareCJK", fontSize=9.5, leading=15, wordWrap="CJK", textColor=colors.black),
    }
    lines = source.read_text(encoding="utf-8").splitlines()
    story = []
    section_count = 0
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        i += 1
        if not line:
            continue
        if line.startswith("# "):
            story.append(Paragraph(inline(line[2:]), styles["title"]))
        elif line.startswith("## "):
            if section_count:
                story.append(PageBreak())
            story.append(Paragraph(inline(line[3:]), styles["h1"]))
            section_count += 1
        elif line.startswith("### "):
            story.append(Paragraph(inline(line[4:]), styles["h2"]))
        elif line.startswith("|"):
            raw_rows = [line]
            while i < len(lines) and lines[i].strip().startswith("|"):
                raw_rows.append(lines[i].strip())
                i += 1
            rows = [[cell.strip() for cell in row.strip("|").split("|")]
                    for row in raw_rows if not re.fullmatch(r"[|\s:\-]+", row)]
            count = len(rows[0])
            fractions = {3: (0.25, 0.32, 0.43), 6: (0.07, 0.17, 0.16, 0.15, 0.20, 0.25)}.get(count)
            if rows[0][0] == "优先级":
                fractions = (0.10, 0.35, 0.55)
            elif rows[0][0] == "用途":
                fractions = (0.31, 0.22, 0.47)
            widths = [WIDTH * f for f in fractions] if fractions else [WIDTH / count] * count
            cells = [[Paragraph(inline(cell), styles["head" if index == 0 else "cell"])
                      for cell in row] for index, row in enumerate(rows)]
            table = Table(cells, colWidths=widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E9F0ED")),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#D9D9D9")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]))
            story.extend([table, Spacer(1, 13)])
        else:
            style = "meta" if not section_count and "2026年10月20日 |" in line else "body"
            story.append(Paragraph(inline(line), styles[style]))

    path = OUTPUT / f"{source.stem}.pdf"
    title = lines[0].removeprefix("# ")
    document = SimpleDocTemplate(str(path), pagesize=letter, rightMargin=52,
                                 leftMargin=52, topMargin=44, bottomMargin=48,
                                 title=title, author="DeskCare", subject="2026年10月20日项目交付")

    def footer(canvas, doc):
        canvas.saveState()
        canvas.setFont("DeskCareCJK", 8)
        canvas.setFillColor(colors.HexColor("#77867F"))
        canvas.drawString(52, 25, "DeskCare  |  2026年10月20日")
        canvas.drawRightString(letter[0] - 52, 25, str(doc.page))
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    print(path)


def main():
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for filename in ("DeskCare_项目阶段报告_2026-10-20.md", "DeskCare_商业计划书_2026-10-20.md"):
        build(ROOT / "docs" / filename)


if __name__ == "__main__":
    main()
