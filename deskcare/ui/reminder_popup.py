"""Small desktop reminder: no modal dialog, forced focus or private task text."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class ReminderPopup(QWidget):
    response_requested = Signal(str)

    def __init__(self):
        super().__init__(None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setObjectName("desktopReminder")
        self.setWindowTitle("DeskCare · 休息提醒")
        self.setFixedWidth(390)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.panel = QWidget()
        self.panel.setObjectName("reminderSurface")
        outer.addWidget(self.panel)
        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        header = QHBoxLayout()
        self.title = QLabel("休息一下？")
        self.title.setObjectName("popupTitle")
        header.addWidget(self.title)
        header.addStretch()
        self.close_button = QPushButton("×")
        self.close_button.setAccessibleName("关闭这条提醒")
        self.close_button.setFixedSize(28, 28)
        self.close_button.setObjectName("popupClose")
        self.close_button.clicked.connect(lambda: self._respond("SKIP"))
        header.addWidget(self.close_button)
        layout.addLayout(header)
        self.body = QLabel()
        self.body.setWordWrap(True)
        layout.addWidget(self.body)
        self.tip = QLabel()
        self.tip.setWordWrap(True)
        layout.addWidget(self.tip)
        row = QHBoxLayout()
        self.buttons = {}
        for code, text in (("BREAK_NOW", "现在休息"), ("SNOOZE_10_MIN", "10 分钟后"), ("SKIP", "跳过")):
            button = QPushButton(text)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.clicked.connect(lambda _checked=False, value=code: self._respond(value))
            self.buttons[code] = button
            row.addWidget(button)
        layout.addLayout(row)
        self.preview = True
        self.setStyleSheet("""
            #reminderSurface { background:#F9FCFA; border:1px solid #C9DED4; border-radius:18px; }
            QLabel { background:transparent; border:none; color:#354E48; font-family:'Microsoft YaHei UI'; font-size:14px; }
            #popupTitle { font-size:20px; font-weight:600; color:#285C4E; }
            QPushButton { background:#E7F0EB; color:#285C4E; border:none; border-radius:9px; padding:10px 8px; }
            QPushButton:hover { background:#D5E7DC; }
            #popupClose { background:transparent; padding:0; font-size:20px; }
        """)

    def present(self, *, preview: bool = False, show_tip: bool = True) -> None:
        self.preview = preview
        self.title.setText("提醒效果预览" if preview else "休息一下？")
        self.body.setText("这只是预览，不会记录提醒或改变计时。" if preview
                          else "已经用了一会儿电脑。如果方便，可以给自己留个短暂空档。")
        self.tip.setText("可以起身走几步，或轻轻活动肩颈；以舒适为准，不舒服就停下。")
        self.tip.setVisible(show_tip)
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(area.right() - self.width() - 18, area.bottom() - self.height() - 18)
        # Deliberately no raise_(), activateWindow() or setFocus().
        self.show()

    def _respond(self, code: str) -> None:
        self.hide()
        if not self.preview:
            self.response_requested.emit(code)
