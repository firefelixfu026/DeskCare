"""Qt application assembly for the M7 DeskCare shell."""

import os
import sys

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from deskcare.config import ConfigStore
from deskcare.ai.optional_local_llm import LocalAIService
from deskcare.ai.cloud_task_assistant import CloudTaskAssistant
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.sensors.windows import WindowsActivityProvider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.bodylog_service import BodyLogService
from deskcare.services.consent_service import MonitoringController
from deskcare.services.reminder_service import ReminderCoordinator
from deskcare.services.personalization_service import ReminderPersonalizationService
from deskcare.services.report_engine import LocalReportService
from deskcare.services.task_service import TaskService
from deskcare.demo_scenario import prepare_demo_scenario
from deskcare.storage.database import (
    UsageRepository,
    get_default_database_path,
    get_demo_database_path,
    get_demo_scenario_database_path,
)
from deskcare.runtime import SingleInstanceGuard
from deskcare.ui.main_window import MainWindow
from deskcare.ui.tray import TrayController
from deskcare.ui.theme import apply_theme


def _build_provider(demo_requested: bool, *, include_app_name: bool = False):
    if demo_requested or os.name != "nt":
        return FakeActivityProvider()
    return WindowsActivityProvider(include_category=True, include_app_name=include_app_name)


def create_application(argv: list[str] | None = None):
    # Reuse an existing QApplication when the shell is embedded by a test or
    # another local tool; normal ``python -m deskcare`` still creates it here.
    raw_argv = list(sys.argv if argv is None else argv)
    demo_requested = "--demo" in raw_argv
    demo_scenario_requested = "--demo-scenario" in raw_argv
    demo_mode = demo_requested or demo_scenario_requested or os.name != "nt"
    qt_argv = [item for item in raw_argv if item not in {"--demo", "--demo-scenario"}] or ["deskcare"]
    qt_app = QApplication.instance() or QApplication(qt_argv)
    apply_theme(qt_app)
    qt_app.setApplicationName("DeskCare")
    qt_app.setApplicationVersion("2.0.0-ui16")
    instance_guard = SingleInstanceGuard(parent=qt_app)
    if not instance_guard.primary:
        return qt_app, None, None
    config_store = ConfigStore()
    if demo_scenario_requested:
        database_path = get_demo_scenario_database_path()
    elif demo_mode:
        database_path = get_demo_database_path()
    else:
        database_path = get_default_database_path()
    repository = UsageRepository(database_path)
    if demo_mode:
        repository.set_setting("demo_mode", "true")
    if demo_scenario_requested:
        prepare_demo_scenario(repository)
    saved_app_name_consent = repository.get_consent("app_name_stats") is True
    config_store.config.app_name_stats_enabled = saved_app_name_consent
    saved_consent = repository.get_consent("activity_monitoring")
    initially_enabled = (
        config_store.config.activity_monitoring_enabled
        if saved_consent is None
        else saved_consent
    )
    config_store.config.activity_monitoring_enabled = initially_enabled
    saved_wellness_consent = repository.get_consent("wellness_checkin")
    initially_wellness_enabled = saved_wellness_consent is True
    config_store.config.wellness_checkin_enabled = initially_wellness_enabled
    saved_local_ai_consent = repository.get_consent("local_ai")
    initially_local_ai_enabled = saved_local_ai_consent is True
    config_store.config.local_ai_enabled = initially_local_ai_enabled
    provider = _build_provider(demo_mode, include_app_name=saved_app_name_consent)
    controller = MonitoringController(provider, initially_enabled=initially_enabled)
    collector = ActivityCollector(controller, repository)
    task_service = TaskService(repository)
    saved_personalization_consent = repository.get_consent("reminder_personalization")
    initially_personalization_enabled = saved_personalization_consent is True
    config_store.config.reminder_personalization_enabled = initially_personalization_enabled
    personalization_service = ReminderPersonalizationService(
        repository,
        initially_enabled=initially_personalization_enabled,
        data_is_demo=controller.provider_is_demo,
        base_candidate_minutes=config_store.config.break_candidate_minutes,
    )
    reminder_coordinator = ReminderCoordinator(
        controller,
        collector,
        task_service,
        repository,
        personalization_service=personalization_service,
    )
    bodylog_service = BodyLogService(repository, initially_wellness_enabled)
    report_service = LocalReportService(repository)
    local_ai_service = LocalAIService(repository, initially_local_ai_enabled)
    cloud_ai_service = CloudTaskAssistant(repository)
    controller.subscribe(
        lambda enabled, _paused: repository.set_consent("activity_monitoring", enabled)
    )
    window = MainWindow(
        config_store,
        controller,
        collector,
        task_service,
        reminder_coordinator,
        repository,
        bodylog_service,
        report_service,
        local_ai_service,
        personalization_service,
        cloud_ai_service,
    )
    instance_guard.show_requested.connect(
        lambda: (window.show(), window.raise_(), window.activateWindow())
    )
    window.instance_guard = instance_guard
    tray = TrayController(window, controller)
    window.tray_controller = tray
    qt_app.setQuitOnLastWindowClosed(not tray.available)
    sampler = QTimer(window)
    sampler.setInterval(5000)
    def sample_and_evaluate() -> None:
        collector.poll_once()
        reminder_coordinator.evaluate(is_recent_switch=collector.consume_recent_switch())

    sampler.timeout.connect(sample_and_evaluate)
    sampler.start()
    window.activity_collector = collector
    window.task_service = task_service
    window.activity_timer = sampler
    qt_app.aboutToQuit.connect(sampler.stop)
    qt_app.aboutToQuit.connect(window.shutdown_background_work)
    return qt_app, window, tray


def main(argv: list[str] | None = None) -> int:
    app, window, _tray = create_application(argv)
    if window is None:
        return 0
    window.show()
    return app.exec()

