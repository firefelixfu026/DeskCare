"""Optional, local-only event journal. Nothing here calls an AI service."""

from datetime import date, datetime, timedelta
from pathlib import Path
import sqlite3

from PySide6.QtCore import QEvent, Qt, Signal, QTimer
from PySide6.QtGui import QIntValidator, QTextBlockFormat, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox,
    QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from deskcare.domain.health_journal import CHANGE_LABELS, SEVERITY_LABELS
from deskcare.domain.types import TaskDraft
from deskcare.ui.pagination import Pagination
from deskcare.ui.choices import SoftComboBox
from deskcare.ui.task_dialog import TaskFormDialog
from deskcare.ui.theme import STYLE
from deskcare.ui.report_preview import ReportPreview


def text_label(text, name="mutedText"):
    label = QLabel(text)
    label.setObjectName(name)
    label.setWordWrap(True)
    return label


class JournalEntryDialog(QDialog):
    def __init__(self, now, event=None, parent=None):
        super().__init__(parent)
        self.setStyleSheet(STYLE)
        self.setWindowTitle("编辑不适记录" if event else "记一下不适")
        self.setMinimumWidth(490)
        self.when_edit = QLineEdit((event.occurred_at if event else now).strftime("%Y-%m-%d %H:%M"))
        self.when_edit.setPlaceholderText("YYYY-MM-DD HH:mm")
        self.area_edit = QLineEdit(event.body_area if event else "")
        self.area_edit.setMaxLength(80)
        self.area_edit.setPlaceholderText("可留空，例如眼睛、肩颈")
        self.description_edit = QLineEdit(event.description if event else "")
        self.description_edit.setMaxLength(500)
        self.description_edit.setPlaceholderText("用自己的话记下这次感受")
        self.severity_edit = SoftComboBox()
        for value, label in SEVERITY_LABELS.items():
            self.severity_edit.addItem(label, value)
        self.severity_edit.setCurrentIndex(self.severity_edit.findData(event.severity if event else None))
        self.duration_edit = QLineEdit(str(event.duration_minutes) if event and event.duration_minutes is not None else "")
        self.duration_edit.setValidator(QIntValidator(0, 10080, self))
        self.duration_edit.setPlaceholderText("可留空，0 表示刚开始")
        self.notes_edit = QPlainTextEdit(event.notes if event else "")
        self.notes_edit.setMaximumHeight(90)
        self.notes_edit.setPlaceholderText("可留空；只保存你填写的文字")
        form = QFormLayout()
        form.setSpacing(12)
        for label, widget in (("发生时间", self.when_edit), ("部位（可选）", self.area_edit),
                              ("这次的感受", self.description_edit), ("自报程度（可选）", self.severity_edit),
                              ("持续分钟（可选）", self.duration_edit), ("备注（可选）", self.notes_edit)):
            form.addRow(label, widget)
        self.error = text_label("")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存记录")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("不记录")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("secondaryButton")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)
        root.addWidget(text_label("这是你的自我记录，不是症状识别或医学评估。"))
        root.addLayout(form)
        root.addWidget(self.error)
        root.addWidget(buttons)

    def values(self):
        if not self.description_edit.text().strip():
            raise ValueError("写一句自己的感受即可；不想记录可以取消。")
        try:
            when = datetime.fromisoformat(self.when_edit.text().strip())
            minutes = int(self.duration_edit.text()) if self.duration_edit.text().strip() else None
        except ValueError:
            raise ValueError("请核对日期时间和持续分钟。") from None
        return dict(occurred_at=when, body_area=self.area_edit.text(), description=self.description_edit.text(),
                    severity=self.severity_edit.currentData(), duration_minutes=minutes, notes=self.notes_edit.toPlainText())

    def _accept(self):
        try:
            self.values()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class JournalFollowupDialog(QDialog):
    def __init__(self, now, parent=None):
        super().__init__(parent)
        self.setStyleSheet(STYLE)
        self.setWindowTitle("补记后来的感受")
        self.setMinimumWidth(460)
        self.when_edit = QLineEdit(now.strftime("%Y-%m-%d %H:%M"))
        self.change_edit = SoftComboBox()
        self.change_edit.addItem("请选择，也可以取消不记", None)
        for value, label in CHANGE_LABELS.items():
            self.change_edit.addItem(label, value)
        self.note_edit = QPlainTextEdit()
        self.note_edit.setMaximumHeight(110)
        self.note_edit.setPlaceholderText("可选：后来做了什么，或还有什么想记的")
        self.error = text_label("")
        form = QFormLayout()
        form.setSpacing(12)
        form.addRow("补记时间", self.when_edit)
        form.addRow("自己的感受", self.change_edit)
        form.addRow("备注（可选）", self.note_edit)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存补记")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("暂不记录")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setObjectName("secondaryButton")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 22, 24, 20)
        root.setSpacing(16)
        root.addLayout(form)
        root.addWidget(self.error)
        root.addWidget(buttons)

    def values(self):
        if self.change_edit.currentData() is None:
            raise ValueError("请选择自己的感受；不想补记可直接取消。")
        try:
            when = datetime.fromisoformat(self.when_edit.text().strip())
        except ValueError:
            raise ValueError("请核对补记日期和时间。") from None
        return dict(recorded_at=when, change=self.change_edit.currentData(), note=self.note_edit.toPlainText())

    def _accept(self):
        try:
            self.values()
        except ValueError as exc:
            self.error.setText(str(exc))
            return
        self.accept()


