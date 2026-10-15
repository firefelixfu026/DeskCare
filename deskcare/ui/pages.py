"""DeskCare pages with the M2 task surface and M1 activity statistics."""

from datetime import date, datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QTableWidget,
    QTableWidgetItem,
    QMessageBox,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from deskcare.domain.types import Task, TaskStatus, WELLNESS_LEVEL_LABELS, WellnessLevel
from deskcare.importers.loader import parse_selected_file
from deskcare.services.bodylog_service import BodyLogService
from deskcare.services.reminder_service import REMINDER_RESPONSES, ReminderSnapshot
from deskcare.services.report_engine import LocalReportService, ReportPeriod
from deskcare.ui.task_dialog import ImportPreviewDialog, TaskFormDialog


ACTIVITY_TIPS = (
    "如果方便，可以站起来走几步；不想活动时也可以直接跳过。",
    "也可以轻轻活动肩颈，动作以舒适为准；感觉不适就停下。",
    "可以按自己的感觉换个姿势，或短暂看看远处。",
)

APP_DISPLAY_NAMES = {
    "code": "Visual Studio Code",
    "chrome": "Google Chrome",
    "msedge": "Microsoft Edge",
    "firefox": "Firefox",
    "brave": "Brave",
    "weixin": "微信",
    "wechat": "微信",
    "bilibili": "哔哩哔哩",
    "qq": "QQ",
    "teams": "Microsoft Teams",
    "winword": "Microsoft Word",
    "excel": "Microsoft Excel",
    "powerpnt": "Microsoft PowerPoint",
    "wps": "WPS Office",
}


def label(text: str, object_name: str = "") -> QLabel:
    widget = QLabel(text)
    widget.setObjectName(object_name)
    widget.setWordWrap(True)
    return widget


def card(title: str, body: str, accent: str = "#2F6B5F") -> QFrame:
    frame = QFrame()
    frame.setObjectName("card")
    frame.setStyleSheet(f"QFrame#card {{ border-left: 4px solid {accent}; }}")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(18, 15, 18, 15)
    layout.setSpacing(6)
    layout.addWidget(label(title, "cardTitle"))
    layout.addWidget(label(body, "cardBody"))
    return frame


class _ReportAIWorker(QObject):
    """Run the optional local report request away from the Qt GUI thread."""

    finished = Signal(str, bool)

    def __init__(self, service, facts, fallback_markdown: str) -> None:
        super().__init__()
        self.service = service
        self.facts = facts
        self.fallback_markdown = fallback_markdown

    def run(self) -> None:
        markdown, used_model = self.service.narrate_facts(self.facts, self.fallback_markdown)
        self.finished.emit(markdown, used_model)


class _LocalModelProbeWorker(QObject):
    """Probe a loopback model service away from the Qt GUI thread."""

    finished = Signal(object, str)

    def __init__(self, service, endpoint: str, model: str) -> None:
        super().__init__()
        self.service = service
        self.endpoint = endpoint
        self.model = model

    def run(self) -> None:
        try:
            models = self.service.probe_models(self.endpoint, self.model)
        except Exception as exc:
            self.finished.emit((), str(exc))
            return
        self.finished.emit(models, "")


