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
    QLayout,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QMessageBox,
    QInputDialog,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from deskcare.domain.types import Task, TaskStatus, WELLNESS_LEVEL_LABELS, WellnessLevel
from deskcare.domain.display_names import APP_DISPLAY_NAMES, CATEGORY_DISPLAY_NAMES
from deskcare.importers.loader import parse_selected_file
from deskcare.services.bodylog_service import BodyLogService
from deskcare.services.reminder_service import (
    REMINDER_RESPONSES,
    ReminderSnapshot,
    decision_context_summary,
)
from deskcare.services.report_engine import LocalReportService, ReportPeriod
from deskcare.ui.task_dialog import ImportPreviewDialog, TaskFormDialog
from deskcare.ui.charts import UsageChart
from deskcare.ui.report_preview import ReportPreview


ACTIVITY_TIPS = (
    "如果方便，可以站起来走几步；不想活动时也可以直接跳过。",
    "也可以轻轻活动肩颈，动作以舒适为准；感觉不适就停下。",
    "可以按自己的感觉换个姿势，或短暂看看远处。",
)

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
    def __init__(self, controller, task_service=None, reminder_coordinator=None, local_ai_service=None, repository=None, cloud_ai_service=None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.task_service = task_service
        self.reminder_coordinator = reminder_coordinator
        self.local_ai_service = local_ai_service
        self.cloud_ai_service = cloud_ai_service
        self.repository = repository
        self._tasks: list[Task] = []
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.addWidget(label("把今天放在眼前，按自己的节奏推进。", "pageLead"))

        state_row = QHBoxLayout()
        self.monitoring_badge = label("电脑使用统计未开启", "statusBadge")
        self.monitoring_badge.setWordWrap(False)
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
        self.task_table.setHorizontalHeaderLabels(["状态", "任务", "截止时间", "预计用时（分钟）"])
        self.task_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.task_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.task_table.horizontalHeader().setStretchLastSection(False)
        self.task_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for column in (0, 2, 3):
            self.task_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        task_layout.addWidget(self.task_table)
        self.empty_state = label("今天还没有任务。可以手动添加，也可以从文字清单导入。", "mutedText")
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
            "任务清单 (*.txt *.md *.csv *.xlsx);;文本文件 (*.txt *.md);;表格文件 (*.csv *.xlsx)",
        )
        if not path:
            return
        try:
            result = parse_selected_file(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "无法读取任务清单",
                f"文件暂时打不开或格式无法识别。原有任务没有改动。\n\n{exc}",
            )
            return
        selected_suffix = Path(path).suffix.casefold()
        ai_parser = None
        if selected_suffix != ".xlsx" and self.local_ai_service is not None and self.local_ai_service.enabled:
            ai_parser = lambda selected_path=path: self.local_ai_service.parse_path(selected_path)
        cloud_request_factory = None
        cloud_parser = None
        if selected_suffix != ".xlsx" and self.cloud_ai_service is not None and self.cloud_ai_service.enabled:
            cloud_request_factory = lambda selected_path=path: self.cloud_ai_service.prepare(
                Path(selected_path).read_bytes(), Path(selected_path).name
            )
            cloud_parser = self.cloud_ai_service.parse
        dialog = ImportPreviewDialog(result, self, ai_parser=ai_parser,
                                     cloud_request_factory=cloud_request_factory,
                                     cloud_parser=cloud_parser)
        if selected_suffix == ".xlsx":
            explanation = "表格内容已作为本地草稿读取；AI 整理暂不支持 Excel，请直接编辑草稿或另存为 CSV。"
            dialog.ai_button.setToolTip(explanation)
            dialog.cloud_button.setToolTip(explanation)
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
            due_item = QTableWidgetItem(task.due_at.astimezone().strftime("%m月%d日 %H:%M") if task.due_at else "未设置")
            if task.due_at:
                due_item.setToolTip(task.due_at.isoformat(timespec="minutes"))
            self.task_table.setItem(row, 2, due_item)
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
        self.reminder_body.setText(snapshot.decision.human_explanation)
        reason_labels = {
            "POSSIBLE_NATURAL_GAP": "出现了可能的自然空档",
            "SOFT_DELAY_LIMIT_REACHED": "已等到设定的最长提醒时机",
        }
        reasons = " · ".join(
            reason_labels.get(code, "符合温和提醒条件")
            for code in snapshot.decision.reason_codes
        )
        response = REMINDER_RESPONSES.get(snapshot.response or "", "")
        suffix = f"最近选择：{response}" if response else ""
        context_summary = (
            decision_context_summary(snapshot.decision_context)
            if snapshot.decision_context
            else ""
        )
        self.reminder_reason.setText(
            f"提醒依据：{context_summary} {reasons}。{suffix}".strip()
        )
        show_tip = self.repository is None or self.repository.get_setting(
            "activity_tips_enabled", "true"
        ) == "true"
        self.activity_tip.setVisible(show_tip)
        if show_tip:
            self.activity_tip.setText(ACTIVITY_TIPS[datetime.now().minute % len(ACTIVITY_TIPS)])

    def _sync(self, enabled: bool, paused: bool) -> None:
        if not enabled:
            self.monitoring_badge.setText("● 电脑使用统计未开启")
            self.monitoring_badge.setProperty("tone", "muted")
        elif paused:
            self.monitoring_badge.setText("● 电脑使用统计已暂停")
        else:
            self.monitoring_badge.setText("● 电脑使用统计已开启")
        self.monitoring_badge.style().unpolish(self.monitoring_badge)
        self.monitoring_badge.style().polish(self.monitoring_badge)


