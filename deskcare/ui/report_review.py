"""Readable review cards and a separate, deliberate AI send workflow."""
from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (QCheckBox, QDialog, QFrame, QHBoxLayout, QLabel,
                               QPlainTextEdit, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from deskcare.services.report_review import ACTION_LABELS
from deskcare.services.reminder_advice import AdviceError
from deskcare.ui.choices import SoftComboBox


class _ReviewWorker(QObject):
    finished = Signal(int, object, object, str)

    def __init__(self, service, request, generation):
        super().__init__()
        self.service, self.request = service, request
        self.generation = generation

    @Slot()
    def run(self):
        try:
            self.finished.emit(self.generation, self.request, self.service.analyze(self.request, confirmed=True), '')
        except AdviceError as exc:
            self.finished.emit(self.generation, self.request, None, str(exc))
        except Exception:
            self.finished.emit(self.generation, self.request, None, '这次分析没有完成，本机回顾仍可查看。')


class ReportReviewDialog(QDialog):
    open_view_requested = Signal(str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._thread = self._worker = self._request = self.snapshot = None
        self._generation = 0
        self.setWindowTitle('日报与周报 · 回顾与下一步')
        self.resize(820, 760)
        root = QVBoxLayout(self)
        root.setSpacing(12)
        self.heading = QLabel('回顾一下，接下来先做什么？')
        self.heading.setObjectName('cardTitle')
        root.addWidget(self.heading)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.status)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        self.cards = QVBoxLayout(content)
        self.cards.setContentsMargins(0, 0, 8, 0)
        self.cards.setSpacing(10)
        area.setWidget(content)
        root.addWidget(area, 1)
        self.actions = QHBoxLayout()
        root.addLayout(self.actions)
        self.provider = SoftComboBox()
        self.provider.addItem('联网 AI · 使用已配置的服务', 'cloud')
        self.provider.addItem('本机 AI', 'local')
        self.provider.currentIndexChanged.connect(self._invalidate)
        root.addWidget(self.provider)
        self.consent = QCheckBox('允许 AI 参考这份报告的数量汇总（独立授权，可随时关闭）')
        self.consent.setObjectName('aiConsent')
        self.consent.setChecked(service.enabled)
        self.consent.toggled.connect(self._consent_changed)
        root.addWidget(self.consent)
        notice = QLabel('只发时长、任务与提醒数量，不含任务内容、应用名或健康记录。联网可能产生费用并由服务商保留；每次都要确认。')
        notice.setWordWrap(True)
        notice.setObjectName('mutedText')
        root.addWidget(notice)
        row = QHBoxLayout()
        self.preview_button = QPushButton('查看本次发送内容')
        self.preview_button.clicked.connect(self.prepare_request)
        row.addWidget(self.preview_button)
        self.send_button = QPushButton('确认发送，帮我挑出重点')
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send_request)
        row.addWidget(self.send_button)
        self.close_button = QPushButton('关闭')
        self.close_button.setObjectName('secondaryButton')
        self.close_button.clicked.connect(self.reject)
        row.addWidget(self.close_button)
        root.addLayout(row)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(145)
        self.preview.setMaximumHeight(200)
        self.preview.setPlaceholderText('无需 AI 也能查看上方回顾。点“查看本次发送内容”后再决定是否发送。')
        root.addWidget(self.preview)

    def begin(self, facts):
        self._invalidate()
        self.snapshot = self.service.snapshot(facts)
        self.heading.setText('周报复盘 · 先看什么，接着做什么' if self.snapshot.data['period']['type'] == 'weekly'
                             else '日报复盘 · 先看什么，接着做什么')
        self.consent.blockSignals(True)
        self.consent.setChecked(self.service.enabled)
        self.consent.blockSignals(False)
        self._show_baseline()
        self.show()
        self.raise_()
        self.activateWindow()

    def _show_baseline(self):
        if self.snapshot is None:
            return
        cards = self.snapshot.cards[:3]
        actions = tuple(dict.fromkeys(card.action for card in cards if card.action))[:2]
        self._render(cards, actions)
        demo = '虚构演示 · ' if self.snapshot.data['data_is_demo'] else ''
        self.status.setText(f'{demo}{self.snapshot.captured_at:%m月%d日 %H:%M} 的记录快照 · 本机回顾，尚未使用 AI。原始日报保持不变。')

    def _render(self, cards, actions):
        for layout in (self.cards, self.actions):
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().hide()
                    item.widget().deleteLater()
        for number, card in enumerate(cards, 1):
            frame = QFrame()
            frame.setObjectName('card')
            layout = QVBoxLayout(frame)
            layout.setContentsMargins(16, 12, 16, 12)
            title = QLabel(f'{number:02d}  {card.title}')
            title.setObjectName('cardTitle')
            title.setWordWrap(True)
            layout.addWidget(title)
            detail = QLabel(card.detail)
            detail.setWordWrap(True)
            layout.addWidget(detail)
            self.cards.addWidget(frame)
        self.cards.addStretch()
        for action in actions:
            button = QPushButton(ACTION_LABELS[action])
            button.setObjectName('secondaryButton')
            button.clicked.connect(lambda _checked=False, action=action: self._open_view(action))
            self.actions.addWidget(button)
        self.actions.addStretch()

    def _open_view(self, action):
        self.reject()
        self.open_view_requested.emit(action)

    def _invalidate(self, *_):
        self._generation += 1
        self.service.invalidate()
        self._request = None
        self.send_button.setEnabled(False)
        self.preview.clear()
        self._show_baseline()

    def _consent_changed(self, enabled):
        self.service.set_enabled(enabled)
        self._invalidate()
        if not enabled:
            self.status.setText('AI 复盘授权已关闭。尚未发送的内容不会发送；已发送的内容无法撤回。本机回顾仍可查看。')

    def prepare_request(self):
        if self.snapshot is None or self._thread is not None:
            return
        try:
            request = self.service.prepare(self.snapshot, self.provider.currentData())
            self._request = request
            destination = ('发送到：' if request.provider == 'cloud' else '本机服务：') + request.endpoint
            self.preview.setPlainText(f'{destination}\n模型：{request.model}\n\n{request.snapshot.human_preview()}')
            self.send_button.setEnabled(self.service.enabled)
            self.status.setText('请核对下方内容。只有打开独立授权并点击“确认发送”，才会请求 AI。')
        except AdviceError as exc:
            self.status.setText(str(exc))
            self._request = None
            self.send_button.setEnabled(False)

    def send_request(self):
        if self._request is None or self._thread is not None or not self.service.enabled:
            return
        request = self._request
        self._request = None
        self.send_button.setEnabled(False)
        self.preview_button.setEnabled(False)
        self.status.setText('正在参考这份快照挑选复盘重点… 原始日报、任务和提醒设置不会改变。')
        generation = self._generation
        thread = QThread(self)
        worker = _ReviewWorker(self.service, request, generation)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        # A QObject-bound slot is required: a free lambda may run on the worker
        # thread in PySide and must never create or delete widgets there.
        worker.finished.connect(self._finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_done)
        thread.finished.connect(thread.deleteLater)
        self._thread, self._worker = thread, worker
        thread.start()

    @Slot(int, object, object, str)
    def _finished(self, generation, request, result, error):
        if generation != self._generation:
            return
        try:
            current = self.service.is_current(request)
        except AdviceError:
            current = False
        if error or result is None or not current:
            self._show_baseline()
            self.status.setText((error or '授权或服务已改变，结果未采用。') + ' 本机回顾仍可查看，原始日报未改动。')
            return
        self._render(*result)
        provider = '联网 AI' if request.provider == 'cloud' else '本机 AI'
        demo = '虚构演示 · ' if request.snapshot.data['data_is_demo'] else ''
        self.status.setText(f'{demo}{provider} 已挑选复盘重点 · {request.snapshot.captured_at:%H:%M} 快照。数字与文字依据仍来自本机记录；不是健康或效率判断。')

    @Slot()
    def _thread_done(self):
        self._thread = self._worker = None
        self.preview_button.setEnabled(True)

    def done(self, result):
        self._invalidate()
        super().done(result)
