"""Small, optional desktop companion for quick, user-confirmed task updates."""

from __future__ import annotations

import importlib.util
from pathlib import Path

from PySide6.QtCore import QObject, QThread, QTimer, Qt, Signal, Slot
from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
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
from deskcare.voice.vosk_adapter import transcribe_pcm


class _TranscribeWorker(QObject):
    finished = Signal(str, str)

    def __init__(self, model_path: str, pcm: bytes):
        super().__init__()
        self.model_path = model_path
        self.pcm = pcm

    @Slot()
    def run(self):
        try:
            self.finished.emit(transcribe_pcm(self.model_path, self.pcm), "")
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
        self._audio_source = None
        self._audio_device = None
        self._audio_buffer = bytearray()
        self._voice_thread = None
        self.setObjectName("deskcareCompanion")
        self.setWindowTitle("DeskCare 桌面伙伴")
        self.setFixedWidth(300)
        self.setStyleSheet(
            "QWidget#deskcareCompanion{background:#F7F5F0;border:1px solid #C9D9D0;border-radius:18px;}"
            "QLabel{color:#214F45;} QPushButton{background:#2F6B5F;color:white;border:0;border-radius:9px;padding:8px;}"
            "QLineEdit,QComboBox{background:white;border:1px solid #D7E1DB;border-radius:8px;padding:7px;}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 14)
        title_row = QHBoxLayout()
        title = QLabel("DeskCare · 今日伙伴")
        title.setStyleSheet("font-size:15px;font-weight:700")
        title_row.addWidget(title)
        title_row.addStretch()
        hide_button = QPushButton("隐藏")
        hide_button.setFixedWidth(58)
        hide_button.clicked.connect(self.hide_requested.emit)
        title_row.addWidget(hide_button)
        root.addLayout(title_row)

        self.mode = QComboBox()
        for value, text in (("normal", "普通工作"), ("focus", "专注模式"), ("meeting", "会议中"), ("reading", "阅读中"), ("quiet", "安静时段")):
            self.mode.addItem(text, value)
        self.mode.currentIndexChanged.connect(self._set_mode)
        root.addWidget(QLabel("当前情境"))
        root.addWidget(self.mode)
        root.addWidget(QLabel("今日任务（勾选即标记完成）"))
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
        add_row.addWidget(QPushButton("添加任务"))
        add_row.itemAt(0).widget().clicked.connect(self._add_task)
        self.voice_button = QPushButton("按住说话")
        self.voice_button.setToolTip("按住录音，松开后使用已配置的本地 Vosk 模型识别；音频仅保留在内存。")
        self.voice_button.pressed.connect(self._start_recording)
        self.voice_button.released.connect(self._stop_recording)
        add_row.addWidget(self.voice_button)
        root.addLayout(add_row)
        self.model_path = repository.get_setting("voice_model_path", "") if repository is not None else ""
        self.model_button = QPushButton("选择离线语音模型文件夹")
        self.model_button.clicked.connect(self._choose_model)
        root.addWidget(self.model_button)
        self.recording_hint = QLabel("首次使用：安装可选 voice 组件并选择本地 Vosk 中文模型；不使用云端识别。")
        self.recording_hint.setWordWrap(True)
        self.recording_hint.setStyleSheet("color:#71817C;font-size:11px")
        root.addWidget(self.recording_hint)
        self.transcript = QLineEdit()
        self.transcript.setPlaceholderText("语音文字草稿：核对后再添加")
        root.addWidget(self.transcript)
        confirm = QPushButton("确认草稿并添加")
        confirm.clicked.connect(self._confirm_transcript)
        root.addWidget(confirm)
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
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_offset = None
        super().mouseReleaseEvent(event)

    def _set_mode(self, _index):
        if self.reminder_coordinator is not None:
            self.reminder_coordinator.set_mode(self.mode.currentData())
            self.reminder_coordinator.evaluate()

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
        path = QFileDialog.getExistingDirectory(self, "选择已解压的 Vosk 中文模型文件夹", self.model_path)
        if path:
            self.model_path = path
            if self.repository is not None:
                self.repository.set_setting("voice_model_path", path)
            self.recording_hint.setText("已配置本地模型；按住录音后松开，识别结果只进入草稿框。")

    def _start_recording(self):
        if self._voice_thread is not None and self._voice_thread.isRunning():
            return
        if not importlib.util.find_spec("vosk"):
            self.recording_hint.setText("本地语音组件未安装；安装 voice 可选依赖后仍可使用手动输入。")
            return
        if not self.model_path or not Path(self.model_path).is_dir():
            self.recording_hint.setText("请先选择已下载并解压的 Vosk 中文离线模型文件夹。")
            return
        audio_format = QAudioFormat()
        audio_format.setSampleRate(16000)
        audio_format.setChannelCount(1)
        audio_format.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        device = QMediaDevices.defaultAudioInput()
        if device.isNull() or not device.isFormatSupported(audio_format):
            self.recording_hint.setText("当前默认麦克风不支持 16 kHz 单声道 PCM；请检查 Windows 麦克风设置。")
            return
        self._audio_buffer.clear()
        self._audio_source = QAudioSource(device, audio_format, self)
        self._audio_source.stateChanged.connect(self._audio_state_changed)
        self._audio_device = self._audio_source.start()
        if self._audio_device is None:
            self.recording_hint.setText("无法打开麦克风；请检查系统麦克风权限。仍可手动输入任务。")
            self._audio_source.stop()
            self._audio_source.deleteLater()
            self._audio_source = None
            return
        self.recording_hint.setText("正在本机录音…松开按钮结束。最多录制 30 秒；不会保存音频文件。")
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
            timer = getattr(self, "_audio_timer", None)
            if timer is not None:
                timer.stop()
            self.voice_button.setText("按住说话")
            self.recording_hint.setText("麦克风不可用或权限被拒绝；没有任务被修改，可手动输入。")

    def _read_audio(self):
        if self._audio_device is None:
            return
        available = self._audio_device.bytesAvailable()
        if available > 0:
            self._audio_buffer.extend(bytes(self._audio_device.read(min(available, 8192))))
        if len(self._audio_buffer) >= 16000 * 2 * 30:
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
            self.recording_hint.setText("没有录到语音；音频缓冲已丢弃。")
            return
        self.voice_button.setEnabled(False)
        self.recording_hint.setText("正在本机识别；识别完成前音频只保存在内存中。")
        thread = QThread(self)
        worker = _TranscribeWorker(self.model_path, bytes(self._audio_buffer))
        self._audio_buffer.clear()
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_transcribed)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda: setattr(self, "_voice_thread", None))
        self._voice_thread = thread
        thread.start()

    def _on_transcribed(self, text: str, error: str):
        self.voice_button.setEnabled(True)
        if error:
            self.recording_hint.setText(f"本地识别失败：{error}。可以改为手动输入。")
        elif not text:
            self.recording_hint.setText("没有识别出文字；没有创建或修改任务。可重试或手动输入。")
        else:
            self.transcript.setText(text)
            self.recording_hint.setText("这是未确认的识别草稿；检查后点击“确认草稿并添加”才会写入任务。")

    def closeEvent(self, event):
        if self.isVisible():
            event.ignore()
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
