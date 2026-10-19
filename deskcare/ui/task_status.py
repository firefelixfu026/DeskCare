"""Small task-status badges with a consistently sized, keyboard-ready menu."""

from PySide6.QtCore import QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QComboBox, QMenu


class TaskStatusCombo(QComboBox):
    """Keep the combo's model/signals, without its native popup container.

    The stock combo popup calculates its height from a styled table cell,
    producing clipped rows and scroll arrows on Windows. A real QMenu sizes
    each action independently and provides Escape, arrows and Enter handling.
    """

    MENU_STYLE = """
        QMenu { background: #FFFFFF; color: #405C52;
                border: 1px solid #DCE7E1; border-radius: 10px;
                padding: 6px; font-size: 13px; }
        QMenu::item { padding: 9px 16px 9px 10px; margin: 1px 0;
                      border: none; border-radius: 6px; }
        QMenu::item:selected { background: #EAF3ED; color: #2D6955; }
        QMenu::indicator { width: 14px; height: 14px; }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("taskStatus")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.menu = QMenu(self)
        self.menu.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self.menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.menu.setStyleSheet(self.MENU_STYLE)
        self.menu.setMinimumWidth(152)
        self.menu.aboutToHide.connect(self.update)
        self.currentIndexChanged.connect(self.update)

    def badge_rect(self):
        return QRectF(10, (self.height() - 30) / 2, self.width() - 20, 30)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        value = self.currentData()
        tone = getattr(value, "value", value)
        background, foreground = {
            "todo": ("#F2F5F3", "#687F74"),
            "doing": ("#FFF4DF", "#9C752F"),
            "done": ("#E6F3EC", "#38775F"),
        }.get(tone, ("#F2F5F3", "#687F74"))
        rect = self.badge_rect()
        painter.setBrush(QColor(background))
        painter.setPen(QPen(QColor("#A0BCAF"), 1) if self.hasFocus() else Qt.PenStyle.NoPen)
        painter.drawRoundedRect(rect, 7, 7)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(foreground))
        painter.drawEllipse(QPoint(int(rect.left() + 12), int(rect.center().y())), 2, 2)
        painter.setPen(QColor(foreground))
        painter.setFont(self.font())
        painter.drawText(rect.adjusted(22, 0, -21, 0), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self.currentText())
        x, y = rect.right() - 12, rect.center().y()
        painter.setPen(QPen(QColor(foreground), 1.4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawLine(QPoint(int(x - 3), int(y - 1)), QPoint(int(x), int(y + 2)))
        painter.drawLine(QPoint(int(x), int(y + 2)), QPoint(int(x + 3), int(y - 1)))

    def showPopup(self):
        if not self.isEnabled() or not self.count():
            return
        self.menu.clear()
        for index in range(self.count()):
            action = self.menu.addAction(self.itemText(index))
            action.setCheckable(True)
            action.setChecked(index == self.currentIndex())
            action.triggered.connect(lambda _checked=False, value=index: self._choose(value))
        self.menu.popup(self.mapToGlobal(QPoint(10, int(self.badge_rect().bottom()) + 5)))
        self.menu.setActiveAction(self.menu.actions()[self.currentIndex()])

    def hidePopup(self):
        self.menu.hide()

    def _choose(self, index):
        # Persisting emits a synchronous refresh which can replace this widget.
        # Close the popup before the callback and never access it afterwards.
        self.menu.hide()
        self.setCurrentIndex(index)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F4) or (
            event.key() == Qt.Key.Key_Down and event.modifiers() & Qt.KeyboardModifier.AltModifier
        ):
            self.showPopup()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.hidePopup()
            event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        # Scrolling the task list must not silently modify a task's status.
        event.ignore()