class TodayPage(QWidget):
    def __init__(self, controller, task_service=None, reminder_coordinator=None, local_ai_service=None, repository=None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.task_service = task_service
        self.reminder_coordinator = reminder_coordinator
        self.local_ai_service = local_ai_service
        self.repository = repository
        self._tasks: list[Task] = []
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.addWidget(label("把今天放在眼前，按自己的节奏推进。", "pageLead"))

        state_row = QHBoxLayout()
        self.monitoring_badge = label("监测未开启", "statusBadge")
        state_row.addWidget(self.monitoring_badge)
        state_row.addStretch()
        add_button = QPushButton("添加任务")
        add_button.clicked.connect(self._add_manual)
        import_button = QPushButton("导入清单")
        import_button.clicked.connect(self._import_file)
        state_row.addWidget(add_button)
        state_row.addWidget(import_button)
        root.addLayout(state_row)

        context_row = QHBoxLayout()
        context_row.addWidget(label("当前情境", "contextLabel"))
        self.context_mode = QComboBox()
        for value, text in (
            ("normal", "普通工作"),
            ("focus", "专注模式"),
            ("meeting", "会议中"),
            ("reading", "阅读中"),
            ("quiet", "安静时段"),
        ):
            self.context_mode.addItem(text, value)
        self.context_mode.currentIndexChanged.connect(self._mode_changed)
        context_row.addWidget(self.context_mode)
        context_row.addStretch()
        root.addLayout(context_row)

        self.reminder_card = QFrame()
        self.reminder_card.setObjectName("reminderCard")
        reminder_layout = QVBoxLayout(self.reminder_card)
        reminder_layout.setContentsMargins(18, 14, 18, 14)
        reminder_layout.setSpacing(8)
        self.reminder_title = label("可以考虑留一个短暂空档", "reminderTitle")
        self.reminder_body = label("", "reminderBody")
        self.reminder_reason = label("", "reminderReason")
        self.activity_tip = label("", "activityTip")
        reminder_layout.addWidget(self.reminder_title)
        reminder_layout.addWidget(self.reminder_body)
        reminder_layout.addWidget(self.reminder_reason)
        reminder_layout.addWidget(self.activity_tip)
        reminder_actions = QHBoxLayout()
        for response, text in (
            ("BREAK_NOW", "现在休息"),
            ("SNOOZE_10_MIN", "10 分钟后"),
            ("SKIP", "跳过"),
            ("BAD_TIMING", "时机不合适"),
        ):
            button = QPushButton(text)
            button.setObjectName("reminderAction")
            button.clicked.connect(lambda _checked=False, value=response: self._respond_reminder(value))
            reminder_actions.addWidget(button)
        reminder_layout.addLayout(reminder_actions)
        root.addWidget(self.reminder_card)
        self.reminder_card.setVisible(False)

        task_frame = QFrame()
        task_frame.setObjectName("card")
        task_layout = QVBoxLayout(task_frame)
        task_layout.setContentsMargins(18, 15, 18, 15)
        task_layout.addWidget(label("今日任务", "cardTitle"))
        task_layout.addWidget(label("任务只有在你确认后才会保存；完成状态也只能由你主动修改。", "cardBody"))
        self.task_table = QTableWidget(0, 4)
        self.task_table.setHorizontalHeaderLabels(["状态", "任务", "截止时间", "预计分钟"])
        self.task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.task_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.task_table.horizontalHeader().setStretchLastSection(False)
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        task_layout.addWidget(self.task_table)
        self.empty_state = label("还没有已确认的今日任务。可以手工添加，或选择一个 .txt / .md / .csv 清单开始。", "mutedText")
        task_layout.addWidget(self.empty_state)
        actions = QHBoxLayout()
        self.edit_button = QPushButton("编辑选中")
        self.edit_button.clicked.connect(self._edit_selected)
        self.delete_button = QPushButton("删除选中")
        self.delete_button.clicked.connect(self._delete_selected)
        actions.addWidget(self.edit_button)
        actions.addWidget(self.delete_button)
        actions.addStretch()
        task_layout.addLayout(actions)
        root.addWidget(task_frame)
        root.addWidget(card("下一步建议", "当前监测默认关闭。你可以在“设置与隐私”中单独开启使用统计；未开启时，任务页仍可正常使用。", "#7D9FB3"))
        root.addStretch()
        controller.subscribe(self._sync)
        if self.task_service is not None:
            self.task_service.subscribe(self.refresh_tasks)
        if self.reminder_coordinator is not None:
            self.reminder_coordinator.subscribe(self._sync_reminder)
        self.refresh_tasks()
        self._sync(controller.enabled, controller.paused)

    def _selected_task(self) -> Task | None:
        row = self.task_table.currentRow()
        return self._tasks[row] if 0 <= row < len(self._tasks) else None

    def _add_manual(self) -> None:
        if self.task_service is None:
            return
        dialog = TaskFormDialog(self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            title, due, minutes = dialog.values()
            try:
                self.task_service.add_manual(title, due, minutes)
            except ValueError as exc:
                QMessageBox.warning(self, "无法添加任务", str(exc))

    def _edit_selected(self) -> None:
        task = self._selected_task()
        if task is None or self.task_service is None:
            return
        dialog = TaskFormDialog(self, task)
        if dialog.exec() == dialog.DialogCode.Accepted:
            title, due, minutes = dialog.values()
            try:
                self.task_service.update(task.id, title=title, due_at=due, estimated_minutes=minutes)
            except (KeyError, ValueError) as exc:
                QMessageBox.warning(self, "无法编辑任务", str(exc))

    def _delete_selected(self) -> None:
        task = self._selected_task()
        if task is None or self.task_service is None:
            return
        answer = QMessageBox.question(
            self,
            "确认删除任务",
            f"是否删除“{task.title}”？此操作只删除本地已确认任务。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.task_service.delete(task.id)

    def _import_file(self) -> None:
        if self.task_service is None:
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "选择今日任务清单",
            "",
            "任务清单 (*.txt *.md *.csv);;文本文件 (*.txt *.md);;CSV 文件 (*.csv)",
        )
        if not path:
            return
        result = parse_selected_file(path)
        ai_parser = None
        if self.local_ai_service is not None and self.local_ai_service.enabled:
            ai_parser = lambda selected_path=path: self.local_ai_service.parse_path(selected_path)
        dialog = ImportPreviewDialog(result, self, ai_parser=ai_parser)
        if dialog.exec() != dialog.DialogCode.Accepted:
            return
        try:
            self.task_service.confirm_import(dialog.drafts, Path(path).name)
        except ValueError as exc:
            QMessageBox.warning(self, "无法确认导入", str(exc))

    def refresh_tasks(self) -> None:
        if self.task_service is None:
            self._tasks = []
        else:
            self._tasks = list(self.task_service.list_today())
        self.task_table.setRowCount(0)
        self.edit_button.setEnabled(bool(self._tasks))
        self.delete_button.setEnabled(bool(self._tasks))
        self.empty_state.setVisible(not self._tasks)
        for row, task in enumerate(self._tasks):
            self.task_table.insertRow(row)
            status = QComboBox()
            status.addItem("待处理", TaskStatus.TODO)
            status.addItem("进行中", TaskStatus.DOING)
            status.addItem("已完成", TaskStatus.DONE)
            status.setCurrentIndex(status.findData(task.status))
            status.currentIndexChanged.connect(
                lambda _index, task_id=task.id, combo=status: self._set_status(task_id, combo.currentData())
            )
            self.task_table.setCellWidget(row, 0, status)
            self.task_table.setItem(row, 1, QTableWidgetItem(task.title))
            self.task_table.setItem(row, 2, QTableWidgetItem(task.due_at.isoformat(timespec="minutes") if task.due_at else "未设置"))
            self.task_table.setItem(row, 3, QTableWidgetItem(str(task.estimated_minutes or "—")))

    def _set_status(self, task_id: int, status: TaskStatus) -> None:
        if self.task_service is not None:
            try:
                self.task_service.set_status(task_id, status)
                if status is TaskStatus.DONE and self.reminder_coordinator is not None:
                    self.reminder_coordinator.mark_task_completed()
            except KeyError:
                self.refresh_tasks()

    def _mode_changed(self, _index: int) -> None:
        if self.reminder_coordinator is not None:
            self.reminder_coordinator.set_mode(self.context_mode.currentData())
            self.reminder_coordinator.evaluate()

    def _respond_reminder(self, response: str) -> None:
        if self.reminder_coordinator is not None:
            self.reminder_coordinator.respond(response)

    def _sync_reminder(self, snapshot: ReminderSnapshot) -> None:
        self.reminder_card.setVisible(snapshot.visible)
        if not snapshot.visible:
            return
        self.reminder_title.setText("可以考虑留一个短暂空档")
        self.reminder_body.setText(snapshot.decision.explanation)
        reasons = " · ".join(snapshot.decision.reason_codes)
        response = REMINDER_RESPONSES.get(snapshot.response or "", "")
        suffix = f"最近选择：{response}" if response else ""
        self.reminder_reason.setText(f"依据：{reasons}。{suffix}")
        show_tip = self.repository is None or self.repository.get_setting(
            "activity_tips_enabled", "true"
        ) == "true"
        self.activity_tip.setVisible(show_tip)
        if show_tip:
            self.activity_tip.setText(ACTIVITY_TIPS[datetime.now().minute % len(ACTIVITY_TIPS)])

    def _sync(self, enabled: bool, paused: bool) -> None:
        if not enabled:
            self.monitoring_badge.setText("● 监测未开启")
            self.monitoring_badge.setProperty("tone", "muted")
        elif paused:
            self.monitoring_badge.setText("● 监测已暂停")
        else:
            self.monitoring_badge.setText("● 监测已开启")
        self.monitoring_badge.style().unpolish(self.monitoring_badge)
        self.monitoring_badge.style().polish(self.monitoring_badge)


class UsagePage(QWidget):
    def __init__(self, controller, collector=None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.collector = collector
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.addWidget(label("只展示有限、可解释的电脑活动估计。", "pageLead"))
        grid = QGridLayout()
        grid.setSpacing(12)
        active_frame, self.active_value = self._metric_card("今日活跃估计", "未开启监测", "#7D9FB3")
        category_frame, self.category_value = self._metric_card("类别汇总", "暂无数据", "#D69E52")
        grid.addWidget(active_frame, 0, 0)
        grid.addWidget(category_frame, 0, 1)
        root.addLayout(grid)
        self.demo_banner = label("", "demoBanner")
        root.addWidget(self.demo_banner)
        self.session_value = label("", "cardBody")
        session_frame = QFrame()
        session_frame.setObjectName("card")
        session_layout = QVBoxLayout(session_frame)
        session_layout.setContentsMargins(18, 15, 18, 15)
        session_layout.addWidget(label("当前采样会话", "cardTitle"))
        session_layout.addWidget(self.session_value)
        root.addWidget(session_frame)
        app_frame = QFrame()
        app_frame.setObjectName("card")
        app_layout = QVBoxLayout(app_frame)
        app_layout.setContentsMargins(18, 15, 18, 15)
        app_layout.addWidget(label("最近 7 天 · 应用明细", "cardTitle"))
        self.app_usage_value = label("具体应用明细默认关闭。", "appUsageValue")
        app_layout.addWidget(self.app_usage_value)
        root.addWidget(app_frame)
        root.addWidget(card("采样边界", "不会记录键入内容、截图、窗口标题、网页地址、剪贴板或文件内容。类别统计按日聚合；具体应用标识只有在独立授权后才会保存为按日时长。", "#C56B5D"))
        root.addStretch()
        controller.subscribe(self._sync)
        if collector is not None:
            collector.subscribe(lambda _result: self._sync(controller.enabled, controller.paused))
        self._sync(controller.enabled, controller.paused)

    @staticmethod
    def _metric_card(title: str, value: str, accent: str):
        frame = QFrame()
        frame.setObjectName("card")
        frame.setStyleSheet(f"QFrame#card {{ border-left: 4px solid {accent}; }}")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 15, 18, 15)
        layout.setSpacing(6)
        layout.addWidget(label(title, "cardTitle"))
        value_label = label(value, "metricValue")
        layout.addWidget(value_label)
        return frame, value_label

    def _sync(self, enabled: bool, paused: bool) -> None:
        self._sync_app_usage()
        if not enabled:
            self.active_value.setText("未开启监测\n\n不会把未采集的数据表示为 0 分钟。")
            self.category_value.setText("暂无数据")
            self.session_value.setText("监测未开启；不会调用活动 provider。")
            self.demo_banner.setText("监测未开启：当前页面没有读取 Windows 活动，也没有生成虚假 0 分钟数据。")
            return
        if self.collector is None:
            self.active_value.setText("已开启，等待采样")
            self.category_value.setText("统计服务未连接")
            self.session_value.setText("当前测试窗口未连接 M1 采样服务。")
            return
        rows = self.collector.usage_for_day(date.today())
        active = sum(row.active_seconds for row in rows)
        idle = sum(row.idle_seconds for row in rows)
        unknown = sum(row.unknown_seconds for row in rows)
        if not rows:
            self.active_value.setText("已开启，等待第二次采样\n\n首个样本只建立会话基线。")
            self.category_value.setText("尚未形成日聚合")
        else:
            self.active_value.setText(
                f"约 {active / 60:.1f} 分钟活跃\n"
                f"约 {idle / 60:.1f} 分钟空闲 · {unknown / 60:.1f} 分钟未知"
            )
            category_lines = [
                f"{row.category}: {row.active_seconds / 60:.1f} 分钟"
                for row in rows
                if row.active_seconds > 0
            ]
            self.category_value.setText("\n".join(category_lines) or "暂无活跃类别")
        state = "已暂停" if paused else "运行中"
        continuous = self.collector.continuous_active_seconds
        self.session_value.setText(
            f"监测{state}。当前连续活跃估计约 {continuous:.0f} 秒。使用 monotonic 间隔估算；超过 60 秒的采样间隔会被丢弃，避免把睡眠/锁屏算作持续活动。"
        )
        reason = self.collector.last_result.reason
        if reason == "provider_error":
            self.demo_banner.setText("采样异常：本次没有记录活动数据，应用仍可继续运行；请检查系统权限后重试。")
        elif reason == "long_gap":
            self.demo_banner.setText("采样间隔超过 60 秒：本段未计入活动，避免把锁屏或睡眠算作持续使用。")
        elif reason == "non_monotonic_sample":
            self.demo_banner.setText("采样时间异常：本次间隔未计入活动，等待下一次有效样本。")
        elif reason == "observation_unavailable":
            self.demo_banner.setText("本次观测不可用：未写入活动统计，后续有效样本会重新建立基线。")
        else:
            self.demo_banner.setText(
                "演示数据：当前 provider 为 FakeProvider，未读取 Windows 活动。"
                if self.controller.provider_is_demo
                else "Windows 受控采样：仅在你开启监测后读取空闲秒数与粗粒度类别；应用标识需独立授权。"
            )

    def _sync_app_usage(self) -> None:
        if self.collector is None:
            self.app_usage_value.setText("统计服务未连接。")
            return
        repository = self.collector.repository
        if repository.get_consent("app_name_stats") is not True:
            self.app_usage_value.setText("未开启独立授权；不会保存具体应用标识。")
            return
        rows = repository.app_usage_for_period(date.today() - timedelta(days=6), date.today())
        self.app_usage_value.setText(
            "\n".join(
                f"{APP_DISPLAY_NAMES.get(row.app_id, row.app_id)}　约 {row.active_seconds / 60:.1f} 分钟"
                for row in rows
            )
            if rows
            else "已授权，最近 7 天尚无可显示的应用时长。"
        )


class ReportsPage(QWidget):
    def __init__(self, controller, repository=None, bodylog_service=None, report_service=None, local_ai_service=None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.repository = repository
        self.bodylog_service: BodyLogService | None = bodylog_service
        self.report_service: LocalReportService | None = report_service
        self.local_ai_service = local_ai_service
        self._report_ai_thread: QThread | None = None
        self._report_ai_worker: _ReportAIWorker | None = None
        self._report_ai_generation = 0
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.addWidget(label("以事实为基础回顾，不把估计说成结论。", "pageLead"))

        bodylog_frame = QFrame()
        bodylog_frame.setObjectName("card")
        bodylog_layout = QVBoxLayout(bodylog_frame)
        bodylog_layout.setContentsMargins(18, 15, 18, 15)
        bodylog_layout.addWidget(label("BodyLog · 今日状态打卡", "cardTitle"))
        self.bodylog_status = label("状态打卡默认关闭；需要单独授权。", "cardBody")
        bodylog_layout.addWidget(self.bodylog_status)
        bodylog_actions = QHBoxLayout()
        self.wellness_level = QComboBox()
        for level in WellnessLevel:
            self.wellness_level.addItem(WELLNESS_LEVEL_LABELS[level], level)
        bodylog_actions.addWidget(self.wellness_level)
        self.save_wellness = QPushButton("保存今天的自报")
        self.save_wellness.clicked.connect(self._save_wellness)
        bodylog_actions.addWidget(self.save_wellness)
        self.delete_wellness = QPushButton("删除今天记录")
        self.delete_wellness.clicked.connect(self._delete_wellness)
        bodylog_actions.addWidget(self.delete_wellness)
        bodylog_actions.addStretch()
        bodylog_layout.addLayout(bodylog_actions)
        bodylog_layout.addWidget(label("只记录你主动选择的粗粒度舒适度，不是医学测量；可以不记录或随时删除。", "mutedText"))
        root.addWidget(bodylog_frame)

        report_frame = QFrame()
        report_frame.setObjectName("card")
        report_layout = QVBoxLayout(report_frame)
        report_layout.setContentsMargins(18, 15, 18, 15)
        report_top = QHBoxLayout()
        report_top.addWidget(label("本地事实报告", "cardTitle"))
        report_top.addStretch()
        self.report_period = QComboBox()
        self.report_period.addItem("今日日报", "daily")
        self.report_period.addItem("本周周报", "weekly")
        self.report_period.currentIndexChanged.connect(lambda _index: self.refresh_report())
        report_top.addWidget(self.report_period)
        self.refresh_report_button = QPushButton("刷新报告")
        self.refresh_report_button.clicked.connect(self.refresh_report)
        report_top.addWidget(self.refresh_report_button)
        self.export_report_button = QPushButton("导出 Markdown")
        self.export_report_button.clicked.connect(self._export_report)
        report_top.addWidget(self.export_report_button)
        self.ai_report_button = QPushButton("本地 AI 改写")
        self.ai_report_button.setEnabled(local_ai_service is not None and local_ai_service.enabled)
        self.ai_report_button.setToolTip("只在你主动点击后，把当前结构化 FactSheet 发送到本机回环模型。")
        self.ai_report_button.clicked.connect(self._rewrite_with_ai)
        report_top.addWidget(self.ai_report_button)
        report_layout.addLayout(report_top)
        self.report_sources = label("", "mutedText")
        report_layout.addWidget(self.report_sources)
        self.report_text = QTextEdit()
        self.report_text.setReadOnly(True)
        self.report_text.setMinimumHeight(260)
        report_layout.addWidget(self.report_text)
        report_layout.addWidget(label("报告仅来自本地结构化记录；没有数据时会明确说明缺失，不把电脑活动解释为健康或效率结论。", "mutedText"))
        root.addWidget(report_frame)
        root.addStretch()
        if self.bodylog_service is not None:
            self.bodylog_service.subscribe(self._sync_bodylog)
        else:
            self._sync_bodylog(False)
        controller.subscribe(lambda _enabled, _paused: self.refresh_report())
        if self.local_ai_service is not None:
            self.local_ai_service.subscribe(self._sync_local_ai)
        self.refresh_report()

    def _sync_local_ai(self, enabled: bool) -> None:
        self.ai_report_button.setEnabled(enabled)

    def _sync_bodylog(self, enabled: bool) -> None:
        self.bodylog_status.setText(
            "状态打卡已开启；只保存你今天主动选择的粗粒度选项。"
            if enabled
            else "状态打卡默认关闭；请先在“设置与隐私”中单独授权。"
        )
        self.wellness_level.setEnabled(enabled)
        self.save_wellness.setEnabled(enabled)
        has_entry = self.bodylog_service is not None and self.bodylog_service.today_entry() is not None
        self.delete_wellness.setEnabled(enabled and has_entry)
        if enabled and self.bodylog_service is not None:
            entry = self.bodylog_service.today_entry()
            if entry is not None:
                index = self.wellness_level.findData(entry.comfort_level)
                if index >= 0:
                    self.wellness_level.setCurrentIndex(index)
        self.refresh_report()

    def _save_wellness(self) -> None:
        if self.bodylog_service is None:
            return
        try:
            self.bodylog_service.save_today(self.wellness_level.currentData())
            self.bodylog_status.setText("已保存今天的自报；它只代表你主动填写的记录。")
        except PermissionError:
            self._sync_bodylog(False)
        self._sync_bodylog(self.bodylog_service.enabled)

    def _delete_wellness(self) -> None:
        if self.bodylog_service is None or not self.bodylog_service.enabled:
            return
        answer = QMessageBox.question(
            self,
            "删除今天的状态记录",
            "是否删除今天的 BodyLog 自报？删除后报告不再包含这条记录。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.bodylog_service.delete_today()
            self._sync_bodylog(True)

    @staticmethod
    def _current_period(kind: str) -> ReportPeriod:
        today = date.today()
        if kind == "daily":
            return ReportPeriod("daily", today, today)
        start = today - timedelta(days=today.weekday())
        return ReportPeriod("weekly", start, start + timedelta(days=6))

    def refresh_report(self) -> None:
        self._report_ai_generation += 1
        if self.report_service is None:
            self.report_text.setPlainText("M4 报告服务未连接。")
            self.report_sources.setText("当前窗口未连接本地报告服务。")
            return
        period = self._current_period(self.report_period.currentData() or "daily")
        facts, markdown = self.report_service.render(period)
        self.report_text.setPlainText(markdown)
        quality = facts["data_quality"]
        self.report_sources.setText(
            f"事实来源：usage_daily / 用户确认任务 / reminder_events / BodyLog 自报；"
            f"活动授权：{'已开启' if quality['activity_monitoring_enabled'] else '未开启'}；"
            f"状态打卡：{'已授权' if quality['wellness_opt_in'] else '未授权'}；"
            f"生成：本地规则/模板"
        )

    def _rewrite_with_ai(self) -> None:
        if self.report_service is None or self.local_ai_service is None or not self.local_ai_service.enabled:
            return
        if self._report_ai_thread is not None:
            return
        period = self._current_period(self.report_period.currentData() or "daily")
        facts, template_markdown = self.report_service.render(period)
        generation = self._report_ai_generation
        thread = QThread(self)
        worker = _ReportAIWorker(self.local_ai_service, facts, template_markdown)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda markdown, used_model, generation=generation: self._on_report_ai_finished(
                generation, markdown, used_model
            )
        )
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(self._on_report_ai_thread_finished)
        thread.finished.connect(thread.deleteLater)
        self._report_ai_thread = thread
        self._report_ai_worker = worker
        self.ai_report_button.setEnabled(False)
        self.ai_report_button.setText("本地 AI 改写中…")
        thread.start()

    def _on_report_ai_finished(self, generation: int, markdown: str, used_model: bool) -> None:
        if generation != self._report_ai_generation:
            return
        if self.local_ai_service is None or not self.local_ai_service.enabled:
            self.refresh_report()
            return
        self.report_text.setPlainText(markdown)
        self.report_sources.setText(
            "事实来源：当前本地 FactSheet；生成：本地模型（数字由事实表代入）"
            if used_model
            else "本地模型不可用或输出未通过校验，已回退本地规则/模板。"
        )

    def _on_report_ai_thread_finished(self) -> None:
        self._report_ai_thread = None
        self._report_ai_worker = None
        self.ai_report_button.setText("本地 AI 改写")
        self.ai_report_button.setEnabled(
            self.local_ai_service is not None and self.local_ai_service.enabled
        )

    def _export_report(self) -> None:
        if self.report_service is None:
            return
        period = self._current_period(self.report_period.currentData() or "daily")
        default_name = f"deskcare_{period.kind}_{period.start.isoformat()}.md"
        path, _ = QFileDialog.getSaveFileName(self, "导出 DeskCare 报告", default_name, "Markdown (*.md)")
        if not path:
            return
        self.report_service.export_markdown(path, period)
        self.report_sources.setText(f"报告已保存到用户选择的位置：{Path(path).name}。未保存原始窗口或键盘内容。")


class SettingsPage(QWidget):
    monitoring_changed = Signal(bool)
    all_data_cleared = Signal()
    companion_visibility_changed = Signal(bool)

    def __init__(self, config_store, controller, collector=None, bodylog_service=None, local_ai_service=None, personalization_service=None, repository=None, parent=None) -> None:
        super().__init__(parent)
        self.config_store = config_store
        self.controller = controller
        self.collector = collector
        self.bodylog_service: BodyLogService | None = bodylog_service
        self.local_ai_service = local_ai_service
        self.personalization_service = personalization_service
        self.repository = repository or (collector.repository if collector is not None else None)
        self._local_ai_probe_thread: QThread | None = None
        self._local_ai_probe_worker: _LocalModelProbeWorker | None = None
        self._local_ai_probe_generation = 0
        page_layout = QVBoxLayout(self)
        page_layout.setContentsMargins(0, 0, 0, 0)
        self.settings_scroll = QScrollArea()
        self.settings_scroll.setObjectName("settingsScroll")
        self.settings_scroll.setWidgetResizable(True)
        self.settings_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.settings_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        settings_content = QWidget()
        settings_content.setObjectName("settingsContent")
        root = QVBoxLayout(settings_content)
        root.setSpacing(14)
        root.addWidget(label("所有敏感能力分开授权，随时可以暂停或清除。", "pageLead"))
        root.addWidget(card("隐私原则", "DeskCare 默认离线运行。M1 只有在你明确开启后才读取有限活动信号；M2 只在你主动选择文件后读取其内容，并且只保存确认后的结构化任务；M3 提醒只使用有限活动聚合、已确认任务和你选择的情境。不读取键盘内容、窗口标题、网页地址或剪贴板。", "#2F6B5F"))

        self.companion_enabled = QCheckBox("显示桌面伙伴（默认关闭；可随时隐藏）")
        self.companion_enabled.setChecked(
            self.repository.get_setting("companion_enabled", "false") == "true"
            if self.repository is not None else False
        )
        self.companion_enabled.toggled.connect(self._toggle_companion)
        root.addWidget(self.companion_enabled)
        root.addWidget(label("伙伴只显示你已确认的今日任务和手动情境；本地语音需另行配置 Vosk 模型，仅在按住录音时访问麦克风，不保留音频文件。", "mutedText"))

        self.monitoring = QCheckBox("开启电脑活动统计：空闲秒数与粗粒度类别（默认关闭）")
        self.monitoring.setChecked(controller.enabled)
        self.monitoring.toggled.connect(self._toggle_monitoring)
        root.addWidget(self.monitoring)

        self.app_names = QCheckBox("允许按具体应用统计时长（独立授权，默认关闭）")
        self.app_names.setChecked(
            collector.repository.get_consent("app_name_stats") is True
            if collector is not None else False
        )
        self.app_names.setEnabled(collector is not None)
        self.app_names.setToolTip(
            "保存规范化应用标识（如 chrome）和按日活跃时长；不保存路径、窗口标题或文档名。关闭时会清除已有应用明细。"
        )
        self.app_names.toggled.connect(self._toggle_app_names)
        root.addWidget(self.app_names)
        root.addWidget(label(
            "应用明细只有在此开关和电脑活动统计都开启时才记录。关闭此项会立即删除已有应用级统计；类别统计授权不受影响。",
            "mutedText",
        ))
        self.activity_tips = QCheckBox("休息提醒中显示轻柔、可跳过的活动建议")
        self.activity_tips.setChecked(
            collector.repository.get_setting("activity_tips_enabled", "true") == "true"
            if collector is not None else True
        )
        self.activity_tips.setEnabled(collector is not None)
        self.activity_tips.toggled.connect(self._toggle_activity_tips)
        root.addWidget(self.activity_tips)
        self.health = QCheckBox("开启个人状态打卡：只保存我主动填写的粗粒度舒适度（默认关闭）")
        self.health.setChecked(bodylog_service.enabled if bodylog_service is not None else False)
        self.health.setEnabled(bodylog_service is not None)
        self.health.toggled.connect(self._toggle_bodylog)
        root.addWidget(self.health)
        personalization_card = QFrame()
        personalization_card.setObjectName("card")
        personalization_layout = QVBoxLayout(personalization_card)
        personalization_layout.setContentsMargins(14, 10, 14, 10)
        personalization_layout.addWidget(label("提醒反馈个性化（透明规则）", "cardTitle"))
        self.reminder_personalization = QCheckBox(
            "允许根据我主动提交的提醒反馈，小步降低不合时宜的提醒频率（默认关闭）"
        )
        self.reminder_personalization.setChecked(
            personalization_service.enabled if personalization_service is not None else False
        )
        self.reminder_personalization.setEnabled(
            personalization_service is not None and personalization_service.eligible
        )
        self.reminder_personalization.toggled.connect(self._toggle_personalization)
        personalization_layout.addWidget(self.reminder_personalization)
        self.personalization_feedback = label(
            "至少 10 次真实反馈后才评估；只会把候选窗口延后 5 分钟，不改变静默、截止时间和冷却硬规则。",
            "mutedText",
        )
        personalization_layout.addWidget(self.personalization_feedback)
        self.reset_personalization = QPushButton("恢复默认提醒参数")
        self.reset_personalization.setEnabled(
            personalization_service is not None and personalization_service.enabled
        )
        self.reset_personalization.clicked.connect(self._reset_personalization)
        personalization_layout.addWidget(self.reset_personalization)
        root.addWidget(personalization_card)
        self.local_ai = QCheckBox("允许本机 Local LLM 处理我主动选择的任务清单或报告事实（默认关闭）")
        self.local_ai.setChecked(local_ai_service.enabled if local_ai_service is not None else False)
        self.local_ai.setEnabled(local_ai_service is not None)
        self.local_ai.setToolTip("只允许访问 localhost/127.0.0.1；报告只有在你主动点击改写时才会发送结构化事实；不会上传到云端。")
        self.local_ai.toggled.connect(self._toggle_local_ai)
        root.addWidget(self.local_ai)
        local_ai_config = QFrame()
        local_ai_config.setObjectName("card")
        local_ai_layout = QVBoxLayout(local_ai_config)
        local_ai_layout.setContentsMargins(14, 10, 14, 10)
        local_ai_layout.addWidget(label("本地模型连接（只允许回环地址）", "cardTitle"))
        endpoint_row = QHBoxLayout()
        endpoint_row.addWidget(label("Endpoint", "mutedText"))
        self.local_ai_endpoint = QLineEdit(
            local_ai_service.endpoint if local_ai_service is not None else "http://127.0.0.1:11434/api/chat"
        )
        self.local_ai_endpoint.setPlaceholderText("http://127.0.0.1:11434/api/chat")
        endpoint_row.addWidget(self.local_ai_endpoint, 1)
        local_ai_layout.addLayout(endpoint_row)
        model_row = QHBoxLayout()
        model_row.addWidget(label("模型名", "mutedText"))
        self.local_ai_model = QLineEdit(
            local_ai_service.model if local_ai_service is not None else "llama3.2:3b"
        )
        self.local_ai_model.setPlaceholderText("例如 llama3.2:3b 或你本机已有的模型名")
        model_row.addWidget(self.local_ai_model, 1)
        self.save_local_ai_config = QPushButton("保存配置")
        self.save_local_ai_config.clicked.connect(self._save_local_ai_config)
        model_row.addWidget(self.save_local_ai_config)
        self.probe_local_ai = QPushButton("检测本机模型")
        self.probe_local_ai.setEnabled(
            local_ai_service is not None and local_ai_service.enabled
        )
        self.probe_local_ai.setToolTip("只请求回环地址的 /api/tags，不发送任务、报告或 BodyLog。")
        self.probe_local_ai.clicked.connect(self._probe_local_ai)
        model_row.addWidget(self.probe_local_ai)
        local_ai_layout.addLayout(model_row)
        self.local_ai_config_feedback = label(
            "配置只保存在本地；保存时只校验地址格式，不会联网测试。", "mutedText"
        )
        local_ai_layout.addWidget(self.local_ai_config_feedback)
        root.addWidget(local_ai_config)

        self.pause_button = QPushButton("暂停监测" if controller.enabled else "监测尚未开启")
        self.pause_button.setEnabled(controller.enabled)
        self.pause_button.clicked.connect(controller.toggle_paused)
        root.addWidget(self.pause_button)
        self.clear_usage_button = QPushButton("清除已保存的活动统计")
        self.clear_usage_button.setEnabled(collector is not None)
        self.clear_usage_button.clicked.connect(self._clear_usage)
        root.addWidget(self.clear_usage_button)
        self.clear_usage_feedback = label("仅删除本地活动聚合，不改变监测授权；执行前会再次确认。", "mutedText")
        root.addWidget(self.clear_usage_feedback)
        self.clear_wellness_button = QPushButton("清除全部 BodyLog 状态记录")
        self.clear_wellness_button.setEnabled(bodylog_service is not None)
        self.clear_wellness_button.clicked.connect(self._clear_wellness)
        root.addWidget(self.clear_wellness_button)
        self.clear_wellness_feedback = label("只删除状态自报，不关闭授权；执行前会再次确认。", "mutedText")
        root.addWidget(self.clear_wellness_feedback)
        self.clear_all_button = QPushButton("清除 DeskCare 全部本地数据")
        self.clear_all_button.setEnabled(collector is not None)
        self.clear_all_button.clicked.connect(self._clear_all_data)
        root.addWidget(self.clear_all_button)
        root.addWidget(label("将删除活动聚合、已确认任务、提醒反馈、BodyLog 记录和本地授权状态，并压缩本地数据库；不会删除程序文件。系统备份或磁盘快照中仍可能存在副本。", "mutedText"))
        root.addWidget(label("BodyLog 和本地 AI 均为独立授权；本地模型只访问回环地址，任务清单和报告改写都仍需你的主动操作。", "mutedText"))
        root.addStretch()
        controller.subscribe(self._sync)
        if self.local_ai_service is not None:
            self.local_ai_service.subscribe(self._sync_local_ai)
        if self.personalization_service is not None:
            self.personalization_service.subscribe(self._sync_personalization)
        self._sync(controller.enabled, controller.paused)
        self.settings_scroll.setWidget(settings_content)
        page_layout.addWidget(self.settings_scroll)

    def _toggle_companion(self, enabled: bool) -> None:
        if self.repository is not None:
            self.repository.set_setting("companion_enabled", "true" if enabled else "false")
        self.companion_visibility_changed.emit(enabled)

    def _toggle_monitoring(self, enabled: bool) -> None:
        self.config_store.config.activity_monitoring_enabled = enabled
        self.controller.set_enabled(enabled)
        self.monitoring_changed.emit(enabled)

    def _toggle_app_names(self, enabled: bool) -> None:
        if self.collector is None:
            return
        self.config_store.config.app_name_stats_enabled = enabled
        self.collector.set_app_name_enabled(enabled)

    def _toggle_activity_tips(self, enabled: bool) -> None:
        if self.collector is not None:
            self.collector.repository.set_setting(
                "activity_tips_enabled", "true" if enabled else "false"
            )

    def _toggle_bodylog(self, enabled: bool) -> None:
        self.config_store.config.wellness_checkin_enabled = enabled
        if self.bodylog_service is not None:
            self.bodylog_service.set_enabled(enabled)

    def _toggle_local_ai(self, enabled: bool) -> None:
        self.config_store.config.local_ai_enabled = enabled
        if self.local_ai_service is not None:
            self.local_ai_service.set_enabled(enabled)

    def _toggle_personalization(self, enabled: bool) -> None:
        self.config_store.config.reminder_personalization_enabled = enabled
        if self.personalization_service is not None:
            self.personalization_service.set_enabled(enabled)

    def _reset_personalization(self) -> None:
        if self.personalization_service is None:
            return
        self.config_store.config.reminder_personalization_enabled = False
        self.personalization_service.reset_to_default()

    def _sync_personalization(self, snapshot) -> None:
        self.reminder_personalization.blockSignals(True)
        self.reminder_personalization.setChecked(snapshot.enabled)
        self.reminder_personalization.blockSignals(False)
        self.reminder_personalization.setEnabled(snapshot.eligible)
        self.reset_personalization.setEnabled(snapshot.enabled)
        self.personalization_feedback.setText(snapshot.explanation)

    def _sync_local_ai(self, enabled: bool) -> None:
        self.local_ai.blockSignals(True)
        self.local_ai.setChecked(enabled)
        self.local_ai.blockSignals(False)
        self.local_ai_endpoint.setText(self.local_ai_service.endpoint)
        self.local_ai_model.setText(self.local_ai_service.model)
        self.probe_local_ai.setEnabled(enabled and self._local_ai_probe_thread is None)
        if not enabled:
            self._local_ai_probe_generation += 1

    def _save_local_ai_config(self) -> None:
        if self.local_ai_service is None:
            return
        try:
            self.local_ai_service.configure(self.local_ai_endpoint.text(), self.local_ai_model.text())
        except ValueError as exc:
            QMessageBox.warning(self, "无法保存本地 AI 配置", str(exc))
            return
        self.local_ai_config_feedback.setText(
            "配置已保存到本地；DeskCare 不会在保存时联网，只有你主动使用 AI 功能时才请求本机服务。"
        )

    def _probe_local_ai(self) -> None:
        if (
            self.local_ai_service is None
            or not self.local_ai_service.enabled
            or self._local_ai_probe_thread is not None
        ):
            return
        self._local_ai_probe_generation += 1
        generation = self._local_ai_probe_generation
        endpoint = self.local_ai_endpoint.text().strip()
        configured_model = self.local_ai_model.text().strip()
        self.probe_local_ai.setEnabled(False)
        self.probe_local_ai.setText("检测中…")
        self.local_ai_endpoint.setEnabled(False)
        self.local_ai_model.setEnabled(False)
        self.save_local_ai_config.setEnabled(False)
        self.local_ai_config_feedback.setText(
            "正在检查本机回环服务；不会发送任务、报告或 BodyLog。"
        )
        thread = QThread(self)
        worker = _LocalModelProbeWorker(self.local_ai_service, endpoint, configured_model)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(
            lambda models, error, token=generation, model=configured_model: self._on_local_ai_probe_finished(
                token, model, tuple(models), error
            )
        )
        worker.finished.connect(thread.quit)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._on_local_ai_probe_thread_finished)
        self._local_ai_probe_thread = thread
        self._local_ai_probe_worker = worker
        thread.start()

    def _on_local_ai_probe_finished(
        self, generation: int, configured_model: str, models: tuple[str, ...], error: str
    ) -> None:
        if generation != self._local_ai_probe_generation or not self.local_ai_service.enabled:
            return
        if error:
            self.local_ai_config_feedback.setText(f"检测失败：{error}")
            return
        if not models:
            self.local_ai_config_feedback.setText(
                "本机服务已连接，但没有发现已安装模型；请先在 Ollama 中准备模型。"
            )
            return
        preview = "、".join(models[:4])
        suffix = "…" if len(models) > 4 else ""
        if configured_model in models:
            self.local_ai_config_feedback.setText(
                f"检测成功：配置模型 {configured_model} 可用；本机共 {len(models)} 个模型（{preview}{suffix}）。"
            )
        else:
            self.local_ai_config_feedback.setText(
                f"服务已连接并发现 {len(models)} 个模型（{preview}{suffix}），但当前配置模型 {configured_model or '未填写'} 不在列表中。"
            )

    def _on_local_ai_probe_thread_finished(self) -> None:
        self._local_ai_probe_thread = None
        self._local_ai_probe_worker = None
        self.probe_local_ai.setText("检测本机模型")
        self.probe_local_ai.setEnabled(
            self.local_ai_service is not None and self.local_ai_service.enabled
        )
        self.local_ai_endpoint.setEnabled(True)
        self.local_ai_model.setEnabled(True)
        self.save_local_ai_config.setEnabled(True)

    def _clear_wellness(self) -> None:
        if self.bodylog_service is None:
            return
        answer = QMessageBox.question(
            self,
            "确认清除 BodyLog",
            "这会删除本地所有状态自报，但不会关闭授权。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.bodylog_service.clear_all()
            self.clear_wellness_feedback.setText("已清除全部 BodyLog 状态记录；授权状态未改变。")

    def _clear_all_data(self) -> None:
        if self.collector is None:
            return
        answer = QMessageBox.question(
            self,
            "确认清除 DeskCare 全部数据",
            "这会删除活动聚合、任务、提醒反馈、BodyLog 记录和所有本地授权状态，并压缩本地数据库。无法清除系统备份或磁盘快照中的副本。此操作不可从应用内撤销，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.bodylog_service is not None:
            self.bodylog_service.set_enabled(False)
        if self.local_ai_service is not None:
            self.local_ai_service.set_enabled(False)
        if self.personalization_service is not None:
            self.personalization_service.reset_to_default()
        if self.collector is not None:
            self.collector.set_app_name_enabled(False)
        self.controller.set_enabled(False)
        if self.local_ai_service is not None:
            self.local_ai_service.reset_configuration()
        self.collector.repository.clear_all_data()
        self.collector.reset_session()
        self.collector.notify()
        self.config_store.config.activity_monitoring_enabled = False
        self.config_store.config.wellness_checkin_enabled = False
        self.config_store.config.local_ai_enabled = False
        self.config_store.config.reminder_personalization_enabled = False
        self.config_store.config.app_name_stats_enabled = False
        self.app_names.blockSignals(True)
        self.app_names.setChecked(False)
        self.app_names.blockSignals(False)
        self.clear_usage_feedback.setText("已清除全部 DeskCare 本地数据和授权状态。")
        self.clear_wellness_feedback.setText("已清除全部 DeskCare 本地数据；授权状态已关闭。")
        self.all_data_cleared.emit()

    def _clear_usage(self) -> None:
        if self.collector is None:
            return
        answer = QMessageBox.question(
            self,
            "确认清除活动统计",
            "这会删除 DeskCare 已保存的活动日聚合，但不会删除授权设置。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.collector.repository.clear_usage()
        self.collector.reset_session()
        self.collector.notify()
        self.clear_usage_feedback.setText("已清除本地活动统计；监测授权状态未改变。")

    def _sync(self, enabled: bool, paused: bool) -> None:
        self.monitoring.blockSignals(True)
        self.monitoring.setChecked(enabled)
        self.monitoring.blockSignals(False)
        self.pause_button.setEnabled(enabled)
        self.pause_button.setText("恢复监测" if paused else "暂停监测" if enabled else "监测尚未开启")
        if self.bodylog_service is not None:
            self.health.blockSignals(True)
            self.health.setChecked(self.bodylog_service.enabled)
            self.health.blockSignals(False)
        if self.local_ai_service is not None:
            self.local_ai.blockSignals(True)
            self.local_ai.setChecked(self.local_ai_service.enabled)
            self.local_ai.blockSignals(False)

