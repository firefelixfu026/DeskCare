"""A deliberate preview -> send -> review -> confirm reminder workflow."""
from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFormLayout, QHBoxLayout, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
    QTabWidget, QWidget,
)

from deskcare.domain.types import TaskStatus
from deskcare.ui.choices import SoftComboBox
from deskcare.services.reminder_advice import AdviceError


class _AdviceWorker(QObject):
    finished = Signal(object, str)

    def __init__(self, advisor, request):
        super().__init__()
        self.advisor, self.request = advisor, request

    @Slot()
    def run(self):
        try:
            self.finished.emit(self.advisor.analyze(self.request, confirmed=True), "")
        except AdviceError as exc:
            self.finished.emit(None, str(exc))
        except Exception:
            self.finished.emit(None, "分析未完成，原提醒不变。")


class ReminderAdviceDialog(QDialog):
    interval_applied = Signal(int)

    def __init__(self, service, advisor, parent=None):
        super().__init__(parent)
        self.service, self.advisor = service, advisor
        self._thread = None
        self._worker = None
        self._request = None
        self.context = None
        self.advice = None
        self._discard = False
        self.setWindowTitle("分析提醒安排")
        self.resize(760, 620)
        self.setMinimumSize(620, 520)
        root = QVBoxLayout(self)
        root.setSpacing(9)
        title = QLabel("怎样提醒，更适合现在的安排？")
        title.setObjectName("cardTitle")
        root.addWidget(title)
        notice = QLabel("只分析下面选定的信息，不读取屏幕。AI 不会替你更改间隔；不发送时也有本机建议。")
        notice.setWordWrap(True)
        root.addWidget(notice)
        input_page = QWidget()
        input_layout = QVBoxLayout(input_page)
        input_layout.setContentsMargins(4, 8, 4, 4)
        input_layout.setSpacing(10)
        form = QFormLayout()
        self.provider = SoftComboBox()
        self.provider.addItem("本机 AI", "local")
        self.provider.addItem("联网 AI（使用已配置的服务）", "cloud")
        if not advisor.local_ai or not advisor.local_ai.enabled:
            self.provider.setCurrentIndex(1)
        form.addRow("分析服务", self.provider)
        self.task = SoftComboBox()
        form.addRow("本次参考的任务", self.task)
        self.comfort = SoftComboBox()
        self.comfort.addItem("不提供感受", None)
        self.comfort.addItem("本次自报：无明显不适", "comfortable")
        self.comfort.addItem("本次自报：有点不适", "some_discomfort")
        self.comfort.setToolTip("仅供本次分析，不保存为打卡或不适记录；不会读取历史健康记录。")
        form.addRow("感受（可不提供）", self.comfort)
        input_layout.addLayout(form)
        self.context_summary = QLabel()
        self.context_summary.setTextFormat(Qt.TextFormat.PlainText)
        self.context_summary.setWordWrap(True)
        self.consent = QCheckBox("允许将本次选定的情境提供给 AI 分析（独立授权）")
        self.consent.setObjectName("aiConsent")
        self.consent.setChecked(service.enabled)
        self.consent.toggled.connect(self._consent_changed)
        input_layout.addWidget(self.consent)
        self.destination = QLabel()
        self.destination.setTextFormat(Qt.TextFormat.PlainText)
        self.destination.setWordWrap(True)
        input_layout.addWidget(self.destination)
        row = QHBoxLayout()
        self.prepare_button = QPushButton("预览本次分析内容")
        self.prepare_button.clicked.connect(self.prepare_request)
        row.addWidget(self.prepare_button)
        self.send_button = QPushButton("确认发送并分析")
        self.send_button.setEnabled(False)
        self.send_button.clicked.connect(self.send_request)
        row.addWidget(self.send_button)
        row.addStretch()
        input_layout.addLayout(row)
        self.preview = QPlainTextEdit()
        self.preview.setReadOnly(True)
        self.preview.setMinimumHeight(100)
        self.preview.setPlaceholderText("这里会用普通文字列出本次提供的信息。先开启上方授权，再预览并确认发送。")
        input_layout.addWidget(self.preview, 1)
        self.result = QPlainTextEdit()
        self.result.setReadOnly(True)
        self.result.setMinimumHeight(100)
        result_page = QWidget()
        result_layout = QVBoxLayout(result_page)
        result_layout.setContentsMargins(4, 8, 4, 4)
        result_layout.addWidget(self.context_summary)
        result_layout.addWidget(self.result, 1)
        self.details = QTabWidget()
        self.details.addTab(result_page, "建议")
        self.details.addTab(input_page, "本次信息与发送预览")
        root.addWidget(self.details, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        root.addWidget(self.status)
        actions = QHBoxLayout()
        self.apply_button = QPushButton("确认采用建议间隔")
        self.apply_button.setEnabled(False)
        self.apply_button.clicked.connect(self.apply_advice)
        actions.addWidget(self.apply_button)
        keep = QPushButton("先不修改")
        keep.setObjectName("secondaryButton")
        keep.clicked.connect(self.reject)
        actions.addWidget(keep)
        actions.addStretch()
        root.addLayout(actions)
        for combo in (self.provider, self.task, self.comfort):
            combo.currentIndexChanged.connect(self.refresh_context)

    def begin(self):
        if self._thread is not None:
            self.show()
            self.raise_()
            return
        self._discard = False
        self.task.blockSignals(True)
        self.task.clear()
        self.task.addItem("不选任务（不会猜测你正在做什么）", None)
        for task in self.service.tasks.list_today(self.service.now().date()):
            if task.status is not TaskStatus.DONE and task.confirmed_at is not None:
                self.task.addItem(task.title, task.id)
        self.task.blockSignals(False)
        self.comfort.setCurrentIndex(0)
        self.consent.blockSignals(True)
        self.consent.setChecked(self.service.enabled)
        self.consent.blockSignals(False)
        self.refresh_context()
        self.details.setCurrentIndex(0)
        self.show()
        self.raise_()

    def refresh_context(self, *_):
        if self._thread is not None:
            return
        self._request = None
        self.send_button.setEnabled(False)
        self.preview.clear()
        self.apply_button.setEnabled(False)
        try:
            self.context = self.service.capture(self.task.currentData(), self.comfort.currentData())
            self.advice = self.service.fallback(self.context)
            data = self.context.data
            from deskcare.services.reminder_service import MODE_LABELS
            task = data["selected_task"]
            active = data["active_minutes_estimate"]
            feedback = data["feedback"]
            self.context_summary.setText(
                ("演示数据（非真实使用记录）\n" if data["data_is_demo"] else "")
                + f"本次快照 {self.context.captured_at:%H:%M} · {MODE_LABELS.get(data['mode'], data['mode'])} · "
                f"当前间隔 {data['interval_minutes']} 分钟\n"
                + (f"累计活跃估计 {active:g} 分钟" if active is not None else "当前活动信息不可用")
                + (f" · 已选任务：{task['title']}" if task else " · 未选定任务")
                + (f"\n同情境 {feedback['context_count']} 条反馈：推迟 {feedback.get('snoozed', 0)} 次，"
                   f"跳过 {feedback.get('skipped', 0)} 次，明确不合适 {feedback['bad_timing']} 次。"
                   if feedback["context_count"] else "")
            )
            self.result.setPlainText(self.advice.text())
            self.apply_button.setEnabled(self.advice.interval_minutes is not None)
            self.status.setText("这是本机建议。需要 AI 时，先预览，再确认发送。")
        except AdviceError as exc:
            self.context = self.advice = None
            self.context_summary.clear()
            self.result.clear()
            self.status.setText(str(exc))
        self.destination.setText(
            "联网内容会离开本机，可能产生费用或被服务商保留。感受可不提供；历史不适记录不发送。"
            if self.provider.currentData() == "cloud" else
            "本机分析只连接回环服务；历史不适记录不读取、不发送。"
        )

    def _consent_changed(self, enabled):
        if enabled:
            answer = QMessageBox.question(
                self, "开启提醒分析授权？",
                "此权限独立于任务清单 AI。允许你主动将当前模式、计时估计、反馈汇总、选定任务和可选感受提供给 AI。\n"
                "每次仍需预览并确认发送。联网时这些信息会离开本机，感受可能属于敏感信息；可不提供。\n"
                "历史不适记录、检验单、应用名称和活动轨迹不在范围内。撤回不能收回已经发送的内容。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.consent.blockSignals(True)
                self.consent.setChecked(False)
                self.consent.blockSignals(False)
                return
        try:
            self.service.set_enabled(enabled)
        except Exception:
            self.consent.blockSignals(True)
            self.consent.setChecked(self.service.enabled)
            self.consent.blockSignals(False)
            self.status.setText("授权状态没有保存，请重试。")
            return
        self.send_button.setEnabled(False)
        self._request = None
        if enabled:
            self.preview.clear()
            self.status.setText("提醒分析授权已开启；请预览本次内容后，再确认发送。")
        if not enabled:
            if self._thread is not None:
                self._discard = True
            self._request = None
            self.apply_button.setEnabled(False)
            self.status.setText("已撤回提醒分析授权；不再发送，进行中的结果将丢弃。已发送内容无法撤回。")

    def prepare_request(self):
        self.refresh_context()
        if self.context is None:
            return
        try:
            request = self.advisor.prepare(self.context, self.provider.currentData())
        except AdviceError as exc:
            self.status.setText(str(exc))
            return
        self._request = request
        self.preview.setPlainText(request.human_preview())
        self.details.setCurrentIndex(1)
        self.destination.setText(f"发送到：{request.endpoint}  ·  模型：{request.model}\n" + self.destination.text())
        self.send_button.setEnabled(self.service.enabled)
        self.status.setText("请核对本次提供的信息。" + ("确认后才会发送。" if self.service.enabled else "请先开启上方的提醒分析授权，再重新预览。"))

    def send_request(self):
        if self._request is None or not self.service.enabled or self._thread is not None:
            return
        if not self.service.is_current(self._request.context):
            self.refresh_context()
            self.status.setText("上下文已改变，请重新预览。")
            return
        self._discard = False
        thread = QThread(self)
        worker = _AdviceWorker(self.advisor, self._request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._received)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._thread_done)
        thread.finished.connect(thread.deleteLater)
        self._thread, self._worker = thread, worker
        for widget in (self.provider, self.task, self.comfort, self.prepare_button, self.send_button, self.apply_button):
            widget.setEnabled(False)
        self.status.setText("正在分析。可以关闭或撤回授权；原来的提醒继续按规则运行。")
        thread.start()

    @Slot(object, str)
    def _received(self, advice, error):
        if self._discard or not self.service.enabled or not self.isVisible():
            return
        if self.context is None or not self.service.is_current(self.context):
            self.status.setText("任务、模式或设置已改变，已丢弃本次结果；请重新预览。")
            self.advice = None
            return
        self.advice = advice or self.service.fallback(self.context)
        self.result.setPlainText(self.advice.text())
        self.details.setCurrentIndex(0)
        self.status.setText(error or "分析完成。你可以保持原设置，或明确确认采用建议间隔。")

    @Slot()
    def _thread_done(self):
        self._thread = self._worker = None
        for widget in (self.provider, self.task, self.comfort, self.prepare_button):
            widget.setEnabled(True)
        self.send_button.setEnabled(False)  # A retry requires a fresh preview.
        self._request = None
        self.apply_button.setEnabled(bool(not self._discard and self.service.enabled and self.advice
                                           and self.advice.interval_minutes is not None
                                           and self.context and self.service.is_current(self.context)))

    def apply_advice(self):
        if self.advice is None or self.context is None:
            return
        minutes = self.advice.interval_minutes
        answer = QMessageBox.question(
            self, "修改提醒间隔？", f"将提醒间隔改为 {minutes} 分钟？这是产品设置，不是医学建议。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.service.apply(self.advice, self.context, confirmed=True)
        except AdviceError as exc:
            self.status.setText(str(exc))
            self.apply_button.setEnabled(False)
            return
        except Exception:
            self.status.setText("设置没有完整保存，请核对当前提醒间隔后重试。")
            return
        self.interval_applied.emit(minutes)
        self.refresh_context()
        actual = self.service.coordinator.policy.config.break_candidate_minutes
        self.status.setText(f"已保存：当前提醒间隔为 {actual} 分钟。设置页已同步；仍会在方便的间隙择机提醒。")

    def reject(self):
        self._discard = True
        self._request = None
        self.context = self.advice = None
        self.context_summary.clear()
        self.preview.clear()
        self.result.clear()
        super().reject()