class UsagePage(QWidget):
    def __init__(self, controller, collector=None, parent=None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.collector = collector
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setObjectName("usageContent")
        root = QVBoxLayout(content)
        root.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        root.setSpacing(16)
        root.addWidget(label("看看电脑大致用了多久。这里的时间是估算值，不代表工作质量。", "pageLead"))
        grid = QGridLayout()
        grid.setSpacing(12)
        active_frame, self.active_value = self._metric_card("今天活跃时间估计", "未开启统计", "#7D9FB3")
        category_frame, self.continuous_value = self._metric_card("当前连续活跃", "暂无数据", "#D69E52")
        grid.addWidget(active_frame, 0, 0)
        grid.addWidget(category_frame, 0, 1)
        root.addLayout(grid)
        self.demo_banner = label("", "demoBanner")
        root.addWidget(self.demo_banner)
        self.session_value = label("", "cardBody")
        root.addWidget(self.session_value)
        self.sections = QTabWidget()
        root.addWidget(self.sections, 1)
        overview = QWidget()
        overview_layout = QHBoxLayout(overview)
        overview_layout.setContentsMargins(0, 0, 0, 0)
        self.week_chart = UsageChart("columns")
        self.category_chart = UsageChart("donut")
        for title, chart in (("最近 7 天 · 活跃时间", self.week_chart), ("今天 · 应用类别占比", self.category_chart)):
            panel = QFrame()
            panel.setObjectName("card")
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(18, 16, 18, 14)
            panel_layout.addWidget(label(title, "cardTitle"))
            panel_layout.addWidget(chart, 1)
            overview_layout.addWidget(panel, 1)
        self.sections.addTab(overview, "使用概览")
        app_frame = QFrame()
        app_frame.setObjectName("card")
        app_layout = QVBoxLayout(app_frame)
        app_layout.setContentsMargins(18, 15, 18, 15)
        app_layout.addWidget(label("最近 7 天 · 各应用使用时长", "cardTitle"))
        self.app_usage_value = label("具体应用明细默认关闭。", "appUsageValue")
        app_layout.addWidget(self.app_usage_value)
        app_scroll = QScrollArea()
        app_scroll.setWidgetResizable(True)
        app_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.app_chart = UsageChart("bars")
        app_scroll.setWidget(self.app_chart)
        app_layout.addWidget(app_scroll, 1)
        self.sections.addTab(app_frame, "应用排行")
        root.addWidget(label("只展示经你授权的本地聚合记录 · 将鼠标移到图上可查看时间", "mutedText"))
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
        self.demo_banner.hide()
        if not enabled:
            self.week_chart.set_values((), "开启统计后，这里会显示最近 7 天的记录")
            self.category_chart.set_values((), "当前未开启电脑使用统计")
            self.active_value.setText("未开启监测\n\n不会把未采集的数据表示为 0 分钟。")
            self.continuous_value.setText("未开启统计")
            self.session_value.setText("电脑使用统计尚未开启。你仍可正常管理任务。")
            self.demo_banner.setText("目前没有收集使用时间，因此不会显示成 0 分钟。")
            return
        if self.collector is None:
            self.active_value.setText("统计刚开启，正在收集使用时间")
            self.continuous_value.setText("统计暂时不可用")
            self.session_value.setText("统计暂时不可用；其他功能仍可继续使用。")
            return
        rows = self.collector.usage_for_day(date.today())
        week = []
        for offset in range(6, -1, -1):
            day = date.today() - timedelta(days=offset)
            day_rows = self.collector.usage_for_day(day)
            week.append((day.strftime("%m/%d"), sum(row.active_seconds for row in day_rows) if day_rows else None))
        self.week_chart.set_values(week)
        self.category_chart.set_values([
            (CATEGORY_DISPLAY_NAMES.get(row.category, "其他应用"), row.active_seconds)
            for row in rows if row.active_seconds > 0
        ], "今天还没有可显示的活跃记录")
        active = sum(row.active_seconds for row in rows)
        idle = sum(row.idle_seconds for row in rows)
        unknown = sum(row.unknown_seconds for row in rows)
        if not rows:
            self.active_value.setText("统计已开启，正在收集使用时间")
        else:
            self.active_value.setText(
            f"活跃约 {active / 60:.1f} 分钟\n"
            f"空闲约 {idle / 60:.1f} 分钟 · 未能判断约 {unknown / 60:.1f} 分钟"
            )
        state = "已暂停" if paused else "运行中"
        continuous = self.collector.continuous_active_seconds
        self.continuous_value.setText(f"约 {continuous / 60:.1f} 分钟" + (" · 已暂停" if paused else ""))
        self.session_value.setText(
            f"统计{state}。连续使用时间约 {continuous / 60:.1f} 分钟。电脑锁屏或休眠期间不会算作持续使用。"
        )
        reason = self.collector.last_result.reason
        self.demo_banner.setVisible(reason in {"provider_error", "long_gap", "non_monotonic_sample", "observation_unavailable"})
        if reason == "provider_error":
            self.demo_banner.setText("这次没有记录到使用时间。你可以稍后重试，其他功能不受影响。")
        elif reason == "long_gap":
            self.demo_banner.setText("电脑锁屏或休眠后，这段时间不会算作持续使用。")
        elif reason == "non_monotonic_sample":
            self.demo_banner.setText("暂时无法判断这段使用时间；下一次正常记录后会继续统计。")
        elif reason == "observation_unavailable":
            self.demo_banner.setText("这段时间没有计入统计；之后有新的记录时会继续更新。")
        else:
            self.demo_banner.setText(
                "这是演示数据，没有读取这台电脑的真实使用情况。"
                if self.controller.provider_is_demo
                else "只有开启统计后，DeskCare 才会估算活跃时间和应用类别；具体应用名称需单独开启统计。"
            )

    def _sync_app_usage(self) -> None:
        if self.collector is None:
            self.app_usage_value.setText("统计服务未连接。")
            self.app_chart.set_values((), "统计服务尚未连接")
            return
        repository = self.collector.repository
        if repository.get_consent("app_name_stats") is not True:
            self.app_usage_value.setText("未开启独立授权；不会保存具体应用标识。")
            self.app_chart.set_values((), "如需查看应用排行，请在设置中单独开启应用名称统计")
            return
        rows = repository.app_usage_for_period(date.today() - timedelta(days=6), date.today())
        self.app_chart.set_values([
            (APP_DISPLAY_NAMES.get(row.app_id, row.app_id), row.active_seconds)
            for row in rows if row.active_seconds > 0
        ], "已授权，最近 7 天尚无应用记录")
        self.app_usage_value.setText(
            f"最近 7 天记录了 {len(rows)} 个应用，按活跃时间排列。"
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
        self._report_ai_base_markdown = ""
        self._template_markdown = None
        self._ai_snapshot_visible = False
        root = QVBoxLayout(self)
        root.setSpacing(16)
        root.addWidget(label("回顾最近的任务和电脑使用情况。记录只是参考，不是健康或效率评判。", "pageLead"))
        self.sections = QTabWidget()
        root.addWidget(self.sections, 1)

        bodylog_frame = QFrame()
        bodylog_frame.setObjectName("card")
        bodylog_layout = QVBoxLayout(bodylog_frame)
        bodylog_layout.setContentsMargins(18, 15, 18, 15)
        bodylog_layout.addWidget(label("今天的状态", "cardTitle"))
        self.bodylog_status = label("状态打卡默认关闭；需要单独授权。", "cardBody")
        bodylog_layout.addWidget(self.bodylog_status)
        bodylog_actions = QHBoxLayout()
        self.wellness_level = QComboBox()
        for level in WellnessLevel:
            self.wellness_level.addItem(WELLNESS_LEVEL_LABELS[level], level)
        bodylog_actions.addWidget(self.wellness_level)
        self.save_wellness = QPushButton("保存今天的状态")
        self.save_wellness.clicked.connect(self._save_wellness)
        bodylog_actions.addWidget(self.save_wellness)
        self.delete_wellness = QPushButton("删除今天记录")
        self.delete_wellness.clicked.connect(self._delete_wellness)
        bodylog_actions.addWidget(self.delete_wellness)
        bodylog_actions.addStretch()
        bodylog_layout.addLayout(bodylog_actions)
        bodylog_layout.addWidget(label("只记录你主动选择的简单状态，不是医学检查；你可以不记录，也可以随时删除。", "mutedText"))
        status_page = QWidget()
        status_layout = QVBoxLayout(status_page)
        status_layout.setContentsMargins(0, 0, 0, 0)
        status_layout.addWidget(bodylog_frame)
        status_layout.addStretch()
        self.sections.addTab(status_page, "我的状态")

        report_frame = QFrame()
        report_frame.setObjectName("card")
        report_layout = QVBoxLayout(report_frame)
        report_layout.setContentsMargins(18, 15, 18, 15)
        report_top = QHBoxLayout()
        report_top.addWidget(label("今日 / 每周小结", "cardTitle"))
        report_top.addStretch()
        self.report_period = QComboBox()
        self.report_period.addItem("今日日报", "daily")
        self.report_period.addItem("本周周报", "weekly")
        self.report_period.currentIndexChanged.connect(lambda _index: self.refresh_report())
        report_top.addWidget(self.report_period)
        self.refresh_report_button = QPushButton("刷新报告")
        self.refresh_report_button.clicked.connect(self.refresh_report)
        report_top.addWidget(self.refresh_report_button)
        self.export_report_button = QPushButton("保存为文件")
        self.export_report_button.clicked.connect(self._export_report)
        report_top.addWidget(self.export_report_button)
        self.ai_report_button = QPushButton("AI 帮我润色")
        self.ai_report_button.setEnabled(local_ai_service is not None and local_ai_service.enabled)
        self.ai_report_button.setToolTip("只在你主动点击后，使用已设置的本机 AI 帮助整理这份小结；不会发送到云端。")
        self.ai_report_button.clicked.connect(self._rewrite_with_ai)
        report_top.addWidget(self.ai_report_button)
        report_layout.addLayout(report_top)
        self.report_sources = label("", "mutedText")
        report_layout.addWidget(self.report_sources)
        self.report_text = ReportPreview()
        self.report_text.setMinimumHeight(260)
        report_layout.addWidget(self.report_text)
        report_layout.addWidget(label("小结只使用 DeskCare 已记录的信息。缺少记录时会直接说明，不会猜测你的健康或工作效率。", "mutedText"))
        self.sections.addTab(report_frame, "日报与周报")
        self.sections.setCurrentIndex(1)
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
        if not enabled:
            self.refresh_report()

    def _sync_bodylog(self, enabled: bool) -> None:
        self.bodylog_status.setText(
            "状态打卡已开启；只保存你今天主动选择的选项。"
            if enabled
            else "状态打卡默认关闭；需要时可在“设置与隐私”中开启。"
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
            "是否删除今天的状态记录？删除后今日小结不再包含这条记录。",
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
        was_snapshot = self._ai_snapshot_visible
        self._ai_snapshot_visible = False
        self._report_ai_generation += 1
        if self.report_service is None:
            self.report_text.setPlainText("小结暂时不可用。")
            self.report_sources.setText("目前无法读取本机保存的记录。")
            return
        period = self._current_period(self.report_period.currentData() or "daily")
        facts, markdown = self.report_service.render(period)
        if markdown == self._template_markdown and not was_snapshot:
            return
        self._template_markdown = markdown
        self.report_text.set_report(markdown)
        quality = facts["data_quality"]
        self.report_sources.setText(
            f"小结依据：电脑使用记录、你确认的任务和提醒反馈；"
            f"电脑使用统计：{'已开启' if quality['activity_monitoring_enabled'] else '未开启'}；"
            f"状态打卡：{'已开启' if quality['wellness_opt_in'] else '未开启'}；"
            f"生成方式：DeskCare 本机整理"
        )

    def notify_data_changed(self) -> None:
        # A model request describes the snapshot selected by the user. Do not
        # invalidate it every five seconds or silently mix it with newer facts.
        if self._report_ai_thread is not None or self._ai_snapshot_visible:
            self.report_sources.setText(
                "当前为本机 AI 整理时的记录快照；点“刷新报告”可查看最新记录。"
                if self._ai_snapshot_visible else "本机 AI 正在整理点击时的记录；其他功能可继续使用。"
            )
            return
        self.refresh_report()

    def _rewrite_with_ai(self) -> None:
        if self.report_service is None or self.local_ai_service is None or not self.local_ai_service.enabled:
            return
        if self._report_ai_thread is not None:
            return
        period = self._current_period(self.report_period.currentData() or "daily")
        facts, template_markdown = self.report_service.render(period)
        self._report_ai_base_markdown = template_markdown
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
        self.ai_report_button.setText("正在整理…")
        thread.start()

    def _on_report_ai_finished(self, generation: int, markdown: str, used_model: bool) -> None:
        if generation != self._report_ai_generation:
            return
        if self.local_ai_service is None or not self.local_ai_service.enabled:
            self.refresh_report()
            return
        if used_model:
            self._ai_snapshot_visible = True
            self.report_text.set_report(
                f"{markdown}\n\n---\n\n{self._report_ai_base_markdown}"
            )
        else:
            self.report_text.set_report(markdown)
        self.report_sources.setText(
            "本机 AI 整理快照；记录中的时间和数字仍由 DeskCare 提供。点“刷新报告”可查看最新记录。"
            if used_model
            else "本机 AI 暂时不可用，已显示 DeskCare 的基础小结。"
        )

    def _on_report_ai_thread_finished(self) -> None:
        self._report_ai_thread = None
        self._report_ai_worker = None
        self.ai_report_button.setText("AI 帮我润色")
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
        try:
            self.report_service.export_markdown(path, period)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(
                self,
                "报告没有保存",
                f"无法写入你选择的位置。请换一个文件夹后重试。\n\n{exc}",
            )
            return
        self.report_sources.setText(f"报告已保存到用户选择的位置：{Path(path).name}。未保存原始窗口或键盘内容。")


class SettingsPage(QWidget):
    monitoring_changed = Signal(bool)
    all_data_cleared = Signal()
    companion_visibility_changed = Signal(bool)

    def __init__(self, config_store, controller, collector=None, bodylog_service=None, local_ai_service=None, personalization_service=None, repository=None, cloud_ai_service=None, parent=None) -> None:
        super().__init__(parent)
        self.config_store = config_store
        self.controller = controller
        self.collector = collector
        self.bodylog_service: BodyLogService | None = bodylog_service
        self.local_ai_service = local_ai_service
        self.cloud_ai_service = cloud_ai_service
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
        self.settings_scroll.setAlignment(
            Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop
        )
        settings_content = QWidget()
        settings_content.setObjectName("settingsContent")
        settings_content.setMaximumWidth(920)
        root = QVBoxLayout(settings_content)
        root.setSpacing(14)
        root.addWidget(label("哪些信息会被记录、是否使用 AI，都由你决定；每项都可以单独关闭。", "pageLead"))
        self.sections = QTabWidget()
        root.addWidget(self.sections)
        general = QWidget()
        root = QVBoxLayout(general)
        root.setContentsMargins(4, 8, 4, 12)
        root.setSpacing(14)
        self.sections.addTab(general, "常用设置")
        root.addWidget(card("桌面与电脑统计", "选择日常要用的功能。电脑统计与应用名称统计分别由你开启。"))

        self.companion_enabled = QCheckBox("显示桌面伙伴（默认关闭；可随时隐藏）")
        self.companion_enabled.setChecked(
            self.repository.get_setting("companion_enabled", "false") == "true"
            if self.repository is not None else False
        )
        self.companion_enabled.toggled.connect(self._toggle_companion)
        root.addWidget(self.companion_enabled)
        root.addWidget(label("伙伴只显示你确认过的任务和手动选择的情境。语音输入目前需要另行设置离线语音包；按住说话时才会使用麦克风，录音不会保存成文件。", "mutedText"))

        self.monitoring = QCheckBox("开启电脑使用统计（默认关闭）")
        self.monitoring.setChecked(controller.enabled)
        self.monitoring.toggled.connect(self._toggle_monitoring)
        root.addWidget(self.monitoring)

        self.app_names = QCheckBox("显示每个应用的使用时长（单独开启，默认关闭）")
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
            "只有同时开启电脑使用统计和此项，才会记录应用名称。关闭后会立即删除已有应用时长；类别汇总不受影响。",
            "mutedText",
        ))
        root.addStretch()
        reminders = QWidget()
        root = QVBoxLayout(reminders)
        root.setContentsMargins(4, 8, 4, 12)
        root.setSpacing(14)
        self.sections.addTab(reminders, "提醒与状态")
        self.activity_tips = QCheckBox("休息提醒中显示轻柔、可跳过的活动建议")
        self.activity_tips.setChecked(
            collector.repository.get_setting("activity_tips_enabled", "true") == "true"
            if collector is not None else True
        )
        self.activity_tips.setEnabled(collector is not None)
        self.activity_tips.toggled.connect(self._toggle_activity_tips)
        root.addWidget(self.activity_tips)
        self.health = QCheckBox("开启每天的状态打卡（默认关闭）")
        self.health.setChecked(bodylog_service.enabled if bodylog_service is not None else False)
        self.health.setEnabled(bodylog_service is not None)
        self.health.toggled.connect(self._toggle_bodylog)
        root.addWidget(self.health)
        personalization_card = QFrame()
        personalization_card.setObjectName("card")
        personalization_layout = QVBoxLayout(personalization_card)
        personalization_layout.setContentsMargins(14, 10, 14, 10)
        personalization_layout.addWidget(label("让休息提醒参考我的反馈", "cardTitle"))
        self.reminder_personalization = QCheckBox(
            "允许 DeskCare 参考我的反馈，减少不合时宜的提醒（默认关闭）"
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
            "收集到足够的提醒反馈后，DeskCare 才会尝试调整提醒时机；你可以随时关闭或恢复默认。",
            "mutedText",
        )
        personalization_layout.addWidget(self.personalization_feedback)
        self.reset_personalization = QPushButton("恢复默认提醒参数")
        self.reset_personalization.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.reset_personalization.setEnabled(
            personalization_service is not None and personalization_service.enabled
        )
        self.reset_personalization.clicked.connect(self._reset_personalization)
        personalization_layout.addWidget(
            self.reset_personalization, 0, Qt.AlignmentFlag.AlignLeft
        )
        root.addWidget(personalization_card)
        root.addStretch()
        ai = QWidget()
        root = QVBoxLayout(ai)
        root.setContentsMargins(4, 8, 4, 12)
        root.setSpacing(14)
        self.sections.addTab(ai, "AI 服务")
        root.addWidget(card("按需启用 AI", "不设置 AI 也能管理任务、查看统计和生成本地小结。"))
        self.local_ai = QCheckBox("允许本机 AI 帮我整理任务清单和小结（默认关闭）")
        self.local_ai.setChecked(local_ai_service.enabled if local_ai_service is not None else False)
        self.local_ai.setEnabled(local_ai_service is not None)
        self.local_ai.setToolTip("只使用这台电脑上的 AI 服务，不会把内容上传到云端。整理任务或小结仍需你主动点击。")
        self.local_ai.toggled.connect(self._toggle_local_ai)
        root.addWidget(self.local_ai)
        self.local_ai_advanced_button = QPushButton("填写本机 AI 连接信息（高级设置）")
        self.local_ai_advanced_button.setCheckable(True)
        self.local_ai_advanced_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        root.addWidget(self.local_ai_advanced_button, 0, Qt.AlignmentFlag.AlignLeft)
        local_ai_config = QFrame()
        self.local_ai_config = local_ai_config
        local_ai_config.setObjectName("card")
        local_ai_layout = QVBoxLayout(local_ai_config)
        local_ai_layout.setContentsMargins(14, 10, 14, 10)
        local_ai_layout.addWidget(label("本机 AI 连接设置（高级选项）", "cardTitle"))
        endpoint_row = QHBoxLayout()
        endpoint_row.addWidget(label("服务地址", "mutedText"))
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
        self.probe_local_ai = QPushButton("检查本机 AI 是否可用")
        self.probe_local_ai.setEnabled(
            local_ai_service is not None and local_ai_service.enabled
        )
        self.probe_local_ai.setToolTip("只检查本机 AI 是否可用，不会发送任务或小结。")
        self.probe_local_ai.clicked.connect(self._probe_local_ai)
        model_row.addWidget(self.probe_local_ai)
        local_ai_layout.addLayout(model_row)
        self.local_ai_config_feedback = label(
            "设置只保存在这台电脑；保存时不会连接 AI 服务。", "mutedText"
        )
        local_ai_layout.addWidget(self.local_ai_config_feedback)
        local_ai_config.setVisible(False)
        self.local_ai_advanced_button.toggled.connect(local_ai_config.setVisible)
        root.addWidget(local_ai_config)

        cloud_card = QFrame()
        cloud_card.setObjectName("card")
        cloud_layout = QVBoxLayout(cloud_card)
        cloud_layout.setContentsMargins(14, 10, 14, 10)
        cloud_layout.addWidget(label("联网 AI（可选，默认关闭）", "cardTitle"))
        cloud_layout.addWidget(label(
            "只处理你主动选择的任务清单。每次发送前都会展示内容并等你确认；任务文字会发送给你设置的服务商，可能产生费用并受其隐私政策约束。"
            "不会发送电脑使用统计或状态打卡。关闭授权会删除已保存的服务密钥。", "mutedText"
        ))
        self.cloud_ai = QCheckBox("允许把我选中的任务清单发送给联网 AI 整理")
        self.cloud_ai.setChecked(cloud_ai_service.enabled if cloud_ai_service is not None else False)
        self.cloud_ai.setEnabled(cloud_ai_service is not None)
        self.cloud_ai.toggled.connect(self._toggle_cloud_ai)
        cloud_layout.addWidget(self.cloud_ai)
        self.cloud_advanced_button = QPushButton("填写联网 AI 服务信息（高级设置）")
        self.cloud_advanced_button.setCheckable(True)
        self.cloud_advanced_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        cloud_layout.addWidget(
            self.cloud_advanced_button, 0, Qt.AlignmentFlag.AlignLeft
        )
        cloud_advanced = QWidget()
        self.cloud_advanced_frame = cloud_advanced
        cloud_advanced_layout = QVBoxLayout(cloud_advanced)
        cloud_advanced_layout.setContentsMargins(0, 0, 0, 0)
        self.cloud_endpoint = QLineEdit(cloud_ai_service.endpoint if cloud_ai_service else "https://api.openai.com/v1/chat/completions")
        self.cloud_endpoint.setPlaceholderText("https://…/v1/chat/completions")
        self.cloud_endpoint.setToolTip("服务商提供的 HTTPS 地址。请确认服务商可信并了解其数据政策。")
        cloud_advanced_layout.addWidget(self.cloud_endpoint)
        cloud_model_row = QHBoxLayout()
        self.cloud_model = QLineEdit(cloud_ai_service.model if cloud_ai_service else "")
        self.cloud_model.setPlaceholderText("服务商提供的模型名称（高级设置）")
        cloud_model_row.addWidget(self.cloud_model, 1)
        self.save_cloud_config = QPushButton("保存联网 AI 设置")
        self.save_cloud_config.clicked.connect(self._save_cloud_config)
        cloud_model_row.addWidget(self.save_cloud_config)
        cloud_advanced_layout.addLayout(cloud_model_row)
        key_row = QHBoxLayout()
        self.cloud_key_status = label(
            "服务密钥已安全保存。" if cloud_ai_service and cloud_ai_service.has_key
            else "尚未保存服务密钥。", "mutedText"
        )
        key_row.addWidget(self.cloud_key_status, 1)
        self.save_cloud_key = QPushButton("输入服务密钥")
        self.save_cloud_key.setToolTip("服务商也可能称它为 API Key；DeskCare 会将其保存在 Windows 凭据管理器中。")
        self.save_cloud_key.setEnabled(cloud_ai_service is not None)
        self.save_cloud_key.clicked.connect(self._save_cloud_key)
        key_row.addWidget(self.save_cloud_key)
        self.delete_cloud_key = QPushButton("删除服务密钥")
        self.delete_cloud_key.setEnabled(cloud_ai_service is not None and cloud_ai_service.has_key)
        self.delete_cloud_key.clicked.connect(self._delete_cloud_key)
        key_row.addWidget(self.delete_cloud_key)
        cloud_advanced_layout.addLayout(key_row)
        self.cloud_feedback = label("服务密钥不会写入应用数据、日志或导出文件；联网请求使用加密连接。", "mutedText")
        cloud_advanced_layout.addWidget(self.cloud_feedback)
        cloud_advanced.setVisible(False)
        self.cloud_advanced_button.toggled.connect(cloud_advanced.setVisible)
        cloud_layout.addWidget(cloud_advanced)
        root.addWidget(cloud_card)

        root.addStretch()
        privacy = QWidget()
        root = QVBoxLayout(privacy)
        root.setContentsMargins(4, 8, 4, 12)
        root.setSpacing(14)
        self.sections.addTab(privacy, "数据与隐私")
        root.addWidget(card("隐私说明", "电脑使用统计默认关闭。你开启后，DeskCare 只记录大致的活跃时间和应用类别；只有你主动选文件时才读取清单，并且只有确认后的任务才会保存。不记录键盘输入、截图、窗口标题、网页地址或剪贴板内容。"))
        self.pause_button = QPushButton("暂停电脑使用统计" if controller.enabled else "电脑使用统计尚未开启")
        self.pause_button.setEnabled(controller.enabled)
        self.pause_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.pause_button.clicked.connect(controller.toggle_paused)
        root.addWidget(self.pause_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.clear_usage_button = QPushButton("清除电脑使用记录")
        self.clear_usage_button.setEnabled(collector is not None)
        self.clear_usage_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.clear_usage_button.clicked.connect(self._clear_usage)
        root.addWidget(self.clear_usage_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.clear_usage_feedback = label("只删除电脑使用记录，不会改变统计开关；删除前会再次确认。", "mutedText")
        root.addWidget(self.clear_usage_feedback)
        self.clear_wellness_button = QPushButton("清除所有状态打卡记录")
        self.clear_wellness_button.setEnabled(bodylog_service is not None)
        self.clear_wellness_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.clear_wellness_button.clicked.connect(self._clear_wellness)
        root.addWidget(self.clear_wellness_button, 0, Qt.AlignmentFlag.AlignLeft)
        self.clear_wellness_feedback = label("只删除状态打卡，不会改变开关；删除前会再次确认。", "mutedText")
        root.addWidget(self.clear_wellness_feedback)
        self.clear_all_button = QPushButton("清除 DeskCare 全部本地数据")
        self.clear_all_button.setEnabled(collector is not None)
        self.clear_all_button.setSizePolicy(
            QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed
        )
        self.clear_all_button.clicked.connect(self._clear_all_data)
        root.addWidget(self.clear_all_button, 0, Qt.AlignmentFlag.AlignLeft)
        root.addWidget(label("将删除电脑使用记录、已保存任务、提醒反馈、状态打卡和授权设置；不会删除程序文件。系统备份中可能仍有副本。", "mutedText"))
        root.addWidget(label("本机 AI 和联网 AI 都是可选项。使用联网 AI 前，DeskCare 会先让你查看并确认要发送的内容。", "mutedText"))
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

    def _toggle_cloud_ai(self, enabled: bool) -> None:
        if self.cloud_ai_service is None:
            return
        if enabled:
            answer = QMessageBox.question(
                self, "开启联网 AI",
                "开启后，只有你在导入任务清单时选择联网 AI，并查看本次内容、再次确认后，任务文字才会发送给你设置的服务商。"
                "电脑使用统计和状态打卡不会发送。服务商的数据和收费规则请以其说明为准；关闭此项会删除已保存的服务密钥。现在开启吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.cloud_ai.blockSignals(True)
                self.cloud_ai.setChecked(False)
                self.cloud_ai.blockSignals(False)
                return
        try:
            self.cloud_ai_service.set_enabled(enabled)
        except Exception as exc:
            self.cloud_ai.blockSignals(True)
            # Revocation takes effect before credential deletion is attempted;
            # never re-check the UI into an apparently authorized state.
            self.cloud_ai.setChecked(False)
            self.cloud_ai.blockSignals(False)
            QMessageBox.warning(
                self, "联网 AI 设置状态",
                ("云端授权已关闭，但 Windows 凭据删除失败。请在 Windows 凭据管理器中检查并删除 DeskCare/CloudAI/OpenAICompatible。\n\n" + str(exc))
                if not enabled else str(exc),
            )
            return
        self._sync_cloud_key_status()

    def _save_cloud_config(self) -> None:
        if self.cloud_ai_service is None:
            return
        try:
            self.cloud_ai_service.configure(self.cloud_endpoint.text(), self.cloud_model.text())
        except ValueError as exc:
            QMessageBox.warning(self, "无法保存云端配置", str(exc))
            return
        self.cloud_feedback.setText("联网 AI 设置已保存；保存时不会连接服务商。")

    def _save_cloud_key(self) -> None:
        if self.cloud_ai_service is None or not self.cloud_ai_service.enabled:
            QMessageBox.information(self, "需要授权", "请先开启联网 AI，并确认你同意发送所选任务清单。")
            return
        secret, accepted = QInputDialog.getText(
            self, "保存 API Key", "API Key（仅保存到 Windows 凭据管理器）:", QLineEdit.EchoMode.Password
        )
        if not accepted:
            return
        try:
            self.cloud_ai_service.save_key(secret)
        except Exception as exc:
            QMessageBox.warning(self, "无法保存 API Key", str(exc))
            return
        self._sync_cloud_key_status()

    def _delete_cloud_key(self) -> None:
        if self.cloud_ai_service is None:
            return
        try:
            self.cloud_ai_service.credentials.delete()
        except Exception as exc:
            QMessageBox.warning(self, "无法删除 API Key", str(exc))
            return
        self._sync_cloud_key_status()

    def _sync_cloud_key_status(self) -> None:
        present = self.cloud_ai_service is not None and self.cloud_ai_service.has_key
        self.cloud_key_status.setText("服务密钥已安全保存。" if present else "尚未保存服务密钥。")
        self.delete_cloud_key.setEnabled(present)

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
            "设置已保存到这台电脑；保存时没有联网。只有你主动使用 AI 功能时才会连接本机服务。"
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
            "正在检查本机 AI 是否可用；不会发送任务清单或小结。"
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
                "本机 AI 服务已连接，但没有可用模型；请按本机 AI 软件的说明准备模型。"
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
        self.probe_local_ai.setText("检查本机 AI 是否可用")
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
            "确认清除状态打卡",
            "这会删除本地所有状态打卡记录，但不会关闭开关。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.bodylog_service.clear_all()
            self.clear_wellness_feedback.setText("已清除所有状态打卡记录；开关状态未改变。")

    def _clear_all_data(self) -> None:
        if self.collector is None:
            return
        answer = QMessageBox.question(
            self,
            "确认清除 DeskCare 全部数据",
            "这会删除电脑使用记录、已保存任务、提醒反馈、状态打卡和所有授权设置。系统备份中可能仍有副本；此操作不能在 DeskCare 内撤销。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        if self.bodylog_service is not None:
            self.bodylog_service.set_enabled(False)
        if self.local_ai_service is not None:
            self.local_ai_service.set_enabled(False)
        if self.cloud_ai_service is not None:
            self.cloud_ai_service.set_enabled(False)
        if self.personalization_service is not None:
            self.personalization_service.reset_to_default()
        if self.collector is not None:
            self.collector.set_app_name_enabled(False)
        self.controller.set_enabled(False)
        if self.local_ai_service is not None:
            self.local_ai_service.reset_configuration()
        if self.cloud_ai_service is not None:
            self.cloud_ai_service.reset_configuration()
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
        self.cloud_ai.blockSignals(True)
        self.cloud_ai.setChecked(False)
        self.cloud_ai.blockSignals(False)
        self._sync_cloud_key_status()
        self.clear_usage_feedback.setText("已清除全部 DeskCare 本地数据和授权状态。")
        self.clear_wellness_feedback.setText("已清除全部 DeskCare 本地数据；授权状态已关闭。")
        self.all_data_cleared.emit()

    def _clear_usage(self) -> None:
        if self.collector is None:
            return
        answer = QMessageBox.question(
            self,
            "确认清除电脑使用记录",
            "这会删除 DeskCare 已保存的电脑使用时间，但不会关闭统计开关。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.collector.repository.clear_usage()
        self.collector.reset_session()
        self.collector.notify()
        self.clear_usage_feedback.setText("已清除电脑使用记录；统计开关状态未改变。")

    def _sync(self, enabled: bool, paused: bool) -> None:
        self.monitoring.blockSignals(True)
        self.monitoring.setChecked(enabled)
        self.monitoring.blockSignals(False)
        self.pause_button.setEnabled(enabled)
        self.pause_button.setText("恢复电脑使用统计" if paused else "暂停电脑使用统计" if enabled else "电脑使用统计尚未开启")
        if self.bodylog_service is not None:
            self.health.blockSignals(True)
            self.health.setChecked(self.bodylog_service.enabled)
            self.health.blockSignals(False)
        if self.local_ai_service is not None:
            self.local_ai.blockSignals(True)
            self.local_ai.setChecked(self.local_ai_service.enabled)
            self.local_ai.blockSignals(False)

