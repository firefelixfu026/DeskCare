"""Soft, keyboard-ready choices without a native square popup container."""
from PySide6.QtCore import QEvent, QEasingCurve, QPoint, QRectF, QSize, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFrame, QListView, QMenu, QSizePolicy,
    QStyle, QStyledItemDelegate, QToolButton, QVBoxLayout,
)
from shiboken6 import isValid


def paint_surface(widget):
    painter = QPainter(widget)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(widget.rect()).adjusted(7, 6, -7, -8)
    painter.setPen(Qt.PenStyle.NoPen)
    for spread in range(5, 0, -1):
        painter.setBrush(QColor(42, 74, 60, 4))
        painter.drawRoundedRect(rect.adjusted(-spread, -spread+2, spread, spread+2), 15+spread, 15+spread)
    painter.setBrush(QColor("#FFFFFF"))
    painter.setPen(QPen(QColor("#E1EBE5"), 1))
    painter.drawRoundedRect(rect, 15, 15)
    painter.end()


class RoundedMenu(QMenu):
    """QMenu semantics for existing status/actions, with a transparent shell."""
    STYLE = """
        QMenu { background: transparent; color: #405C52; border: none; padding: 12px; font-size: 13px; }
        QMenu::item { padding: 10px 17px 10px 10px; margin: 2px 0;
                      border: none; border-radius: 9px; background: transparent; }
        QMenu::item:selected { background: #E6F2EA; color: #285F4C; }
        QMenu::indicator { width: 14px; height: 14px; }
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(self.STYLE)

    def paintEvent(self, event):
        paint_surface(self)
        super().paintEvent(event)


class _ChoiceDelegate(QStyledItemDelegate):
    def __init__(self, owner, parent):
        super().__init__(parent)
        self.owner = owner

    def sizeHint(self, option, index):
        return QSize(120, 40)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(option.rect).adjusted(1, 2, -1, -2)
        current = index.row() == self.owner.currentIndex()
        enabled = bool(index.flags() & Qt.ItemFlag.ItemIsEnabled)
        hovered = bool(option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver))
        painter.setPen(Qt.PenStyle.NoPen)
        if current or hovered:
            painter.setBrush(QColor("#DDEEE4" if hovered and enabled else "#EDF5EF"))
            painter.drawRoundedRect(rect, 9, 9)
        painter.setFont(option.font)
        painter.setPen(QColor("#285F4C" if current and enabled else "#405C52" if enabled else "#A4B2AB"))
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        text = option.fontMetrics.elidedText(text, Qt.TextElideMode.ElideRight, int(rect.width()-48))
        painter.drawText(rect.adjusted(12, 0, -32, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        if current:
            x, y = rect.right()-18, rect.center().y()
            path = QPainterPath()
            path.moveTo(x-4, y)
            path.lineTo(x-1, y+3)
            path.lineTo(x+5, y-4)
            painter.setPen(QPen(QColor("#397B5E" if enabled else "#A4B2AB"), 1.8,
                                Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
            painter.drawPath(path)
        painter.restore()


class _ChoiceList(QListView):
    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.parentWidget().choose(self.currentIndex())
            event.accept()
        elif event.key() == Qt.Key.Key_Escape or (event.key() == Qt.Key.Key_Up and event.modifiers() & Qt.KeyboardModifier.AltModifier):
            self.parentWidget().hide()
            event.accept()
        else:
            super().keyPressEvent(event)


class _ChoicePopup(QFrame):
    def __init__(self, owner):
        super().__init__(owner, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        self.owner = owner
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setObjectName("softChoicePopup")
        self.setStyleSheet("QFrame#softChoicePopup { background: transparent; border: none; }")
        self.list = _ChoiceList(self)
        self.list.setObjectName("softChoiceList")
        self.list.setFrameShape(QFrame.Shape.NoFrame)
        self.list.setStyleSheet("QListView#softChoiceList { background: transparent; border: none; outline: none; padding: 0; }")
        self.list.setMouseTracking(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setVerticalScrollMode(QListView.ScrollMode.ScrollPerPixel)
        self.list.setItemDelegate(_ChoiceDelegate(owner, self.list))
        self.list.clicked.connect(self.choose)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 14)
        layout.addWidget(self.list)

    def paintEvent(self, event):
        paint_surface(self)

    def choose(self, index):
        if index.isValid() and index.flags() & Qt.ItemFlag.ItemIsEnabled:
            self.owner._choose(index.row())

    def hideEvent(self, event):
        if isValid(self.owner):
            self.owner.update()
        super().hideEvent(event)


class SoftComboBox(QComboBox):
    """Keep the model/data/signal contract while drawing both surfaces ourselves."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QComboBox { background: transparent; border: none; padding: 0; }")
        self.setMinimumHeight(40)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self._popup = _ChoicePopup(self)
        self._popup.list.setModel(self.model())
        self.model().modelReset.connect(self.hidePopup)
        self.model().rowsRemoved.connect(self.hidePopup)
        self.currentIndexChanged.connect(self.update)

    def sizeHint(self):
        width = max((self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count())), default=100)
        return QSize(min(420, max(136, width+46)), 40)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = QRectF(self.rect()).adjusted(.75, .75, -.75, -.75)
        painter.setBrush(QColor("#F7FAF8" if self.underMouse() else "#FFFFFF"))
        painter.setPen(QPen(QColor("#91B8A6" if self.hasFocus() or self._popup.isVisible() else "#D6E3DB"), 1))
        painter.drawRoundedRect(rect, 11, 11)
        painter.setPen(QColor("#35594B" if self.isEnabled() else "#9EAEA5"))
        text = self.fontMetrics().elidedText(self.currentText(), Qt.TextElideMode.ElideRight, max(0, self.width()-46))
        painter.drawText(rect.adjusted(13, 0, -30, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        x, y = rect.right()-17, rect.center().y()
        path = QPainterPath()
        dy = -1 if self._popup.isVisible() else 1
        path.moveTo(x-4, y-dy)
        path.lineTo(x, y+2*dy)
        path.lineTo(x+4, y-dy)
        painter.setPen(QPen(QColor("#729183"), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        painter.drawPath(path)

    def view(self):
        return self._popup.list

    def showPopup(self):
        if not self.isEnabled() or not self.count():
            return
        view = self.view()
        if view.model() is not self.model():
            view.setModel(self.model())
        view.setRootIndex(self.rootModelIndex())
        view.setModelColumn(self.modelColumn())
        view.setFont(self.font())
        view.setAccessibleName(self.accessibleName() or "选择选项")
        anchor = self.mapToGlobal(QPoint(0, 0))
        screen = QApplication.screenAt(anchor) or self.screen()
        area = screen.availableGeometry()
        text_width = max(self.fontMetrics().horizontalAdvance(self.itemText(i)) for i in range(self.count()))+68
        width = min(max(self.width()+12, min(text_width, 560)), area.width()-12)
        wanted = min(self.count(), max(1, min(self.maxVisibleItems(), 8)))*40+26
        below = area.bottom()-(anchor.y()+self.height())-5
        above = anchor.y()-area.top()-5
        down = wanted <= below or below >= above
        height = max(1, min(wanted, below if down else above, area.height()-12))
        x = max(area.left()+6, min(anchor.x()-6, area.right()-width-5))
        y = anchor.y()+self.height()+3 if down else anchor.y()-height-3
        y = max(area.top()+6, min(y, area.bottom()-height-5))
        self._popup.setGeometry(x, y, width, height)
        self._popup.show()
        index = self.model().index(self.currentIndex(), self.modelColumn(), self.rootModelIndex())
        view.setCurrentIndex(index)
        view.scrollTo(index, QListView.ScrollHint.PositionAtCenter)
        view.setFocus(Qt.FocusReason.PopupFocusReason)
        self.update()

    def hidePopup(self, *args):
        if hasattr(self, "_popup"):
            self._popup.hide()

    def _choose(self, index):
        text = self.itemText(index)
        self.hidePopup()
        self.setFocus(Qt.FocusReason.PopupFocusReason)
        self.setCurrentIndex(index)
        # Synchronous consumers may replace/delete the control.
        if isValid(self):
            self.activated.emit(index)
        if isValid(self):
            self.textActivated.emit(text)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.hidePopup() if self._popup.isVisible() else self.showPopup()
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        event.accept()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_F4,
                           Qt.Key.Key_Down, Qt.Key.Key_Up):
            self.showPopup()
            event.accept()
        elif event.key() == Qt.Key.Key_Escape:
            self.hidePopup()
            event.accept()
        else:
            super().keyPressEvent(event)

    def wheelEvent(self, event):
        event.ignore()

    def hideEvent(self, event):
        self.hidePopup()
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "_popup") and event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self.hidePopup()


class SegmentedChoice(QComboBox):
    """Visible button choices, preserving existing index/data and signal APIs."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("QComboBox { background: transparent; border: none; padding: 0; }")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        self.setMinimumHeight(44)
        self.buttons = []
        self._pill = QRectF()
        self.animation = QVariantAnimation(self)
        self.animation.setDuration(150)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.animation.valueChanged.connect(self._animate)
        self.model().rowsInserted.connect(self._rebuild)
        self.model().rowsRemoved.connect(self._rebuild)
        self.model().modelReset.connect(self._rebuild)
        self.model().dataChanged.connect(self._rebuild)
        self.currentIndexChanged.connect(self._sync)

    def sizeHint(self):
        return QSize(sum(max(62, self.fontMetrics().horizontalAdvance(self.itemText(i))+28) for i in range(self.count()))+12, 44)

    def minimumSizeHint(self):
        return self.sizeHint()

    def _rebuild(self, *args):
        for button in self.buttons:
            button.hide()
            button.deleteLater()
        self.buttons = []
        for index in range(self.count()):
            button = QToolButton(self)
            button.setText(self.itemText(index))
            button.setAccessibleName(self.itemText(index))
            button.setCheckable(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet("QToolButton { background: transparent; border: none; padding: 0 8px; color: #70867A; }"
                                "QToolButton:checked { color: #285F49; font-weight: 600; }"
                                "QToolButton:hover { color: #285F49; } QToolButton:disabled { color: #A6B5AC; }")
            button.clicked.connect(lambda checked=False, row=index: self._choose(row))
            self.buttons.append(button)
            button.show()
        self._layout_buttons()
        self._sync(self.currentIndex(), animate=False)
        self.updateGeometry()

    def _layout_buttons(self):
        if not self.buttons:
            return
        width = max(0, self.width()-12)/len(self.buttons)
        for i, button in enumerate(self.buttons):
            button.setGeometry(round(6+i*width), 5, round(width), max(0, self.height()-10))

    def _sync(self, index, *, animate=True):
        for row, button in enumerate(self.buttons):
            button.setChecked(row == index)
            button.setEnabled(self.isEnabled() and bool(self.model().flags(self.model().index(row, self.modelColumn())) & Qt.ItemFlag.ItemIsEnabled))
        target = QRectF(self.buttons[index].geometry()) if 0 <= index < len(self.buttons) else QRectF()
        self.animation.stop()
        if animate and self.isVisible() and not self._pill.isEmpty() and not target.isEmpty():
            self.animation.setStartValue(self._pill)
            self.animation.setEndValue(target)
            self.animation.start()
        else:
            self._pill = target
            self.update()

    def _animate(self, value):
        self._pill = value
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#E8EFEB"))
        painter.drawRoundedRect(QRectF(self.rect()).adjusted(.5, .5, -.5, -.5), 14, 14)
        if not self._pill.isEmpty():
            painter.setBrush(QColor("#FFFFFF" if self.isEnabled() else "#F2F5F3"))
            painter.setPen(QPen(QColor("#DFE9E2"), .8))
            painter.drawRoundedRect(self._pill, 10, 10)
        if self.hasFocus():
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setPen(QPen(QColor("#8FB5A1"), 1))
            painter.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 13, 13)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_buttons()
        self._sync(self.currentIndex(), animate=False)

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "buttons") and event.type() in (QEvent.Type.EnabledChange, QEvent.Type.FontChange):
            self._sync(self.currentIndex(), animate=False)
            self.updateGeometry()

    def _choose(self, index):
        if 0 <= index < len(self.buttons) and self.buttons[index].isEnabled():
            self.setFocus(Qt.FocusReason.MouseFocusReason)
            self.setCurrentIndex(index)
            if isValid(self):
                self._sync(index)
                self.activated.emit(index)

    def setCurrentIndex(self, index):
        super().setCurrentIndex(index)
        # Page/assistant sync blocks public signals to avoid a write-back loop.
        # Visual state must still follow the authoritative value.
        if hasattr(self, "buttons") and self.signalsBlocked():
            self._sync(self.currentIndex())

    def showPopup(self):
        pass

    def mousePressEvent(self, event):
        event.accept()

    def keyPressEvent(self, event):
        key = event.key()
        step = 1 if key in (Qt.Key.Key_Right, Qt.Key.Key_Down) else -1 if key in (Qt.Key.Key_Left, Qt.Key.Key_Up) else 0
        if step:
            index = self.currentIndex()+step
            while 0 <= index < self.count():
                if self.buttons[index].isEnabled():
                    self._choose(index)
                    break
                index += step
            event.accept()
        elif key in (Qt.Key.Key_Home, Qt.Key.Key_End):
            self._choose(0 if key == Qt.Key.Key_Home else self.count()-1)
            event.accept()
        else:
            event.accept()

    def wheelEvent(self, event):
        event.ignore()
