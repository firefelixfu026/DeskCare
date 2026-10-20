"""Read-only Markdown presentation without loading external resources."""

from PySide6.QtGui import (
    QColor, QFont, QTextBlockFormat, QTextCharFormat, QTextCursor,
    QTextDocument, QTextLength, QTextOption,
)
from PySide6.QtWidgets import QTextBrowser

from deskcare.ui.theme import REPORT_CSS


class ReportPreview(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setAccessibleName("已排版的本地报告")
        self.document().setDefaultFont(QFont("Microsoft YaHei UI", 11))
        option = self.document().defaultTextOption()
        option.setWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)
        self.document().setDefaultTextOption(option)
        self.document().setDefaultStyleSheet(REPORT_CSS)
        self.markdown = ""

    def loadResource(self, resource_type, name):
        # Model-generated Markdown must never read a local image/file or URL.
        return None

    def set_report(self, markdown):
        if markdown == self.markdown:
            return
        position = self.verticalScrollBar().value()
        self.markdown = markdown
        self.document().setMarkdown(
            markdown,
            QTextDocument.MarkdownFeature.MarkdownDialectGitHub
            | QTextDocument.MarkdownFeature.MarkdownNoHTML,
        )
        self._format_document()
        self.moveCursor(QTextCursor.MoveOperation.Start)
        self.verticalScrollBar().setValue(position)

    def _format_document(self):
        """QTextDocument Markdown does not apply all browser CSS spacing rules."""
        document = self.document()
        cursor = QTextCursor(document)
        cursor.select(QTextCursor.SelectionType.Document)
        body = QTextCharFormat()
        body.setFontFamilies(["Microsoft YaHei UI", "Segoe UI"])
        body.setFontPointSize(11)
        body.setForeground(QColor("#354E48"))
        cursor.mergeCharFormat(body)
        block = document.begin()
        tables = set()
        while block.isValid():
            cursor = QTextCursor(block)
            table = cursor.currentTable()
            if table is not None and table not in tables:
                tables.add(table)
                table_format = table.format()
                table_format.setCellPadding(9)
                table_format.setCellSpacing(0)
                table_format.setBorder(0.5)
                table_format.setBorderBrush(QColor("#E0E9E4"))
                table.setFormat(table_format)
            fmt = block.blockFormat()
            level = fmt.headingLevel()
            fmt.setLineHeight(155, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
            fmt.setTopMargin(0 if table else 3)
            fmt.setBottomMargin(0 if table else 15)
            if level:
                fmt.setTopMargin(4 if level == 1 else 26 if level == 2 else 16)
                fmt.setBottomMargin(13 if level <= 2 else 9)
                fmt.setLineHeight(130, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
                heading = QTextCharFormat()
                heading.setFontPointSize({1: 21, 2: 14, 3: 11.5}.get(level, 11))
                heading.setFontWeight(QFont.Weight.DemiBold)
                heading.setForeground(QColor("#285C4E"))
                cursor.select(QTextCursor.SelectionType.BlockUnderCursor)
                cursor.mergeCharFormat(heading)
            elif block.textList() is not None:
                fmt.setBottomMargin(8)
            cursor.setBlockFormat(fmt)
            block = block.next()
        self._set_reading_margins()

    def _set_reading_margins(self):
        # Center a comfortable reading column instead of stretching text across
        # the full window. These are logical pixels, so DPI scaling stays native.
        frame = self.document().rootFrame()
        fmt = frame.frameFormat()
        margin = max(24.0, (self.viewport().width() - 850) / 2)
        fmt.setLeftMargin(margin)
        fmt.setRightMargin(margin)
        fmt.setTopMargin(24)
        fmt.setBottomMargin(32)
        frame.setFrameFormat(fmt)
        block = self.document().begin()
        tables = set()
        while block.isValid():
            cursor = QTextCursor(block)
            table = cursor.currentTable()
            if table is not None and table not in tables:
                tables.add(table)
                table_format = table.format()
                table_format.setWidth(QTextLength(QTextLength.Type.FixedLength,
                                                 max(120, self.viewport().width() - 2 * margin - 16)))
                table.setFormat(table_format)
            block = block.next()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._set_reading_margins()
