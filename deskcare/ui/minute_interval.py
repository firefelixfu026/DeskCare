"""Plain, validated minute input; avoids the styled NoButtons spinbox layout."""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QLineEdit


class MinuteIntervalEdit(QLineEdit):
    valueChanged = Signal(int)

    def __init__(self, minutes=40, parent=None):
        super().__init__(parent)
        self._value = 40
        self.setValidator(QIntValidator(1, 180, self))
        self.setAccessibleName("休息提醒间隔，单位分钟，1 至 180")
        self.setToolTip("输入 1–180 的整数分钟，回车或离开输入框保存；空白或无效输入恢复原值。")
        self.setValue(minutes)

    def value(self):
        return self._value

    def setValue(self, minutes):
        if type(minutes) is not int or not 1 <= minutes <= 180:
            raise ValueError("提醒间隔应为 1–180 分钟。")
        changed = minutes != self._value
        self._value = minutes
        self.setText(str(minutes))
        if changed:
            self.valueChanged.emit(minutes)

    def _commit(self):
        try:
            minutes = int(self.text().strip())
            if not 1 <= minutes <= 180:
                raise ValueError
        except ValueError:
            self.setText(str(self._value))
            return
        self.setValue(minutes)

    def focusOutEvent(self, event):
        self._commit()
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._commit()
        super().keyPressEvent(event)
