"""Small, optional desktop companion for quick, user-confirmed task updates."""

from __future__ import annotations

from datetime import date

from PySide6.QtCore import QEvent, QRect, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QCursor,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QRegion,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from deskcare.domain.types import TaskStatus, WellnessLevel, WELLNESS_LEVEL_LABELS
from deskcare.ui.mascot import MascotSurface
from deskcare.ui.theme import STYLE, apply_theme


class SproutMascot(QWidget):
    """A small code-drawn DeskCare sprout; no external image asset is required."""

    clicked = Signal()

    def __init__(self, *, interactive: bool = False, parent=None):
        super().__init__(parent)
        self.interactive = interactive
        self.setFixedSize(38, 38)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        if interactive:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.setToolTip("点我展开 DeskCare")
            self.setAccessibleName("展开 DeskCare 桌面伙伴")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = min(self.width(), self.height()) / 64.0
        painter.translate((self.width() - 64 * scale) / 2, (self.height() - 64 * scale) / 2)
        painter.scale(scale, scale)

        if self.interactive:
            badge = QRadialGradient(26, 20, 48, 25, 19)
            badge.setColorAt(0, QColor("#F3FFF8"))
            badge.setColorAt(0.72, QColor("#D5F0E2"))
            badge.setColorAt(1, QColor("#B7DDC9"))
            painter.setPen(QPen(QColor("#367A6C"), 1.8))
            painter.setBrush(badge)
            painter.drawEllipse(3, 3, 58, 58)

        body = QPainterPath()
        body.moveTo(32, 19)
        body.cubicTo(17, 19, 10, 30, 11, 42)
        body.cubicTo(12, 55, 22, 60, 32, 60)
        body.cubicTo(43, 60, 53, 54, 53, 41)
        body.cubicTo(53, 29, 46, 19, 32, 19)
        body.closeSubpath()
        painter.setPen(QPen(QColor("#367A6C"), 2.2))
        painter.setBrush(QColor("#C9EBDD"))
        painter.drawPath(body)

        painter.save()
        painter.translate(31, 17)
        painter.rotate(-22)
        painter.setPen(QPen(QColor("#367A6C"), 1.8))
        painter.setBrush(QColor("#7CBF8D"))
        painter.drawEllipse(0, -13, 18, 10)
        painter.restore()
        painter.setPen(QPen(QColor("#367A6C"), 1.8))
        painter.drawLine(31, 18, 35, 9)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#315B51"))
        painter.drawEllipse(23, 37, 3.5, 4.5)
        painter.drawEllipse(38, 37, 3.5, 4.5)
        painter.setBrush(QColor("#E9A7A0"))
        painter.drawEllipse(16, 42, 6, 3.5)
        painter.drawEllipse(42, 42, 6, 3.5)
        painter.setPen(QPen(QColor("#567C6F"), 1.7))
        painter.drawArc(QRect(27, 40, 10, 8), 205 * 16, 130 * 16)

    def mouseReleaseEvent(self, event):
        if self.interactive and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CompanionWindow(QWidget):
    """Frameless, draggable top-level helper; hidden unless explicitly enabled."""

    hide_requested = Signal()
    open_main_requested = Signal()
    presentation_changed = Signal(str)

    def __init__(self, task_service=None, reminder_coordinator=None, repository=None, parent=None,
                 *, bodylog_service=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.task_service = task_service
        self.reminder_coordinator = reminder_coordinator
        self.repository = repository
        self.bodylog_service = bodylog_service
        self.presentation = "panel"
        self._mascot_panel_open = False
        self._mascot_state = "skip"
        self._mascot_press = None
        self._mascot_dragged = False
        self._state_day = date.today()
        self._drag_offset = None
        self._peek_side: str | None = None
        self._expanded_size = None
        self.setObjectName("deskcareCompanion")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("DeskCare 桌面伙伴")
        self.setFixedWidth(300)
        apply_theme(QApplication.instance())
        self.setStyleSheet(STYLE + """
            QWidget#deskcareCompanion { background: transparent; }
            QWidget#companionContent { background: #FFFFFF; border: 1px solid #D8E4DE; border-radius: 18px; }
        """)
        if self.repository is not None:
            self.repository.delete_setting("voice_model_path")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.content = QWidget(self)
        self.content.setObjectName("companionContent")
        self.content.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.content.customContextMenuRequested.connect(
            lambda position: self._mascot_menu(self.content.mapToGlobal(position))
        )
        root = QVBoxLayout(self.content)
        root.setContentsMargins(14, 12, 14, 14)
        title_row = QHBoxLayout()
        title_row.addWidget(SproutMascot(parent=self))
        title = QLabel("DeskCare")
        title.setObjectName("companionDragHandle")
        title.setCursor(Qt.CursorShape.SizeAllCursor)
        title.setToolTip("拖动这里移动；右键切换伙伴样式")
        title.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        title.customContextMenuRequested.connect(
            lambda position: self._mascot_menu(title.mapToGlobal(position))
        )
        title.installEventFilter(self)
        title.setStyleSheet("font-size:15px;font-weight:700")
        title_row.addWidget(title)
        title_row.addStretch()
        self.back_to_mascot = QPushButton("返回")
        self.back_to_mascot.setObjectName("secondaryButton")
        self.back_to_mascot.clicked.connect(self._show_mascot)
        self.back_to_mascot.hide()
        title_row.addWidget(self.back_to_mascot)
        hide_button = QPushButton("隐藏")
        hide_button.setFixedWidth(58)
        hide_button.clicked.connect(self._hide_companion)
        title_row.addWidget(hide_button)
        root.addLayout(title_row)

        from deskcare.ui.choices import SoftComboBox
        self.mode = SoftComboBox()
        self.mode.setObjectName("companionContextSelector")
        self.mode.setMaxVisibleItems(5)
        self.mode.setMinimumHeight(40)
        for value, text in (("normal", "普通工作"), ("focus", "专注模式"), ("meeting", "会议中"), ("reading", "阅读中"), ("quiet", "安静时段")):
            self.mode.addItem(text, value)
        self.mode.currentIndexChanged.connect(self._set_mode)
        root.addWidget(QLabel("当前情境"))
        root.addWidget(self.mode)
        root.addWidget(QLabel("今日任务"))
        self.task_list = QVBoxLayout()
        self.task_list.setSpacing(4)
        root.addLayout(self.task_list)
        open_main = QPushButton("全部任务")
        open_main.setObjectName("secondaryButton")
        open_main.clicked.connect(self.open_main_requested.emit)
        root.addWidget(open_main)
        add_row = QHBoxLayout()
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("添加任务…")
        self.task_input.returnPressed.connect(self._add_task)
        add_row.addWidget(self.task_input, 1)
        self.add_task_button = QPushButton("添加")
        self.add_task_button.clicked.connect(self._add_task)
        add_row.addWidget(self.add_task_button)
        root.addLayout(add_row)
        outer.addWidget(self.content)
        self.peek_button = SproutMascot(interactive=True, parent=self)
        self.peek_button.setFixedSize(88, 88)
        self.peek_button.clicked.connect(self._expand_from_edge)
        self.peek_button.hide()
        outer.addWidget(self.peek_button)
        self.mascot = MascotSurface(self)
        self.mascot.installEventFilter(self)
        self.mascot.silhouette_changed.connect(self._sync_mascot_mask)
        self.mascot.hide()
        outer.addWidget(self.mascot)
        if self.task_service is not None:
            self.task_service.subscribe(self.refresh_tasks)
        if self.reminder_coordinator is not None and hasattr(self.reminder_coordinator, "subscribe"):
            self.reminder_coordinator.subscribe(self._sync_reminder_mode)
        self.refresh_tasks()
        self.adjustSize()
        saved_style = self.repository.get_setting("companion_style", "panel") if self.repository else "panel"
        self.set_presentation(saved_style if saved_style in {"panel", "mascot"} else "panel", persist=False)
        if self.bodylog_service is not None:
            self.bodylog_service.subscribe(self._sync_wellness)
        else:
            self._sync_wellness(False)
        self._day_timer = QTimer(self)
        self._day_timer.setInterval(60_000)
        self._day_timer.timeout.connect(self._check_day)
        self._day_timer.start()
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(
                max(area.left(), area.right() - self.width() - 20),
                max(area.top(), area.bottom() - self.height() - 20),
            )

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._begin_drag(event.globalPosition().toPoint())
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._move_drag(event.globalPosition().toPoint())
            event.accept()

    def mouseReleaseEvent(self, event):
        self._finish_drag()
        super().mouseReleaseEvent(event)

    def eventFilter(self, watched, event):
        if watched is getattr(self, "mascot", None):
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._mascot_press = event.globalPosition().toPoint()
                self._mascot_dragged = False
                self._begin_drag(self._mascot_press)
                return True
            if event.type() == QEvent.Type.MouseMove and self._mascot_press is not None:
                position = event.globalPosition().toPoint()
                if event.buttons() & Qt.MouseButton.LeftButton:
                    if (position - self._mascot_press).manhattanLength() >= QApplication.startDragDistance():
                        if self._peek_side is not None:
                            self._expand_from_edge()
                        self._mascot_dragged = True
                        self.mascot.set_variant("drag")
                        self.mascot.setCursor(Qt.CursorShape.ClosedHandCursor)
                        self._move_drag(position)
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._mascot_press is not None:
                dragged = self._mascot_dragged
                self._mascot_press = None
                if dragged:
                    self._finish_drag()
                else:
                    self._drag_offset = None
                self._mascot_dragged = False
                self.mascot.setCursor(Qt.CursorShape.OpenHandCursor)
                if not dragged:
                    if self._peek_side is not None:
                        self._expand_from_edge()
                    else:
                        self._show_quick_panel()
                else:
                    self._show_current_artwork()
                return True
            if event.type() == QEvent.Type.ContextMenu:
                self._mascot_menu(event.globalPos())
                return True
        if watched.objectName() == "companionDragHandle":
            if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                self._begin_drag(event.globalPosition().toPoint())
                return True
            if event.type() == QEvent.Type.MouseMove and self._drag_offset is not None:
                if event.buttons() & Qt.MouseButton.LeftButton:
                    self._move_drag(event.globalPosition().toPoint())
                return True
            if event.type() == QEvent.Type.MouseButtonRelease and self._drag_offset is not None:
                self._finish_drag()
                return True
        return super().eventFilter(watched, event)

    def _begin_drag(self, global_position) -> None:
        self._drag_offset = global_position - self.frameGeometry().topLeft()

    def _move_drag(self, global_position) -> None:
        if self._drag_offset is not None:
            self.move(global_position - self._drag_offset)

    def _finish_drag(self) -> None:
        self._drag_offset = None
        if self._peek_side is None:
            self._snap_if_near_edge()

    def _snap_if_near_edge(self) -> None:
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        frame = self.frameGeometry()
        if frame.left() <= area.left() + 34:
            self._dock_to_edge("left", area)
        elif frame.right() >= area.right() - 34:
            self._dock_to_edge("right", area)

    def _dock_to_edge(self, side: str, area: QRect) -> None:
        if side not in {"left", "right"} or self._peek_side is not None:
            return
        self._expanded_size = self.size()
        if self.presentation == "mascot":
            self._mascot_panel_open = False
            self.content.hide()
            self.peek_button.hide()
            self.mascot.show()
            self._peek_side = side
            self.setFixedSize(140, 260)
            self.mascot.set_variant(f"peek-{side}")
            y = min(max(self.y(), area.top()), area.bottom() - self.height() + 1)
            self.move(area.left() if side == "left" else area.right() - self.width() + 1, y)
            self._sync_mascot_mask()
            return
        diameter = 88
        y = min(max(self.y(), area.top()), area.bottom() - diameter + 1)
        self.content.hide()
        self.peek_button.show()
        self._peek_side = side
        self.setFixedSize(diameter, diameter)
        self.setMask(QRegion(self.rect(), QRegion.RegionType.Ellipse))
        x = (
            area.left() - diameter // 2
            if side == "left"
            else area.right() - diameter // 2 + 1
        )
        self.move(x, y)

    def _expand_from_edge(self) -> None:
        if self._peek_side is None:
            return
        side = self._peek_side
        old_y = self.y()
        self._peek_side = None
        self.clearMask()
        self.peek_button.hide()
        if self.presentation == "mascot":
            self._show_mascot()
            screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                self.move(area.left() if side == "left" else area.right() - self.width() + 1,
                          min(max(old_y, area.top()), area.bottom() - self.height() + 1))
            self._expanded_size = None
            return
        self.content.show()
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.resize(self._expanded_size or self.size())
        self.setFixedWidth(300)
        self.adjustSize()
        screen = QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = area.left() if side == "left" else area.right() - self.width() + 1
            y = min(max(old_y, area.top()), area.bottom() - self.height() + 1)
            self.move(x, y)
        self._expanded_size = None

    def _set_mode(self, _index):
        if self.reminder_coordinator is not None:
            self.reminder_coordinator.set_mode(self.mode.currentData())
            self.reminder_coordinator.evaluate()

    def _sync_reminder_mode(self, snapshot):
        index = self.mode.findData(snapshot.mode)
        if index >= 0:
            self.mode.blockSignals(True)
            self.mode.setCurrentIndex(index)
            self.mode.blockSignals(False)

    def set_presentation(self, presentation, *, persist=True):
        if presentation not in {"panel", "mascot"}:
            raise ValueError("Unknown companion presentation")
        self._drag_offset = None
        self._mascot_press = None
        self._mascot_dragged = False
        self._peek_side = None
        self._expanded_size = None
        self.presentation = presentation
        if persist and self.repository is not None:
            self.repository.set_setting("companion_style", presentation)
        if presentation == "mascot":
            self._show_mascot()
        else:
            self._show_quick_panel()
        self._keep_on_screen()
        self.presentation_changed.emit(presentation)

    def _show_mascot(self):
        self._mascot_panel_open = False
        self._peek_side = None
        self.content.hide()
        self.peek_button.hide()
        self.mascot.show()
        self.setFixedSize(210, 300)
        self.mascot.set_variant(self._mascot_state)
        self._sync_mascot_mask()
        self._keep_on_screen()

    def _show_quick_panel(self):
        self._mascot_panel_open = self.presentation == "mascot"
        self._peek_side = None
        self.clearMask()
        self.mascot.hide()
        self.peek_button.hide()
        self.content.show()
        self.back_to_mascot.setVisible(self.presentation == "mascot")
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setFixedWidth(300)
        self.adjustSize()
        self._keep_on_screen()

    def _keep_on_screen(self):
        screen = QApplication.screenAt(self.frameGeometry().center()) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.move(max(area.left(), min(self.x(), area.right() - self.width() + 1)),
                      max(area.top(), min(self.y(), area.bottom() - self.height() + 1)))

    def _sync_mascot_mask(self):
        if self.presentation == "mascot" and not self._mascot_panel_open:
            region = self.mascot.hit_region.translated(self.mascot.pos())
            if not region.isEmpty():
                self.setMask(region)

    def _show_current_artwork(self):
        self.mascot.set_variant(f"peek-{self._peek_side}" if self._peek_side else self._mascot_state)

    def _sync_wellness(self, enabled):
        entry = self.bodylog_service.today_entry() if enabled and self.bodylog_service else None
        level = entry.comfort_level if entry is not None else None
        self._mascot_state = {
            WellnessLevel.COMFORTABLE: "comfortable",
            WellnessLevel.SOME_DISCOMFORT: "uncomfortable",
            WellnessLevel.PREFER_NOT_TO_SAY: "skip",
        }.get(level, "skip")
        state_label = f"今天自报：{WELLNESS_LEVEL_LABELS[level]}" if level is not None else "今天未记录状态"
        self.mascot.setToolTip(state_label + "\n单击查看任务，拖动移动，右键更多操作")
        if not self._mascot_dragged:
            self._show_current_artwork()
        self._state_day = date.today()

    def _check_day(self):
        if date.today() != self._state_day:
            self._sync_wellness(bool(self.bodylog_service and self.bodylog_service.enabled))

    def contextMenuEvent(self, event):
        self._mascot_menu(event.globalPos())
        event.accept()

    def _build_context_menu(self):
        menu = QMenu(self)
        menu.addAction("任务与情境", self._show_quick_panel)
        menu.addAction("打开主窗口", self.open_main_requested.emit)
        menu.addSeparator()
        target = "mascot" if self.presentation == "panel" else "panel"
        menu.addAction("切换为吉祥物" if target == "mascot" else "切换为简洁面板",
                       lambda: self.set_presentation(target))
        menu.addAction("隐藏", self.hide_requested.emit)
        return menu

    def _mascot_menu(self, position):
        menu = self._build_context_menu()
        try:
            menu.exec(position)
        finally:
            menu.deleteLater()

    def _hide_companion(self):
        self.hide_requested.emit()

    def hideEvent(self, event):
        self._mascot_press = None
        self._mascot_dragged = False
        self._drag_offset = None
        if getattr(self, "mascot", None) is not None:
            self.mascot.setCursor(Qt.CursorShape.OpenHandCursor)
            self._show_current_artwork()
        super().hideEvent(event)

    def _add_task(self):
        text = self.task_input.text().strip()
        if not text or self.task_service is None:
            return
        try:
            self.task_service.add_manual(text)
        except ValueError as exc:
            QMessageBox.warning(self, "无法添加任务", str(exc))
            return
        self.task_input.clear()

    def closeEvent(self, event):
        if self.isVisible():
            event.ignore()
            self.hide_requested.emit()
            return
        super().closeEvent(event)

    def refresh_tasks(self):
        while self.task_list.count():
            item = self.task_list.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        tasks = self.task_service.list_today() if self.task_service is not None else []
        if not tasks:
            self.task_list.addWidget(QLabel("暂无今日任务"))
        for task in tasks[:6]:
            box = QCheckBox(self.fontMetrics().elidedText(task.title, Qt.TextElideMode.ElideRight, 245))
            box.setChecked(task.status is TaskStatus.DONE)
            box.setToolTip(task.title)
            box.toggled.connect(lambda checked, task_id=task.id: self._toggle_task(task_id, checked))
            self.task_list.addWidget(box)

    def _toggle_task(self, task_id: int, done: bool):
        if self.task_service is not None:
            self.task_service.set_status(task_id, TaskStatus.DONE if done else TaskStatus.TODO)
            if done and self.reminder_coordinator is not None:
                self.reminder_coordinator.mark_task_completed()
