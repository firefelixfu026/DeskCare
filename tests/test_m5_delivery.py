import importlib.util
from datetime import date
from pathlib import Path

import pytest

from deskcare.domain.types import WellnessLevel
from deskcare.runtime import SingleInstanceGuard
from deskcare.services.bodylog_service import BodyLogService
from deskcare.storage.database import UsageRepository


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_clear_all_data_removes_records_and_consents(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    repository.set_consent("activity_monitoring", True)
    repository.set_consent("wellness_checkin", True)
    repository.set_consent("reminder_personalization", True)
    repository.set_setting("local_ai_model", "qwen2.5:7b")
    repository.add_usage(date(2026, 10, 14), "CODE", active_seconds=30)
    BodyLogService(repository, True).save_today(WellnessLevel.COMFORTABLE, date(2026, 10, 14))

    repository.clear_all_data()

    assert repository.get_consent("activity_monitoring") is None
    assert repository.get_consent("wellness_checkin") is None
    assert repository.get_consent("reminder_personalization") is None
    assert repository.get_setting("local_ai_model") is None
    assert repository.usage_for_day(date(2026, 10, 14)) == []
    assert repository.wellness_for_day(date(2026, 10, 14)) is None


def test_clear_all_data_removes_task_text_from_compacted_database(tmp_path):
    database_path = tmp_path / "deskcare.sqlite3"
    repository = UsageRepository(database_path)
    marker = "DESKCARE-SENSITIVE-MARKER-7F7B0E"
    repository.add_task(marker)
    assert marker.encode("utf-8") in database_path.read_bytes()

    repository.clear_all_data()

    assert marker.encode("utf-8") not in database_path.read_bytes()
    assert repository.tasks_for_day() == []


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="PySide6 is required")
def test_clear_all_data_refreshes_pages_and_reminder_memory(tmp_path, monkeypatch):
    from datetime import datetime, timedelta

    from PySide6.QtWidgets import QApplication, QMessageBox

    from deskcare.config import ConfigStore
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.activity_service import ActivityCollector
    from deskcare.services.consent_service import MonitoringController
    from deskcare.services.personalization_service import ReminderPersonalizationService
    from deskcare.services.reminder_service import ReminderCoordinator
    from deskcare.services.report_engine import LocalReportService
    from deskcare.services.task_service import TaskService
    from deskcare.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    controller = MonitoringController(FakeActivityProvider(), initially_enabled=True)
    collector = ActivityCollector(controller, repository)
    task_service = TaskService(repository)
    task_service.add_manual("清除后不应留在界面")
    personalization = ReminderPersonalizationService(repository)
    reminder = ReminderCoordinator(
        controller,
        collector,
        task_service,
        repository,
        personalization_service=personalization,
    )
    reminder._last_response = "SNOOZE_10_MIN"
    reminder._postpone_until = datetime.now().astimezone() + timedelta(minutes=10)
    window = MainWindow(
        ConfigStore(),
        controller,
        collector,
        task_service,
        reminder,
        repository,
        report_service=LocalReportService(repository),
        personalization_service=personalization,
    )
    assert window.today_page.task_table.rowCount() == 1
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *args, **kwargs: QMessageBox.StandardButton.Yes,
    )

    window.settings_page._clear_all_data()
    app.processEvents()

    assert window.today_page.task_table.rowCount() == 0
    assert "已确认任务 0 项" in window.reports_page.report_text.toPlainText()
    assert reminder._postpone_until is None
    assert reminder._last_response is None
    assert personalization.snapshot.sample_count == 0
    assert controller.enabled is False


def test_baseline_script_is_deterministic_and_does_not_claim_a_winner():
    from scripts.run_baseline import run

    payload = run()
    assert payload["conditions"]["input"] == "synthetic scenarios only"
    assert "claim" in payload["conditions"]["interpretation"]
    assert payload["counts"]["fixed_soft_notifications"] == 6
    assert payload["counts"]["adaptive_soft_notifications"] == 2
    assert len(payload["rows"]) == 7


def test_windows_build_can_verify_the_frozen_qt_package():
    build_script = (PROJECT_ROOT / "scripts" / "build_windows.ps1").read_text(encoding="utf-8")
    verification_script = (
        PROJECT_ROOT / "scripts" / "verify_windows_package.ps1"
    ).read_text(encoding="utf-8")

    assert "[switch]$Verify" in build_script
    assert "$env:PATH = @(" in build_script
    assert "verify_windows_package.ps1" in build_script
    assert 'MainWindowTitle -eq "DeskCare"' in verification_script
    assert 'MainWindowTitle -match "Unhandled exception"' in verification_script
    assert "$env:LOCALAPPDATA = $smokeData" in verification_script


@pytest.mark.skipif(importlib.util.find_spec("PySide6") is None, reason="PySide6 is required")
def test_single_instance_guard_rejects_second_process_name():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    name = "DeskCare-test-single-instance"
    first = SingleInstanceGuard(name, app)
    second = SingleInstanceGuard(name, app)
    assert first.primary is True
    assert second.primary is False
    if first.server is not None:
        first.server.close()
    from PySide6.QtNetwork import QLocalServer

    QLocalServer.removeServer(name)
