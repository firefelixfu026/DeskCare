"""Small explicit page navigation shared by tasks and usage rankings."""

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class Pagination(QWidget):
    changed = Signal(int)

    def __init__(self):
        super().__init__()
        self.index = 0
        self.pages = 1
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.previous = QPushButton("上一页")
        self.previous.setObjectName("secondaryButton")
        self.next = QPushButton("下一页")
        self.next.setObjectName("secondaryButton")
        self.summary = QLabel()
        row.addStretch()
        row.addWidget(self.previous)
        row.addWidget(self.summary)
        row.addWidget(self.next)
        self.previous.clicked.connect(lambda: self.go(self.index - 1))
        self.next.clicked.connect(lambda: self.go(self.index + 1))

    def update_total(self, total, page_size):
        self.pages = max(1, (total + page_size - 1) // page_size)
        self.index = min(self.index, self.pages - 1)
        self.summary.setText(f"{self.index + 1} / {self.pages} 页 · 共 {total} 项")
        self.previous.setEnabled(self.index > 0)
        self.next.setEnabled(self.index + 1 < self.pages)

    def go(self, index):
        self.index = max(0, min(index, self.pages - 1))
        self.changed.emit(self.index)