class JournalReviewDialog(QDialog):
    def __init__(self, service, event_id, parent=None):
        super().__init__(parent)
        self.setStyleSheet(STYLE)
        self.service, self.event_id = service, event_id
        self.setWindowTitle("这次记录与后续")
        self.resize(620, 620)
        self.review_text = ReportPreview()
        self.review_text.setAccessibleName("本人记录与后续回顾，未调用 AI")
        self.followups = QListWidget()
        self.followups.setMaximumHeight(110)
        self.delete_button = QPushButton("删除选中的补记")
        self.delete_button.setObjectName("secondaryButton")
        self.delete_button.clicked.connect(self._delete_followup)
        close = QPushButton("关闭")
        close.clicked.connect(self.accept)
        root = QVBoxLayout(self)
        root.addWidget(self.review_text, 1)
        root.addWidget(text_label("补记填错时，可删除后重新填写。"))
        root.addWidget(self.followups)
        actions = QHBoxLayout()
        actions.addWidget(self.delete_button)
        actions.addStretch()
        actions.addWidget(close)
        root.addLayout(actions)
        self.refresh()

    def refresh(self):
        try:
            content = self.service.review(self.event_id)
            rows = self.service.repository.followups(self.event_id)
        except (KeyError, PermissionError):
            self.review_text.clear()
            self.followups.clear()
            self.reject()
            return
        self.review_text.setPlainText(content)
        cursor = QTextCursor(self.review_text.document())
        cursor.select(QTextCursor.SelectionType.Document)
        fmt = QTextBlockFormat()
        fmt.setLineHeight(145, QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        fmt.setBottomMargin(5)
        cursor.mergeBlockFormat(fmt)
        self.followups.clear()
        for entry in rows:
            item = QListWidgetItem(f"{entry.recorded_at:%m/%d %H:%M} · {CHANGE_LABELS[entry.change]}" +
                                   (" · " + entry.note[:40].replace("\n", " ") if entry.note else ""))
            item.setToolTip(entry.note)
            item.setData(Qt.ItemDataRole.UserRole, entry.id)
            self.followups.addItem(item)
        self.delete_button.setEnabled(bool(rows))

    def _delete_followup(self):
        item = self.followups.currentItem()
        if item and QMessageBox.question(self, "删除补记", f"删除“{item.text()}”？只删除这次补记，保留原记录和行动任务。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            try:
                self.service.delete_followup(self.event_id, item.data(Qt.ItemDataRole.UserRole))
            except (sqlite3.Error, KeyError, PermissionError):
                QMessageBox.warning(self, "未能删除", "请核对记录状态和本机存储权限。")
            self.refresh()


class HealthJournalPage(QWidget):
    task_created = Signal(object)

    def __init__(self, service=None, parent=None):
        super().__init__(parent)
        self.service = service
        self._events = []
        self._page_size = 5
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 4, 0, 0)
        root.setSpacing(12)
        permission_row = QHBoxLayout()
        self.consent = QCheckBox("开启本机不适记录")
        self.consent.setObjectName("aiConsent")
        self.consent.setEnabled(service is not None)
        self.consent.toggled.connect(self._toggle_consent)
        permission_row.addWidget(self.consent)
        permission_row.addStretch()
        self.clear_button = QPushButton("清空记录")
        self.clear_button.setObjectName("secondaryButton")
        self.clear_button.clicked.connect(self._clear)
        permission_row.addWidget(self.clear_button)
        root.addLayout(permission_row)
        self.privacy = text_label("独立开启后才保存，不发送给 AI；关闭会删除记录及补记。")
        root.addWidget(self.privacy)
        toolbar = QHBoxLayout()
        self.period = SoftComboBox()
        self.period.addItems(["近 7 天", "近 30 天", "全部记录"])
        self.period.currentIndexChanged.connect(self._change_period)
        toolbar.addWidget(self.period)
        toolbar.addStretch()
        self.export_button = QPushButton("导出选中")
        self.export_button.setObjectName("secondaryButton")
        self.export_button.clicked.connect(self._export)
        toolbar.addWidget(self.export_button)
        self.add_button = QPushButton("记一下不适")
        self.add_button.clicked.connect(self._record)
        toolbar.addWidget(self.add_button)
        root.addLayout(toolbar)
        frame = QFrame()
        frame.setObjectName("card")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 12, 16, 14)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["发生时间", "自己的记录", "自报程度", "后续补记"])
        self.table.verticalHeader().hide()
        self.table.verticalHeader().setDefaultSectionSize(52)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, width in ((0, 145), (2, 90), (3, 90)):
            self.table.setColumnWidth(col, width)
        self.table.setMinimumHeight(140)
        self.table.setWordWrap(False)
        self.table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.viewport().installEventFilter(self)
        self.table.itemSelectionChanged.connect(self._sync_selection)
        self.table.itemDoubleClicked.connect(lambda _item: self._review())
        layout.addWidget(self.table, 1)
        self.empty = text_label("还没有记录。不想记也没关系。")
        layout.addWidget(self.empty)
        self.pager = Pagination()
        self.pager.changed.connect(lambda _index: self.refresh())
        layout.addWidget(self.pager)
        root.addWidget(frame, 1)
        actions = QHBoxLayout()
        self.view_button = QPushButton("查看回顾")
        self.edit_button = QPushButton("编辑记录")
        self.followup_button = QPushButton("补记感受")
        self.action_button = QPushButton("加入行动任务")
        self.delete_button = QPushButton("删除记录")
        for button, callback in ((self.view_button, self._review), (self.edit_button, self._edit),
                                 (self.followup_button, self._followup), (self.action_button, self._action),
                                 (self.delete_button, self._delete)):
            button.setObjectName("secondaryButton")
            button.clicked.connect(callback)
            actions.addWidget(button)
        actions.addStretch()
        root.addLayout(actions)
        root.addWidget(text_label("记录不能替代就医；紧急健康问题请直接寻求医疗帮助，不要等待软件回复。"))
        if service:
            service.subscribe(self.refresh)
            if service.task_service:
                service.task_service.subscribe(self.refresh)
        self.refresh()

    def _selected(self):
        row = self.table.currentRow()
        return self._events[row] if 0 <= row < len(self._events) else None

    def _sync_selection(self):
        selected = self._selected() is not None and bool(self.service and self.service.enabled)
        for button in (self.view_button, self.edit_button, self.followup_button, self.action_button, self.delete_button, self.export_button):
            button.setEnabled(selected)

    def refresh(self):
        selected = self._selected()
        enabled = bool(self.service and self.service.enabled)
        self.consent.blockSignals(True)
        self.consent.setChecked(enabled)
        self.consent.blockSignals(False)
        self.add_button.setEnabled(enabled)
        self.clear_button.setEnabled(enabled)
        start = None if self.period.currentIndex() == 2 else date.today() - timedelta(days=6 if self.period.currentIndex() == 0 else 29)
        rows = self.service.events(start) if enabled else []
        self.pager.update_total(len(rows), self._page_size)
        self._events = rows[self.pager.index*self._page_size:self.pager.index*self._page_size+self._page_size]
        self.table.setRowCount(0)
        for row, entry in enumerate(self._events):
            self.table.insertRow(row)
            for col, value in enumerate((entry.occurred_at.strftime("%m/%d %H:%M"), entry.description,
                                        SEVERITY_LABELS[entry.severity], f"{entry.followup_count} 次" if entry.followup_count else "未补记")):
                item = QTableWidgetItem(value)
                self.table.setItem(row, col, item)
            if selected and selected.id == entry.id:
                self.table.setCurrentCell(row, 1)
        if self._events and self.table.currentRow() < 0:
            self.table.setCurrentCell(0, 1)
        self.empty.setVisible(not self._events)
        self.empty.setText("这个时段还没有记录。" if enabled else "不适记录尚未开启，与每日打卡分开授权。")
        self._sync_selection()

    def eventFilter(self, watched, event):
        if watched is self.table.viewport() and event.type() == QEvent.Type.Resize:
            QTimer.singleShot(0, self._fit_page)
        return super().eventFilter(watched, event)

    def _fit_page(self):
        if not hasattr(self, "pager"):
            return
        size = max(1, self.table.viewport().height() // 52)
        if size != self._page_size:
            absolute = self.pager.index * self._page_size + max(0, self.table.currentRow())
            self._page_size = size
            self.pager.index = absolute // size
            self.refresh()

    def _show_event(self, entry):
        if entry is None:
            return
        if self.period.currentIndex() != 2 and entry.occurred_at.date() < date.today() - timedelta(days=6 if self.period.currentIndex() == 0 else 29):
            self.period.setCurrentIndex(2)
        start = None if self.period.currentIndex() == 2 else date.today() - timedelta(days=6 if self.period.currentIndex() == 0 else 29)
        rows = self.service.events(start)
        index = next((i for i, item in enumerate(rows) if item.id == entry.id), None)
        if index is not None:
            self.pager.index = index // self._page_size
            self.refresh()
            self.table.setCurrentCell(index % self._page_size, 1)

    def _change_period(self, _index):
        self.pager.index = 0
        self.refresh()

    def _toggle_consent(self, enabled):
        message = ("只在本机保存你主动填写的不适描述、程度和补记，不发送给任何 AI。"
                   "本地数据库不加密，请注意设备访问权限。关闭此项会删除这些记录，但不删除已确认的任务。是否开启？" if enabled else
                   "关闭后会删除所有不适记录、补记及关联关系。已加入任务的行动仍保留，可在任务页删除。是否关闭？")
        if QMessageBox.question(self, "不适记录授权", message,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            try:
                self.service.set_enabled(enabled)
            except sqlite3.Error:
                QMessageBox.warning(self, "授权状态未更新", "请检查本机存储权限或空间，再核对开关状态。")
        self.refresh()

    def _run_form(self, dialog, operation):
        try:
            while dialog.exec() == QDialog.DialogCode.Accepted:
                try:
                    return operation(dialog.values())
                except ValueError as exc:
                    QMessageBox.warning(self, "请核对记录", str(exc))
                except (KeyError, PermissionError) as exc:
                    QMessageBox.warning(self, "没有保存", str(exc))
                    break
                except sqlite3.Error:
                    QMessageBox.warning(self, "没有保存", "请检查本机存储权限或空间；填写内容仍保留在当前表单。")
        finally:
            dialog.deleteLater()

    def _record(self):
        if self.service and self.service.enabled:
            self._show_event(self._run_form(JournalEntryDialog(self.service.now(), parent=self), lambda values: self.service.save(**values)))

    def _edit(self):
        entry = self._selected()
        if entry:
            self._show_event(self._run_form(JournalEntryDialog(self.service.now(), entry, self),
                           lambda values: self.service.save(event_id=entry.id, **values)))

    def _followup(self):
        entry = self._selected()
        if entry:
            self._run_form(JournalFollowupDialog(self.service.now(), self),
                           lambda values: self.service.followup(entry.id, **values))

    def _review(self):
        entry = self._selected()
        if entry:
            dialog = JournalReviewDialog(self.service, entry.id, self)
            self.service.subscribe(dialog.refresh)
            try:
                dialog.exec()
            finally:
                self.service.unsubscribe(dialog.refresh)
                dialog.review_text.clear()
                dialog.deleteLater()

    def _action(self):
        entry = self._selected()
        if not entry:
            return
        dialog = TaskFormDialog(self)
        dialog.setWindowTitle("确认行动安排")
        dialog.title_edit.setText("给自己留一点调整时间")
        dialog.layout().insertWidget(0, text_label("只把你确认的行动写入任务，不复制不适描述；这不是治疗建议。"))
        try:
            if dialog.exec() == QDialog.DialogCode.Accepted:
                title, due, minutes = dialog.values()
                task = self.service.add_action(entry.id, TaskDraft(title, due, minutes, **dialog.details()), confirmed=True)
                self.task_created.emit(task)
        except (ValueError, KeyError, PermissionError) as exc:
            QMessageBox.warning(self, "没有加入任务", str(exc))
        except sqlite3.Error:
            QMessageBox.warning(self, "未能加入任务", "请检查本机存储权限或空间，并核对任务列表。")
        finally:
            dialog.deleteLater()

    def _delete(self):
        entry = self._selected()
        if entry and QMessageBox.question(self, "删除这次记录", "同时删除这条记录的补记及关联关系；已加入任务的行动保留。无法撤销。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._change_records(lambda: self.service.delete(entry.id))

    def _clear(self):
        if QMessageBox.question(self, "清空不适记录", "删除全部不适记录及补记，保留开关与已确认的任务。无法撤销。",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes:
            self._change_records(self.service.clear)

    def _change_records(self, operation):
        try:
            operation()
        except (sqlite3.Error, KeyError, PermissionError):
            QMessageBox.warning(self, "操作未完成", "请核对记录状态和本机存储权限或空间。")

    def _export(self):
        entry = self._selected()
        if not entry:
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出这次记录（可能含健康隐私，请妥善保管）", "我的不适记录.txt", "文本 (*.txt)")
        if path:
            try:
                content = self.service.review(entry.id)
                Path(path).write_text(content + "\n", encoding="utf-8")
            except (OSError, KeyError, PermissionError):
                QMessageBox.warning(self, "未能导出", "请确认记录仍存在且目标位置可写。")
