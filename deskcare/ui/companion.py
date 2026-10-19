"""Small, optional desktop companion for quick, user-confirmed task updates."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRect, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtGui import (
    QColor,
    QCursor,
    QPainter,
    QPainterPath,
    QPen,
    QRadialGradient,
    QRegion,
)
from PySide6.QtMultimedia import QAudioSource, QMediaDevices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QApplication,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from deskcare.domain.types import TaskStatus
from deskcare.voice.audio import to_vosk_pcm16
from deskcare.voice.vosk_adapter import transcribe_pcm


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


class _TranscribeWorker(QObject):
    finished = Signal(str, str)

    def __init__(self, model_path: str, pcm: bytes, sample_rate: int, channels: int, sample_format):
        super().__init__()
        self.model_path = model_path
        self.pcm = pcm
        self.sample_rate = sample_rate
        self.channels = channels
        self.sample_format = sample_format

    @Slot()
    def run(self):
        try:
            mono_pcm = to_vosk_pcm16(self.pcm, self.sample_rate, self.channels, self.sample_format)
            self.finished.emit(transcribe_pcm(self.model_path, mono_pcm), "")
        except Exception as exc:
            self.finished.emit("", str(exc))


class CompanionWindow(QWidget):
    """Frameless, draggable top-level helper; hidden unless explicitly enabled."""

    hide_requested = Signal()
    open_main_requested = Signal()

    def __init__(self, task_service=None, reminder_coordinator=None, repository=None, parent=None):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.task_service = task_service
        self.reminder_coordinator = reminder_coordinator
        self.repository = repository
        self._drag_offset = None
        self._peek_side: str | None = None
        self._expanded_size = None
        self._audio_source = None
        self._audio_device = None
        self._audio_format = None
        self._audio_max_bytes = 0
        self._audio_buffer = bytearray()
        self._voice_thread = None
        self._voice_worker = None
        self.setObjectName("deskcareCompanion")
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowTitle("DeskCare 桌面伙伴")
        self.setFixedWidth(300)
        self.setStyleSheet(
            "QWidget#companionContent{background:#F7F5F0;color:#24312E;border:1px solid #C9D9D0;border-radius:20px;}"
            "QLabel{color:#214F45;} QPushButton{background:#2F6B5F;color:white;border:0;border-radius:9px;padding:8px;}"
            "QLineEdit,QComboBox{color:#24312E;background:white;border:1px solid #D7E1DB;border-radius:8px;padding:7px;}"
            "QComboBox QAbstractItemView{color:#24312E;background:#FFFFFF;selection-color:#214F45;selection-background-color:#D4E4D9;outline:0;}"
            "QComboBox QAbstractItemView::item{color:#24312E;padding:8px 10px;min-height:24px;}"
        )
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.content = QWidget(self)
        self.content.setObjectName("companionContent")
        root = QVBoxLayout(self.content)
        root.setContentsMargins(14, 12, 14, 14)
        title_row = QHBoxLayout()
        title_row.addWidget(SproutMascot(parent=self))
        title = QLabel("DeskCare · 今日伙伴")
        title.setObjectName("companionDragHandle")
        title.setCursor(Qt.CursorShape.SizeAllCursor)
        title.setToolTip("拖动这里移动；靠近屏幕左右边缘松开可收成半露状态")
        title.installEventFilter(self)
        title.setStyleSheet("font-size:15px;font-weight:700")
        title_row.addWidget(title)
        title_row.addStretch()
        hide_button = QPushButton("隐藏")
        hide_button.setFixedWidth(58)
        hide_button.clicked.connect(self._hide_companion)
        title_row.addWidget(hide_button)
        root.addLayout(title_row)

        self.mode = QComboBox()
        self.mode.setObjectName("companionContextSelector")
        self.mode.setMaxVisibleItems(5)
        self.mode.setMinimumHeight(40)
        for value, text in (("normal", "普通工作"), ("focus", "专注模式"), ("meeting", "会议中"), ("reading", "阅读中"), ("quiet", "安静时段")):
            self.mode.addItem(text, value)
        self.mode.currentIndexChanged.connect(self._set_mode)
        root.addWidget(QLabel("当前情境"))
        root.addWidget(self.mode)
        root.addWidget(QLabel("今天要做的事（勾选表示完成）"))
        self.task_list = QVBoxLayout()
        self.task_list.setSpacing(4)
        root.addLayout(self.task_list)
        open_main = QPushButton("打开 DeskCare 主窗口")
        open_main.clicked.connect(self.open_main_requested.emit)
        root.addWidget(open_main)
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText("快速添加一条任务…")
        self.task_input.returnPressed.connect(self._add_task)
        root.addWidget(self.task_input)
        add_row = QHBoxLayout()
        self.add_task_button = QPushButton("添加任务")
        self.add_task_button.clicked.connect(self._add_task)
        add_row.addWidget(self.add_task_button)
        self.voice_button = QPushButton("按住说话")
        self.voice_button.setToolTip("语音转文字目前是可选的离线功能，需要先设置语音包。松开后请核对文字草稿；录音只暂存在内存。")
        self.voice_button.pressed.connect(self._start_recording)
        self.voice_button.released.connect(self._stop_recording)
        add_row.addWidget(self.voice_button)
        root.addLayout(add_row)
        self.model_path = repository.get_setting("voice_model_path", "") if repository is not None else ""
        self.model_button = QPushButton("选择离线语音包")
        self.model_button.clicked.connect(self._choose_model)
        root.addWidget(self.model_button)
        self.recording_hint = QLabel("语音转文字目前需要额外配置离线语音包；不想设置时，直接输入任务也一样方便。")
        self.recording_hint.setWordWrap(True)
        self.recording_hint.setStyleSheet("color:#71817C;font-size:11px")
        root.addWidget(self.recording_hint)
        self.transcript = QLineEdit()
        self.transcript.setPlaceholderText("语音文字草稿：核对后再添加")
        root.addWidget(self.transcript)
        confirm = QPushButton("确认并添加")
        confirm.clicked.connect(self._confirm_transcript)
        root.addWidget(confirm)
        outer.addWidget(self.content)
        self.peek_button = SproutMascot(interactive=True, parent=self)
        self.peek_button.setFixedSize(88, 88)
        self.peek_button.clicked.connect(self._expand_from_edge)
        self.peek_button.hide()
        outer.addWidget(self.peek_button)
        if self.task_service is not None:
            self.task_service.subscribe(self.refresh_tasks)
        self.refresh_tasks()
        self.adjustSize()
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

    def _hide_companion(self):
        self.stop_voice_input()
        self.hide_requested.emit()

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

    def _confirm_transcript(self):
        draft = self.transcript.text().strip()
        if not draft:
            return
        self.task_input.setText(draft)
        self._add_task()
        if not self.task_input.text():
            self.transcript.clear()

    def _choose_model(self):
        path = QFileDialog.getExistingDirectory(self, "选择已准备好的离线语音包", self.model_path)
        if path:
            self.model_path = path
            if self.repository is not None:
                self.repository.set_setting("voice_model_path", path)
            self.recording_hint.setText("语音输入已设置。按住说话，松开后先检查文字草稿，再决定是否添加。")

    def _start_recording(self):
        if self._voice_thread is not None and self._voice_thread.isRunning():
            return
        if not importlib.util.find_spec("vosk"):
            self.recording_hint.setText("语音功能组件尚未安装；你仍可直接输入任务。")
            return
        if not self.model_path or not Path(self.model_path).is_dir():
            self.recording_hint.setText("还没有设置语音包。可点“选择离线语音包”，也可以直接输入任务。")
            return
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            self.recording_hint.setText("没有找到可用麦克风；请检查 Windows 麦克风权限，或直接输入任务。")
            return
        audio_format = device.preferredFormat()
        try:
            to_vosk_pcm16(
                b"", audio_format.sampleRate(), audio_format.channelCount(), audio_format.sampleFormat()
            )
        except (ValueError, RuntimeError) as exc:
            self.recording_hint.setText(f"当前麦克风格式暂不支持：{exc} 你仍可直接输入任务。")
            return
        self._audio_buffer.clear()
        self._audio_format = audio_format
        self._audio_max_bytes = max(1, audio_format.bytesPerFrame()) * audio_format.sampleRate() * 30
        self._audio_source = QAudioSource(device, audio_format, self)
        self._audio_source.stateChanged.connect(self._audio_state_changed)
        self._audio_device = self._audio_source.start()
        if self._audio_device is None:
            self.recording_hint.setText("暂时无法打开麦克风。请检查 Windows 麦克风权限，或直接输入任务。")
            self._audio_source.stop()
            self._audio_source.deleteLater()
            self._audio_source = None
            self._audio_format = None
            return
        self.recording_hint.setText("正在录音…松开按钮结束，最多 30 秒；录音不会保存成文件。")
        self.voice_button.setText("正在录音…松开结束")
        self._audio_timer = QTimer(self)
        self._audio_timer.setInterval(50)
        self._audio_timer.timeout.connect(self._read_audio)
        self._audio_timer.start()

    def _audio_state_changed(self, state):
        if self._audio_source is None:
            return
        if self._audio_source.error() != QAudioSource.Error.NoError:
            self._audio_source.stop()
            self._audio_source.deleteLater()
            self._audio_source = None
            self._audio_device = None
            self._audio_buffer.clear()
            self._audio_format = None
            timer = getattr(self, "_audio_timer", None)
            if timer is not None:
                timer.stop()
            self.voice_button.setText("按住说话")
            self.voice_button.setEnabled(True)
            self.recording_hint.setText("麦克风暂不可用或权限未开启，没有任务被修改；你可以检查设置或直接输入。")

    def _read_audio(self):
        if self._audio_device is None:
            return
        available = self._audio_device.bytesAvailable()
        if available > 0:
            self._audio_buffer.extend(bytes(self._audio_device.read(min(available, 8192))))
        if self._audio_max_bytes and len(self._audio_buffer) >= self._audio_max_bytes:
            self._stop_recording()
            self.recording_hint.setText("已达到 30 秒录音上限，正在本机识别。")

    def _stop_recording(self):
        timer = getattr(self, "_audio_timer", None)
        if timer is None or not timer.isActive():
            return
        timer.stop()
        self._read_audio()
        if self._audio_source is not None:
            self._audio_source.stop()
            self._audio_source.deleteLater()
        self._audio_source = None
        self._audio_device = None
        self.voice_button.setText("按住说话")
        if not self._audio_buffer:
            self._audio_format = None
            self.recording_hint.setText("没有录到语音；音频缓冲已丢弃。")
            return
        self.voice_button.setEnabled(False)
        self.recording_hint.setText("正在本机识别；识别完成前音频只保存在内存中。")
        thread = QThread(self)
        worker = _TranscribeWorker(
            self.model_path,
            bytes(self._audio_buffer),
            self._audio_format.sampleRate(),
            self._audio_format.channelCount(),
            self._audio_format.sampleFormat(),
        )
        self._audio_buffer.clear()
        self._audio_format = None
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_transcribed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        self._voice_thread = thread
        self._voice_worker = worker
        thread.finished.connect(self._on_voice_thread_finished)
        thread.start()

    def _on_transcribed(self, text: str, error: str):
        self.voice_button.setEnabled(True)
        if error:
            self.recording_hint.setText(f"语音没有识别成功：{error}。你可以重试或直接输入任务。")
        elif not text:
            self.recording_hint.setText("没有听清内容，任务没有改动。可以重试或直接输入。")
        else:
            self.transcript.setText(text)
            self.recording_hint.setText("这是待确认的文字草稿。检查无误后点击“确认并添加”才会保存。")

    @Slot()
    def _on_voice_thread_finished(self):
        self._voice_thread = None
        self._voice_worker = None
        self.voice_button.setEnabled(True)

    def closeEvent(self, event):
        if self.isVisible():
            event.ignore()
            self.stop_voice_input()
            self.hide_requested.emit()
            return
        self.stop_voice_input()
        super().closeEvent(event)

    def stop_voice_input(self):
        timer = getattr(self, "_audio_timer", None)
        if timer is not None:
            timer.stop()
        if self._audio_source is not None:
            self._audio_source.stop()
            self._audio_source.deleteLater()
        self._audio_source = None
        self._audio_device = None
        self._audio_buffer.clear()
        self._audio_format = None
        self.voice_button.setText("按住说话")
        self.voice_button.setEnabled(True)
        if self._voice_thread is not None and self._voice_thread.isRunning():
            self._voice_thread.quit()
            self._voice_thread.wait()

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
            box = QCheckBox(task.title)
            box.setChecked(task.status is TaskStatus.DONE)
            box.setToolTip("只在你勾选时更新本地任务状态")
            box.toggled.connect(lambda checked, task_id=task.id: self._toggle_task(task_id, checked))
            self.task_list.addWidget(box)

    def _toggle_task(self, task_id: int, done: bool):
        if self.task_service is not None:
            self.task_service.set_status(task_id, TaskStatus.DONE if done else TaskStatus.TODO)
            if done and self.reminder_coordinator is not None:
                self.reminder_coordinator.mark_task_completed()
