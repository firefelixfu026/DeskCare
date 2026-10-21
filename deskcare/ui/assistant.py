"""Small, plain-language assistant with a real allowlisted tool executor."""
from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QHBoxLayout, QLabel,
    QMessageBox, QPlainTextEdit, QPushButton, QVBoxLayout,
)

from deskcare.services.assistant_service import WELCOME
from deskcare.ui.choices import SoftComboBox
from deskcare.services.reminder_advice import AdviceError


class _AssistantWorker(QObject):
    finished = Signal(object, str)

    def __init__(self, service, request):
        super().__init__()
        self.service, self.request = service, request

    @Slot()
    def run(self):
        try:
            self.finished.emit(self.service.analyze(self.request, confirmed=True), "")
        except AdviceError as exc:
            self.finished.emit(None, str(exc))
        except Exception:
            self.finished.emit(None, "这次没有得到可用的操作建议，原有任务和设置不变。")


class AssistantDialog(QDialog):
    open_view_requested = Signal(str)

    def __init__(self, service, parent=None):
        super().__init__(parent)
        self.service = service
        self._thread = self._worker = self._pending = None
        self._discard = False
        self.setWindowTitle("DeskCare 助手")
        self.resize(760, 640)
        self.setMinimumSize(620, 520)
        root = QVBoxLayout(self)
        root.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("有什么我能帮你安排的？")
        title.setObjectName("cardTitle")
        header.addWidget(title, 1)
        self.provider = SoftComboBox()
        self.provider.addItem("本机 AI", "local")
        self.provider.addItem("联网 AI", "cloud")
        if not service.gateway.local_ai or not service.gateway.local_ai.enabled:
            self.provider.setCurrentIndex(1)
        self.provider.currentIndexChanged.connect(self._invalidate_pending)
        header.addWidget(self.provider)
        root.addLayout(header)
        self.consent = QCheckBox("允许用 AI 理解我主动发送的消息（单独授权）")
        self.consent.setObjectName("aiConsent")
        self.consent.setChecked(service.enabled)
        self.consent.toggled.connect(self._consent_changed)
        root.addWidget(self.consent)
        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setMaximumBlockCount(500)
        self.transcript.setPlainText("DeskCare\n" + WELCOME)
        root.addWidget(self.transcript, 1)
        self.proposal = QLabel()
        self.proposal.setWordWrap(True)
        self.proposal.setTextFormat(Qt.TextFormat.PlainText)
        root.addWidget(self.proposal)
        pending_actions = QHBoxLayout()
        self.confirm = QPushButton("确认执行")
        self.confirm.setEnabled(False)
        self.confirm.hide()
        self.confirm.clicked.connect(self.execute_pending)
        pending_actions.addWidget(self.confirm)
        self.cancel_action = QPushButton("取消这项操作")
        self.cancel_action.setObjectName("secondaryButton")
        self.cancel_action.setEnabled(False)
        self.cancel_action.hide()
        self.cancel_action.clicked.connect(self._invalidate_pending)
        pending_actions.addWidget(self.cancel_action)
        pending_actions.addStretch()
        root.addLayout(pending_actions)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText("例如：把提醒改成 40 分钟。不要输入 API Key 或详细病历。")
        self.input.setFixedHeight(76)
        self.input.textChanged.connect(self._invalidate_pending)
        root.addWidget(self.input)
        buttons = QHBoxLayout()
        self.help_button = QPushButton("你能做什么")
        self.help_button.setObjectName("secondaryButton")
        self.help_button.clicked.connect(lambda: self.append(WELCOME))
        buttons.addWidget(self.help_button)
        self.status = QLabel("每次只发送这句话和当前提醒设置；不上传工具读取的结果或对话历史。")
        self.status.setWordWrap(True)
        buttons.addWidget(self.status, 1)
        self.send = QPushButton("发送")
        self.send.clicked.connect(self.send_message)
        buttons.addWidget(self.send)
        root.addLayout(buttons)

    def begin(self):
        self._discard = self._thread is not None
        self.consent.blockSignals(True)
        self.consent.setChecked(self.service.enabled)
        self.consent.blockSignals(False)
        self.show()
        self.raise_()
        self.input.setFocus()

    def append(self, text, who="DeskCare"):
        self.transcript.appendPlainText(f"\n{who}\n{text}")

    def _invalidate_pending(self, *_):
        self._pending = None
        self.confirm.setEnabled(False)
        self.cancel_action.setEnabled(False)
        self.confirm.hide()
        self.cancel_action.hide()
        self.proposal.clear()
        self.service.invalidate()

    def _consent_changed(self, enabled):
        if enabled and QMessageBox.question(
            self, "允许助手理解你的消息？",
            "只有主动发送时才请求模型。每次会先展示你这次的话和当前提醒设置。\n"
            "联网时这些信息将离开本机，可能收费或被服务商保留。不要发送密钥或详细健康资料。\n"
            "不会自动发送任务列表、工具结果、健康历史或屏幕；修改和添加还需另行确认。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        ) != QMessageBox.StandardButton.Yes:
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
            self.status.setText("授权没有保存，请重试。")
            return
        self._invalidate_pending()
        if not enabled:
            self._discard = True
        self.status.setText("已开启；每次发送前仍会展示本次信息。" if enabled else "已撤回，不再发送；进行中的结果不采用，已发送内容无法撤回。")

    def confirm_send(self, request):
        preview = QDialog(self)
        preview.setWindowTitle("核对本次发送")
        preview.resize(640, 470)
        root = QVBoxLayout(preview)
        target = QLabel(f"服务：{request.endpoint}\n模型：{request.model}")
        target.setTextFormat(Qt.TextFormat.PlainText)
        target.setWordWrap(True)
        root.addWidget(target)
        contents = QPlainTextEdit()
        contents.setReadOnly(True)
        contents.setPlainText(request.human_preview())
        root.addWidget(contents, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认发送")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(preview.accept)
        buttons.rejected.connect(preview.reject)
        root.addWidget(buttons)
        return preview.exec() == QDialog.DialogCode.Accepted

    def send_message(self):
        if self._thread is not None:
            return
        if not self.service.enabled:
            self.status.setText("请先开启上方的助手授权；还没有发送消息。")
            return
        try:
            request = self.service.prepare(self.input.toPlainText(), self.provider.currentData())
        except AdviceError as exc:
            self.status.setText(str(exc))
            return
        self._pending = None
        self.confirm.setEnabled(False)
        self.cancel_action.setEnabled(False)
        self.confirm.hide()
        self.cancel_action.hide()
        self.proposal.clear()
        if not self.confirm_send(request):
            self.status.setText("已取消，没有发送。")
            return
        self.append(request.message, "你")
        self._discard = False
        thread = QThread(self)
        worker = _AssistantWorker(self.service, request)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._received)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._finished)
        thread.finished.connect(thread.deleteLater)
        self._thread, self._worker = thread, worker
        self.input.setEnabled(False)
        self.provider.setEnabled(False)
        self.send.setEnabled(False)
        self.status.setText("正在理解这次需求，还没有执行修改。")
        thread.start()

    @Slot(object, str)
    def _received(self, plan, error):
        if self._discard or not self.service.enabled or not self.isVisible():
            return
        if error or plan is None:
            self.append(error or "这次没有识别成功，请重试。")
            return
        if plan.mutating:
            self._pending = plan
            self.proposal.setText("准备执行，尚未修改：\n" + plan.describe())
            self.confirm.setEnabled(True)
            self.cancel_action.setEnabled(True)
            self.confirm.show()
            self.cancel_action.show()
        else:
            self._execute(plan, confirmed=False)

    def _execute(self, plan, *, confirmed):
        try:
            outcome = self.service.execute(plan, confirmed=confirmed)
        except AdviceError as exc:
            self.append(str(exc))
            return
        except Exception:
            self.append("操作未完成。请核对当前设置或任务后再试；不会自动重试添加。")
            return
        self.append(outcome.text)
        if outcome.open_view:
            self.open_view_requested.emit(outcome.open_view)

    def execute_pending(self):
        if self._pending is None:
            return
        plan, self._pending = self._pending, None
        self.confirm.setEnabled(False)
        self.cancel_action.setEnabled(False)
        self.confirm.hide()
        self.cancel_action.hide()
        self.proposal.clear()
        self._execute(plan, confirmed=True)

    @Slot()
    def _finished(self):
        self._thread = self._worker = None
        self.input.setEnabled(True)
        self.provider.setEnabled(True)
        self.send.setEnabled(True)
        self.status.setText("有待确认的操作时，核对后点击“确认执行”；也可以取消或重新描述。")

    def reject(self):
        self._discard = True
        self._invalidate_pending()
        self.input.clear()
        self.transcript.setPlainText("DeskCare\n" + WELCOME)
        super().reject()
