"""Main Qt window and page navigation for DeskCare M8."""

from PySide6.QtCore import QSize, QThread, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from deskcare.ui.pages import ReportsPage, SettingsPage, TodayPage, UsagePage
from deskcare.ui.companion import CompanionWindow
from deskcare.ui.tray import build_tray_icon
from deskcare.ui.theme import STYLE, apply_theme
from deskcare.ui.icons import navigation_icon
from deskcare.ui.reminder_popup import ReminderPopup
from deskcare.services.health_journal_service import HealthJournalService
from deskcare.services.reminder_advice import ReminderAdviceService
from deskcare.ai.reminder_advisor import ReminderAIAdvisor
from deskcare.ui.reminder_advice import ReminderAdviceDialog
from deskcare.services.assistant_service import AssistantService
from deskcare.ui.assistant import AssistantDialog
from deskcare.services.lab_reading_service import LabReadingService
from deskcare.ui.lab_reading import LabReadingDialog


class MainWindow(QMainWindow):
    def __init__(
        self,
        config_store,
        monitoring_controller,
        activity_collector=None,
        task_service=None,
        reminder_coordinator=None,
        repository=None,
        bodylog_service=None,
        report_service=None,
        local_ai_service=None,
        personalization_service=None,
        cloud_ai_service=None,
    ) -> None:
        super().__init__()
        self.config_store = config_store
        self.monitoring_controller = monitoring_controller
        self.activity_collector = activity_collector
        self.task_service = task_service
        self.reminder_coordinator = reminder_coordinator
        self.repository = repository
        self.bodylog_service = bodylog_service
        self.report_service = report_service
        self.local_ai_service = local_ai_service
        self.cloud_ai_service = cloud_ai_service
        self.personalization_service = personalization_service
        self.health_journal_service = HealthJournalService(repository, task_service) if repository is not None else None
        self.reminder_advice_service = (ReminderAdviceService(repository, reminder_coordinator, task_service)
                                       if repository is not None and reminder_coordinator is not None else None)
        self._reminder_advice_dialog = None
        self.assistant_service = (AssistantService(repository, reminder_coordinator, task_service,
                                                  local_ai_service, cloud_ai_service)
                                  if self.reminder_advice_service is not None and task_service is not None else None)
        self._assistant_dialog = None
        self.lab_reading_service = LabReadingService(repository, local_ai_service, cloud_ai_service) if repository is not None else None
        self._lab_dialog = None
        self._allow_close = False
        self._shutting_down = False
        self.reminder_popup = ReminderPopup()
        self._desktop_event_id = None
        self.setWindowTitle("DeskCare")
        self.setWindowIcon(build_tray_icon())
        self.setMinimumSize(QSize(1040, 680))
        self.resize(1180, 760)
        self._build_ui()
        self._apply_style()
        monitoring_controller.subscribe(self._sync_header)
        self._sync_header(monitoring_controller.enabled, monitoring_controller.paused)

    def _build_ui(self) -> None:
        shell = QWidget()
        shell.setObjectName("appShell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(222)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(18, 28, 18, 22)
        sidebar_layout.setSpacing(16)
        brand = QLabel("DeskCare")
        brand.setObjectName("brand")
        sidebar_layout.addWidget(brand)
        sidebar_layout.addSpacing(18)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        entries = (
            ("今日任务", "安排今天与休息", "tasks"),
            ("使用统计", "电脑使用情况", "usage"),
            ("状态与记录", "每日打卡与自愿不适记录", "status"),
            ("日报与周报", "查看记录与回顾", "report"),
            ("设置与隐私", "管理功能与数据", "settings"),
        )
        for title, subtitle, icon in entries:
            item = QListWidgetItem(title)
            item.setToolTip(subtitle)
            item.setIcon(navigation_icon(icon))
            item.setSizeHint(QSize(160, 48))
            self.navigation.addItem(item)
        self.navigation.setIconSize(QSize(20, 20))
        self.navigation.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.navigation.currentRowChanged.connect(self._switch_page)
        sidebar_layout.addWidget(self.navigation, 1)
        version = QLabel("DeskCare · UI17")
        version.setObjectName("sidebarFooter")
        sidebar_layout.addWidget(version)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 26, 28, 22)
        content_layout.setSpacing(18)
        header = QHBoxLayout()
        self.header_title = QLabel("今日")
        self.header_title.setObjectName("headerTitle")
        header.addWidget(self.header_title)
        header.addStretch()
        self.lab_button = QPushButton("检验单阅读")
        self.lab_button.setObjectName("secondaryButton")
        self.lab_button.setEnabled(self.lab_reading_service is not None)
        self.lab_button.clicked.connect(self._open_lab)
        header.addWidget(self.lab_button)
        self.assistant_button = QPushButton("AI 助手")
        self.assistant_button.setObjectName("secondaryButton")
        self.assistant_button.setEnabled(self.assistant_service is not None)
        self.assistant_button.clicked.connect(self._open_assistant)
        header.addWidget(self.assistant_button)
        self.header_state = QLabel()
        self.header_state.setObjectName("headerState")
        header.addWidget(self.header_state)
        content_layout.addLayout(header)

        self.demo_banner = QLabel()
        self.demo_banner.setObjectName("demoBanner")
        self.demo_banner.setWordWrap(True)
        demo_mode = bool(getattr(self.monitoring_controller, "provider_is_demo", False))
        if demo_mode:
            scenario = (
                self.repository is not None
                and self.repository.get_setting("demo_scenario") == "true"
            )
            self.demo_banner.setText(
                "演示模式：这里显示的是虚构示例，不是这台电脑的真实使用记录。"
                + ("任务、休息提醒和状态记录也都是预先生成的演示内容。" if scenario else "")
            )
        self.demo_banner.setVisible(demo_mode)
        content_layout.addWidget(self.demo_banner)

        self.pages = QStackedWidget()
        self.today_page = TodayPage(
            self.monitoring_controller,
            self.task_service,
            self.reminder_coordinator,
            self.local_ai_service,
            self.repository,
            self.cloud_ai_service,
        )
        self.pages.addWidget(self.today_page)
        self.today_page.task_scope.currentTextChanged.connect(
            lambda text: self.header_title.setText(text) if self.navigation.currentRow() == 0 else None
        )
        self.usage_page = UsagePage(self.monitoring_controller, self.activity_collector)
        self.pages.addWidget(self.usage_page)
        self.reports_page = ReportsPage(
            self.monitoring_controller,
            self.repository,
            self.bodylog_service,
            self.report_service,
            self.local_ai_service,
            health_journal_service=self.health_journal_service,
        )
        self.reports_page.sections.tabBar().hide()
        self.reports_page.open_settings_requested.connect(self._open_wellness_settings)
        self.reports_page.journal_page.task_created.connect(self._show_journal_task)
        self.pages.addWidget(self.reports_page)
        self.settings_page = SettingsPage(
            self.config_store,
            self.monitoring_controller,
            self.activity_collector,
            self.bodylog_service,
            self.local_ai_service,
            self.personalization_service,
            self.repository,
            self.cloud_ai_service,
        )
        self.settings_page.companion_visibility_changed.connect(self.set_companion_visible)
        self.settings_page.all_data_cleared.connect(self._refresh_after_data_clear)
        self.pages.addWidget(self.settings_page)
        if self.task_service is not None:
            self.task_service.subscribe(self.reports_page.notify_data_changed)
        if self.activity_collector is not None:
            self.activity_collector.subscribe(lambda _result: self.reports_page.notify_data_changed())
        if self.reminder_coordinator is not None:
            self.reminder_coordinator.subscribe(lambda _snapshot: self.reports_page.notify_data_changed())
            self.settings_page.reminder_interval_changed.connect(self.reminder_coordinator.set_interval)
            self.reminder_popup.response_requested.connect(self.reminder_coordinator.respond)
            self.reminder_coordinator.subscribe(self._sync_desktop_reminder)
        self.settings_page.test_reminder_requested.connect(self._preview_reminder)
        self.settings_page.open_journal_requested.connect(self._open_health_journal)
        self.settings_page.reminder_advice_requested.connect(self._open_reminder_advice)
        self.today_page.reminder_advice_requested.connect(self._open_reminder_advice)
        content_layout.addWidget(self.pages)
        self.navigation.setCurrentRow(0)
        shell_layout.addWidget(sidebar)
        shell_layout.addWidget(content, 1)
        self.setCentralWidget(shell)
        self.companion = CompanionWindow(
            self.task_service, self.reminder_coordinator, self.repository,
            bodylog_service=self.bodylog_service,
        )
        self.settings_page.companion_style_changed.connect(self.companion.set_presentation)
        self.companion.presentation_changed.connect(self._sync_companion_style)
        self.companion.hide_requested.connect(
            lambda: self.settings_page.companion_enabled.setChecked(False)
        )
        self.companion.open_main_requested.connect(self._show_main_window)
        if self.repository is not None and self.repository.get_setting("companion_enabled", "false") == "true":
            self.companion.show()

    def set_companion_visible(self, visible: bool) -> None:
        if visible:
            self.companion.show()
            self.companion.raise_()
        else:
            self.companion.hide()

    def _preview_reminder(self) -> None:
        if self.reminder_coordinator is not None and self.reminder_coordinator.snapshot.visible:
            self.reminder_popup.present(show_tip=self.settings_page.activity_tips.isChecked())
            return
        self.reminder_popup.present(preview=True, show_tip=self.settings_page.activity_tips.isChecked())

    def _sync_desktop_reminder(self, snapshot) -> None:
        # Any writer (form, AI, assistant) must refresh the same authoritative
        # coordinator value, not only paths that happen to emit a UI signal.
        self._sync_advised_interval(self.reminder_coordinator.policy.config.break_candidate_minutes)
        combo = self.today_page.context_mode
        mode_index = combo.findData(self.reminder_coordinator.mode)
        if combo.currentIndex() != mode_index:
            combo.blockSignals(True)
            combo.setCurrentIndex(mode_index)
            combo.blockSignals(False)
        self.settings_page.reminder_status.setText(self.reminder_coordinator.status_text())
        if not snapshot.visible:
            if not self.reminder_popup.preview:
                self.reminder_popup.hide()
            return
        if snapshot.event_id is not None and snapshot.event_id != self._desktop_event_id:
            self._desktop_event_id = snapshot.event_id
            self.reminder_popup.present(show_tip=self.settings_page.activity_tips.isChecked())

    def _sync_companion_style(self, presentation):
        combo = self.settings_page.companion_style
        combo.blockSignals(True)
        combo.setCurrentIndex(combo.findData(presentation))
        combo.blockSignals(False)

    def _open_wellness_settings(self) -> None:
        self.navigation.setCurrentRow(4)
        self.settings_page.sections.setCurrentIndex(1)

    def _open_health_journal(self) -> None:
        self.navigation.setCurrentRow(2)
        self.reports_page.status_sections.setCurrentIndex(1)

    def _open_reminder_advice(self):
        if self.reminder_advice_service is None:
            return
        if self._reminder_advice_dialog is None:
            advisor = ReminderAIAdvisor(self.reminder_advice_service, self.local_ai_service, self.cloud_ai_service)
            self._reminder_advice_dialog = ReminderAdviceDialog(self.reminder_advice_service, advisor, self)
            self._reminder_advice_dialog.interval_applied.connect(self._sync_advised_interval)
        self._reminder_advice_dialog.begin()

    def _open_assistant(self):
        if self.assistant_service is None:
            return
        if self._assistant_dialog is None:
            self._assistant_dialog = AssistantDialog(self.assistant_service, self)
            self._assistant_dialog.open_view_requested.connect(self._assistant_open_view)
        self._assistant_dialog.begin()

    def _assistant_open_view(self, view):
        if view == "lab":
            self._open_lab()
        elif view == "advice":
            self._open_reminder_advice()
        elif view in {"today", "usage"}:
            self.navigation.setCurrentRow(0 if view == "today" else 1)
            self._show_main_window()
            self._assistant_dialog.hide()

    def _open_lab(self):
        if self.lab_reading_service is None:
            return
        if self._lab_dialog is None:
            self._lab_dialog = LabReadingDialog(self.lab_reading_service, self)
        self._lab_dialog.begin()

    def _sync_advised_interval(self, minutes):
        edit = self.settings_page.reminder_interval
        if edit.value() != minutes:
            edit.blockSignals(True)
            edit.setValue(minutes)
            edit.blockSignals(False)
        self.config_store.config.break_candidate_minutes = minutes

    def _show_journal_task(self, task) -> None:
        self.navigation.setCurrentRow(0)
        self.today_page._show_task(task)

    def _show_main_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _switch_page(self, index: int) -> None:
        if index < 0:
            return
        self.pages.setCurrentIndex((0, 1, 2, 2, 3)[index])
        if index in (2, 3):
            self.reports_page.sections.setCurrentIndex(index - 2)
            if index == 2:
                self.reports_page._sync_bodylog(bool(self.bodylog_service and self.bodylog_service.enabled))
            else:
                self.reports_page.refresh_report()
        self.header_title.setText(self.navigation.item(index).text().splitlines()[0])
        if index == 0:
            self.header_title.setText(self.today_page.task_scope.currentText())

    def _sync_header(self, enabled: bool, paused: bool) -> None:
        if not enabled:
            text, tone = "电脑使用统计未开启", "muted"
        elif paused:
            text, tone = "电脑使用统计已暂停", "warning"
        else:
            text, tone = "电脑使用统计已开启", "active"
        self.header_state.setText(f"●  {text}")
        self.header_state.setProperty("tone", tone)
        self.header_state.style().unpolish(self.header_state)
        self.header_state.style().polish(self.header_state)

    def _refresh_after_data_clear(self) -> None:
        if self.lab_reading_service is not None:
            self.lab_reading_service.clear()
        if self._lab_dialog is not None:
            self._lab_dialog.reject()
            self._lab_dialog.begin_state()
        if self.assistant_service is not None:
            self.assistant_service.invalidate()
        if self._assistant_dialog is not None:
            self._assistant_dialog.reject()
        if self._reminder_advice_dialog is not None:
            self._reminder_advice_dialog.reject()
        if self.reminder_coordinator is not None:
            self.reminder_coordinator.reset_after_data_clear()
        self.settings_page.reminder_interval.blockSignals(True)
        self.settings_page.reminder_interval.setValue(40)
        self.settings_page.reminder_interval.blockSignals(False)
        self.config_store.config.break_candidate_minutes = 40
        self.today_page.refresh_tasks()
        self.reports_page.refresh_report()
        if self.health_journal_service is not None:
            self.health_journal_service.notify()
        self.companion.hide()
        self.settings_page.companion_enabled.setChecked(False)
        self.companion.set_presentation("panel", persist=False)

    def _apply_style(self) -> None:
        apply_theme(QApplication.instance())
        font = QFont()
        font.setFamilies(["Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "Noto Sans CJK SC"])
        font.setPointSize(10)
        self.setFont(font)
        self.setStyleSheet(STYLE)

    def request_quit(self) -> None:
        self._allow_close = True
        self.shutdown_background_work()
        QApplication.quit()

    def shutdown_background_work(self) -> None:
        """Finish bounded local-model workers before Qt destroys their owners."""

        if self._shutting_down:
            return
        self._shutting_down = True
        try:
            self.reminder_popup.hide()
            companion = getattr(self, "companion", None)
            if companion is not None:
                companion.hide()
            threads = [thread for thread in self.findChildren(QThread) if thread.isRunning()]
            # quit() is thread-safe and lets each event loop stop as soon as
            # its current bounded local request returns. Calling it before
            # wait() avoids relying on queued GUI-thread slots during exit.
            for thread in threads:
                thread.requestInterruption()
                thread.quit()
            for thread in threads:
                thread.wait()
        finally:
            self._shutting_down = False

    def closeEvent(self, event) -> None:
        if self._allow_close:
            self.shutdown_background_work()
            self.reminder_popup.close()
            event.accept()
            return
        tray = getattr(self, "tray_controller", None)
        if tray is not None and tray.available:
            self.hide()
            event.ignore()
        else:
            self.shutdown_background_work()
            event.accept()

