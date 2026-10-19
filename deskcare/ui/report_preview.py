"""Read-only Markdown presentation without loading external resources."""

from PySide6.QtGui import QTextCursor, QTextDocument
from PySide6.QtWidgets import QTextBrowser

from deskcare.ui.theme import REPORT_CSS


class ReportPreview(QTextBrowser):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setOpenLinks(False)
        self.setOpenExternalLinks(False)
        self.setAccessibleName("已排版的本地报告")
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
        self.moveCursor(QTextCursor.MoveOperation.Start)
        self.verticalScrollBar().setValue(position)
