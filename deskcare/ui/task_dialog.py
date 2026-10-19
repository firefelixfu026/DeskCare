"""Small M2 dialogs for task forms and draft confirmation."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date, datetime

from PySide6.QtCore import QObject, QThread, Qt, Signal, Slot
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from deskcare.domain.types import Task, TaskDraft
from deskcare.importers.base import ImportResult, duplicate_issues, validate_title
from deskcare.ui.theme import STYLE


class _TaskAIWorker(QObject):
    """Run one user-requested local model parse outside the GUI thread."""

    finished = Signal(int, object, str)

    def __init__(self, generation: int, parser: Callable[[], ImportResult]) -> None:
        super().__init__()
        self.generation = generation
        self.parser = parser

    @Slot()
    def run(self) -> None:
        try:
            result = self.parser()
        except Exception as exc:
            from deskcare.ai.cloud_task_assistant import CloudAIError
            if isinstance(exc, CloudAIError):
                self.finished.emit(self.generation, None, str(exc))
                return
            self.finished.emit(
                self.generation,
                None,
                "本机模型没有返回可用结果；已保留规则解析草稿。",
            )
            return
        self.finished.emit(self.generation, result, "")


def _parse_due(value: str) -> tuple[datetime | None, str | None]:
    value = value.strip()
    if not value:
        return None, None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")), None
    except ValueError:
        return None, f"请输入日期和时间，例如 {date.today():%Y-%m-%d} 18:00，或留空。"


class TaskFormDialog(QDialog):
    def __init__(self, parent=None, task: Task | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(STYLE)
        self.setWindowTitle("编辑任务" if task else "添加任务")
        self.setMinimumWidth(460)
        self.title_edit = QLineEdit(task.title if task else "")
        self.title_edit.setPlaceholderText("例如：完成编程练习")
        self.due_edit = QLineEdit(task.due_at.isoformat(timespec="minutes") if task and task.due_at else "")
        self.due_edit.setPlaceholderText(f"可选：{date.today():%Y-%m-%d} 18:00")
        self.estimate = QSpinBox()
        self.estimate.setRange(0, 1440)
        self.estimate.setSpecialValueText("未设置")
        self.estimate.setValue(task.estimated_minutes or 0 if task else 0)
        form = QFormLayout()
        form.addRow("标题", self.title_edit)
        form.addRow("截止时间", self.due_edit)
        form.addRow("预计用时（分钟）", self.estimate)
        self.error = QLabel()
        self.error.setWordWrap(True)
        self.error.setStyleSheet("color: #B44A42;")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("保存" if task else "添加")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("secondaryButton")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 20)
        root.setSpacing(18)
        root.addLayout(form)
        root.addWidget(self.error)
        root.addWidget(buttons)

    def _accept(self) -> None:
        title = " ".join(self.title_edit.text().split())
        issue = validate_title(title)
        due, due_error = _parse_due(self.due_edit.text())
        if issue or due_error:
            self.error.setText(issue.message if issue else due_error or "输入有误。")
            return
        self.accept()

    def values(self) -> tuple[str, datetime | None, int | None]:
        due, _ = _parse_due(self.due_edit.text())
        minutes = self.estimate.value() or None
        return " ".join(self.title_edit.text().split()), due, minutes


class ImportPreviewDialog(QDialog):
    """Editable draft preview; the dialog never writes to the database."""

    def __init__(self, result: ImportResult, parent=None, ai_parser: Callable[[], ImportResult] | None = None,
                 cloud_request_factory: Callable[[], object] | None = None,
                 cloud_parser: Callable[[object], ImportResult] | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(STYLE)
        self.import_result = result
        self._ai_parser = ai_parser
        self._cloud_request_factory = cloud_request_factory
        self._cloud_parser = cloud_parser
        self._ai_generation = 0
        self._ai_thread: QThread | None = None
        self._ai_worker: _TaskAIWorker | None = None
        self.setWindowTitle(f"预览导入：{result.source_name}")
        self.setMinimumSize(820, 520)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["任务（可编辑）", "截止时间（可编辑）", "预计用时", "备注"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        for draft in result.drafts:
            self._append_draft(draft)
        self.issue_label = QLabel()
        self.issue_label.setWordWrap(True)
        self.issue_label.setStyleSheet("color: #8A5A16; background: #F8EEDC; padding: 8px;")
        self._show_issues(result.issues)
        self.table.itemChanged.connect(lambda _item: self._refresh_validation())
        remove = QPushButton("移除选中项")
        remove.clicked.connect(self._remove_selected)
        self.ai_button = QPushButton("本机 AI 帮我整理")
        self.ai_button.setEnabled(ai_parser is not None)
        self.ai_button.setToolTip(
            "只把本次主动选择的文件发送到本机回环地址；结果仍需编辑并确认。"
            if ai_parser is not None
            else "请先在“设置与隐私”中单独开启本地 AI。"
        )
        if ai_parser is not None:
            self.ai_button.clicked.connect(self._start_ai)
        self.cloud_button = QPushButton("联网 AI 帮我整理")
        self.cloud_button.setEnabled(cloud_request_factory is not None and cloud_parser is not None)
        self.cloud_button.setToolTip("发送前会展示任务清单和服务商；只有你确认后才会发送。")
        if self.cloud_button.isEnabled():
            self.cloud_button.clicked.connect(self._start_cloud)
        self.confirm = QPushButton("确认导入")
        self.confirm.clicked.connect(self._accept)
        cancel = QPushButton("取消")
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addWidget(remove)
        buttons.addWidget(self.ai_button)
        buttons.addWidget(self.cloud_button)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.confirm)
        root = QVBoxLayout(self)
        root.addWidget(QLabel("下面是待确认的任务草稿。你可以修改或删除；点击“确认导入”后才会保存。"))
        root.addWidget(self.issue_label)
        root.addWidget(self.table)
        root.addLayout(buttons)
        self._refresh_validation()

    def _start_cloud(self) -> None:
        if self._cloud_request_factory is None or self._cloud_parser is None or self._ai_thread is not None:
            return
        try:
            request = self._cloud_request_factory()
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "无法准备云端请求", str(exc))
            return
        if request is None:
            return
        preview = QDialog(self)
        preview.setWindowTitle("发送前确认 — 联网 AI")
        preview.setMinimumSize(700, 520)
        layout = QVBoxLayout(preview)
        notice = QLabel(
            f"将发送给：{request.endpoint}\n模型：{request.model}\n"
            "下面只显示你刚选择的清单内容。确认后，这些文字会离开本机并交由该服务处理；可能产生费用。"
            "电脑使用统计和状态打卡不会发送，服务密钥也不会包含在请求内容中。"
        )
        notice.setWordWrap(True)
        layout.addWidget(notice)
        selected_text = QPlainTextEdit()
        selected_text.setReadOnly(True)
        selected_text.setPlainText(request.user_text)
        layout.addWidget(selected_text, 1)
        details_toggle = QPushButton("查看完整请求详情（高级）")
        details_toggle.setCheckable(True)
        layout.addWidget(details_toggle)
        request_details = QPlainTextEdit()
        request_details.setReadOnly(True)
        request_details.setPlainText(request.preview())
        request_details.setVisible(False)
        details_toggle.toggled.connect(request_details.setVisible)
        layout.addWidget(request_details, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("确认发送")
        buttons.accepted.connect(preview.accept)
        buttons.rejected.connect(preview.reject)
        layout.addWidget(buttons)
        if preview.exec() != QDialog.DialogCode.Accepted:
            return
        self._start_parser(lambda: self._cloud_parser(request), "正在请联网 AI 整理…",
                           "已发送你刚刚确认的任务清单；原有草稿仍保留。")

    def _start_ai(self) -> None:
        if self._ai_parser is None or self._ai_thread is not None:
            return
        self._start_parser(self._ai_parser, "正在请本机 AI 整理…",
                           "正在使用这台电脑上的 AI；窗口仍可操作，原有草稿会保留。")

    def _start_parser(self, parser: Callable[[], ImportResult], busy_text: str, status: str) -> None:
        self._ai_generation += 1
        generation = self._ai_generation
        thread = QThread(self)
        worker = _TaskAIWorker(generation, parser)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_ai_finished)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_ai_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._ai_thread = thread
        self._ai_worker = worker
        self.ai_button.setEnabled(False)
        self.cloud_button.setEnabled(False)
        self.ai_button.setText(busy_text)
        self.issue_label.setText(status)
        thread.start()

    @Slot(int, object, str)
    def _on_ai_finished(self, generation: int, result: object, error: str) -> None:
        if generation != self._ai_generation:
            return
        if error or not isinstance(result, ImportResult):
            self._refresh_validation()
            message = error or "AI 暂时没有给出可用结果；已保留原有草稿。"
            self.issue_label.setText(f"{message} 当前规则草稿仍可编辑或确认。")
            return
        self.import_result = result
        self.table.setRowCount(0)
        for draft in result.drafts:
            self._append_draft(draft)
        self._show_issues(result.issues)
        self._refresh_validation()

    @Slot()
    def _on_ai_thread_finished(self) -> None:
        self._ai_thread = None
        self._ai_worker = None
        self.ai_button.setText("本机 AI 帮我整理")
        self.ai_button.setEnabled(self._ai_parser is not None)
        self.cloud_button.setEnabled(self._cloud_request_factory is not None and self._cloud_parser is not None)

    def reject(self) -> None:
        # A timed-out local request cannot be force-killed safely. Let its
        # short-lived worker finish, but discard any result after the dialog
        # has been cancelled or closed.
        self._ai_generation += 1
        super().reject()

    def _append_draft(self, draft: TaskDraft) -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(draft.title))
        self.table.setItem(row, 1, QTableWidgetItem(draft.due_at.isoformat(timespec="minutes") if draft.due_at else ""))
        self.table.setItem(row, 2, QTableWidgetItem(str(draft.estimated_minutes or "")))
        notes = ", ".join(draft.uncertainty) or "规则解析；请核对"
        self.table.setItem(row, 3, QTableWidgetItem(notes))
        self.table.item(row, 3).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)

    def _show_issues(self, issues) -> None:
        if not issues:
            self.issue_label.setText("未发现格式问题。导入器不会保存原文件内容。")
            return
        messages = [f"第 {issue.row} 行：{issue.message}" if issue.row else issue.message for issue in issues]
        self.issue_label.setText("；".join(messages))

    def _remove_selected(self) -> None:
        rows = sorted({index.row() for index in self.table.selectionModel().selectedRows()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)
        self._refresh_validation()

    def _drafts_from_table(self) -> tuple[list[TaskDraft], list[str]]:
        drafts: list[TaskDraft] = []
        errors: list[str] = []

        def cell_text(row: int, column: int) -> str:
            item = self.table.item(row, column)
            return item.text() if item is not None else ""

        for row in range(self.table.rowCount()):
            # Qt emits itemChanged while an importer is still filling the
            # remaining columns. Treat those transiently absent cells as empty
            # user input instead of raising inside the signal callback.
            title = cell_text(row, 0).strip()
            title_issue = validate_title(title, row + 1)
            due, due_error = _parse_due(cell_text(row, 1))
            raw_minutes = cell_text(row, 2).strip()
            minutes = None
            if raw_minutes:
                try:
                    minutes = int(raw_minutes)
                    if not 1 <= minutes <= 1440:
                        raise ValueError
                except ValueError:
                    errors.append(f"第 {row + 1} 行预计分钟无效")
            if title_issue:
                errors.append(title_issue.message)
            if due_error:
                errors.append(due_error)
            if not title:
                continue
            if title_issue or due_error or (raw_minutes and minutes is None):
                continue
            notes = tuple(
                note for note in cell_text(row, 3).split(", ") if note and note != "规则解析；请核对"
            )
            drafts.append(TaskDraft(title, due, minutes, row + 1, notes))
        errors.extend(issue.message for issue in duplicate_issues(drafts))
        return drafts, errors

    def _refresh_validation(self) -> None:
        _, row_errors = self._drafts_from_table()
        blocking_original = [
            issue.message
            for issue in self.import_result.issues
            if issue.fatal and issue.code != "duplicate_title"
        ]
        errors = blocking_original + row_errors
        self.confirm.setEnabled(bool(self.table.rowCount()) and not errors)
        if errors:
            self.issue_label.setText("；".join(errors))
        else:
            self.issue_label.setText("当前草稿可确认导入；确认前不会写入任务库。")

    def _accept(self) -> None:
        drafts, errors = self._drafts_from_table()
        if errors or not drafts:
            self.issue_label.setText("；".join(errors) or "至少保留一项有效任务。")
            return
        self._drafts = drafts
        self._ai_generation += 1
        self.accept()

    @property
    def drafts(self) -> tuple[TaskDraft, ...]:
        return tuple(getattr(self, "_drafts", ()))
