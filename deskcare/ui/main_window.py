"""Main Qt window and page navigation for DeskCare M8."""

from PySide6.QtCore import QSize, QThread, Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from deskcare.ui.pages import ReportsPage, SettingsPage, TodayPage, UsagePage
from deskcare.ui.companion import CompanionWindow
from deskcare.ui.tray import build_tray_icon


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
        self._allow_close = False
        self._shutting_down = False
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
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        sidebar = QFrame()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(246)
        sidebar_layout = QVBoxLayout(sidebar)
        sidebar_layout.setContentsMargins(22, 28, 22, 22)
        sidebar_layout.setSpacing(16)
        brand = QLabel("DeskCare")
        brand.setObjectName("brand")
        sidebar_layout.addWidget(brand)
        tagline = QLabel("陪你把一天过得更清楚")
        tagline.setObjectName("tagline")
        sidebar_layout.addWidget(tagline)
        sidebar_layout.addSpacing(18)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigation")
        for title, subtitle in (("今日", "任务与休息建议"), ("使用统计", "电脑使用情况"), ("状态与报告", "回顾与小结"), ("设置与隐私", "由你选择和管理")):
            item = QListWidgetItem(f"{title}\n{subtitle}")
            item.setSizeHint(QSize(200, 62))
            self.navigation.addItem(item)
        self.navigation.currentRowChanged.connect(self._switch_page)
        sidebar_layout.addWidget(self.navigation)
        sidebar_layout.addStretch()
        version = QLabel("记录留在本机 · 隐私由你掌控")
        version.setObjectName("sidebarFooter")
        sidebar_layout.addWidget(version)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(36, 30, 36, 26)
        content_layout.setSpacing(18)
        header = QHBoxLayout()
        self.header_title = QLabel("今日")
        self.header_title.setObjectName("headerTitle")
        header.addWidget(self.header_title)
        header.addStretch()
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
        self.usage_page = UsagePage(self.monitoring_controller, self.activity_collector)
        self.pages.addWidget(self.usage_page)
        self.reports_page = ReportsPage(
            self.monitoring_controller,
            self.repository,
            self.bodylog_service,
            self.report_service,
            self.local_ai_service,
        )
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
        content_layout.addWidget(self.pages)
        self.navigation.setCurrentRow(0)
        shell_layout.addWidget(sidebar)
        shell_layout.addWidget(content, 1)
        self.setCentralWidget(shell)
        self.companion = CompanionWindow(
            self.task_service, self.reminder_coordinator, self.repository
        )
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

    def _show_main_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def _switch_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        self.header_title.setText(self.navigation.item(index).text().splitlines()[0])

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
        if self.reminder_coordinator is not None:
            self.reminder_coordinator.reset_after_data_clear()
        self.today_page.refresh_tasks()
        self.reports_page.refresh_report()
        self.companion.hide()
        self.settings_page.companion_enabled.setChecked(False)

    def _apply_style(self) -> None:
        for family in ("Microsoft YaHei UI", "Microsoft YaHei", "SimHei", "SimSun", "Segoe UI"):
            if QFontDatabase.hasFamily(family):
                self.setFont(QFont(family))
                break
        self.setStyleSheet(
            """
            QMainWindow, QWidget { background: #F7F5F0; color: #24312E; }
            QFrame#sidebar { background: #E8EFEA; border-right: 1px solid #D7E1DB; }
            QLabel#brand { color: #214F45; font-size: 30px; font-weight: 700; }
            QLabel#tagline, QLabel#sidebarFooter, QLabel#mutedText { color: #71817C; }
            QListWidget#navigation { background: transparent; border: none; outline: none; }
            QListWidget#navigation::item { color: #5D6E68; border-radius: 12px; padding: 10px 12px; margin: 2px 0; }
            QListWidget#navigation::item:selected { color: #214F45; background: #D4E4D9; font-weight: 700; }
            QLabel#headerTitle { color: #214F45; font-size: 28px; font-weight: 700; }
            QLabel#headerState { padding: 8px 13px; border-radius: 14px; background: #E5EBE8; color: #667872; }
            QLabel#headerState[tone="active"] { background: #D7EADD; color: #24624E; }
            QLabel#headerState[tone="warning"] { background: #F5E7CB; color: #94611E; }
            QLabel#statusBadge { padding: 8px 12px; border-radius: 14px; background: #E5EBE8; color: #667872; }
            QLabel#pageLead { color: #62726C; font-size: 15px; }
            QFrame#card { background: #FFFFFF; border: 1px solid #E3E8E4; border-radius: 16px; }
            QFrame#reminderCard { background: #FFF8EA; border: 1px solid #E8D7B5; border-left: 5px solid #D69E52; border-radius: 16px; }
            QLabel#cardTitle { color: #214F45; font-size: 17px; font-weight: 700; }
            QLabel#cardBody { color: #5F6E68; line-height: 1.4; }
            QLabel#contextLabel, QLabel#reminderBody { color: #5F6E68; }
            QLabel#reminderTitle { color: #80571D; font-size: 17px; font-weight: 700; }
            QLabel#reminderReason { color: #967647; font-size: 12px; }
            QPushButton#reminderAction { background: #D69E52; color: #33230E; padding: 8px 12px; }
            QPushButton#reminderAction:hover { background: #C58A3D; }
            QLabel#demoBanner { color: #96611E; background: #F8EEDC; border-radius: 10px; padding: 10px; }
            QPushButton { background: #2F6B5F; color: white; border: none; border-radius: 10px; padding: 10px 16px; }
            QPushButton:hover { background: #25594F; }
            QPushButton:disabled { background: #DCE3DF; color: #81908A; }
            QCheckBox { color: #43534D; padding: 8px 2px; }
            QScrollArea#settingsScroll, QWidget#settingsContent { background: transparent; }
            """
        )

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
            companion = getattr(self, "companion", None)
            if companion is not None:
                companion.stop_voice_input()
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
            event.accept()
            return
        tray = getattr(self, "tray_controller", None)
        if tray is not None and tray.available:
            self.hide()
            event.ignore()
        else:
            self.shutdown_background_work()
            event.accept()

