import importlib.util
from datetime import datetime, timedelta, timezone

import pytest

from deskcare.domain.break_policy import BreakPolicyConfig
from deskcare.domain.types import ActivityKind, ActivitySample, BreakAction, PolicyDecision
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.services.personalization_service import ReminderPersonalizationService
from deskcare.services.reminder_service import ReminderCoordinator
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository


def _add_feedback(repository, index: int, response: str, mode: str = "normal") -> None:
    occurred_at = datetime(2026, 10, 1, 9, 0, tzinfo=timezone.utc) + timedelta(hours=index)
    event = repository.add_reminder_event(
        occurred_at=occurred_at,
        decision=PolicyDecision(
            BreakAction.SOFT_NOTIFY,
            ("POSSIBLE_NATURAL_GAP",),
            "测试用轻量提醒",
            300,
        ),
        mode=mode,
        active_minutes=45,
    )
    repository.update_reminder_response(event.id, response, occurred_at + timedelta(seconds=5))


def test_personalization_requires_consent_and_ten_real_feedback_samples(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    for index in range(9):
        _add_feedback(repository, index, "BAD_TIMING")
    service = ReminderPersonalizationService(repository)
    base = BreakPolicyConfig()

    assert service.effective_config(base, "normal") == base
    service.set_enabled(True)

    assert service.snapshot.sample_count == 9
    assert service.snapshot.applied is False
    assert service.effective_config(base, "normal").break_candidate_minutes == 40
    assert "9 条" in service.snapshot.explanation


def test_personalization_is_context_specific_and_only_reduces_frequency(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    for index in range(10):
        response = "BAD_TIMING" if index < 4 else "BREAK_NOW"
        _add_feedback(repository, index, response, "normal")
    service = ReminderPersonalizationService(repository, initially_enabled=True)
    base = BreakPolicyConfig()

    normal = service.refresh("normal")
    assert normal.applied is False
    assert normal.bad_timing_count == 4
    assert normal.suggested_minutes == 50
    assert service.effective_config(base, "normal").break_candidate_minutes == 40

    focus = service.refresh("focus")
    assert focus.applied is False
    assert service.effective_config(base, "focus").break_candidate_minutes == 40
    assert "0/5" in focus.explanation


def test_personalization_reset_preserves_feedback_and_demo_is_ineligible(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    for index in range(10):
        _add_feedback(repository, index, "BAD_TIMING")
    service = ReminderPersonalizationService(repository, initially_enabled=True)

    service.reset_to_default()

    assert service.enabled is False
    assert repository.get_consent("reminder_personalization") is False
    assert len(repository.recent_reminder_events(responded_only=True)) == 10
    demo = ReminderPersonalizationService(
        repository,
        initially_enabled=True,
        data_is_demo=True,
    )
    assert demo.enabled is False
    assert demo.snapshot.eligible is False
    assert "演示数据不会" in demo.snapshot.explanation


def test_personalization_suggests_without_automatically_changing_coordinator_or_hard_gates(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    for index in range(10):
        _add_feedback(
            repository,
            index,
            "BAD_TIMING" if index < 4 else "BREAK_NOW",
        )
    personalization = ReminderPersonalizationService(repository, initially_enabled=True)
    controller = MonitoringController(FakeActivityProvider(), initially_enabled=True)
    collector = ActivityCollector(controller, repository)
    coordinator = ReminderCoordinator(
        controller,
        collector,
        TaskService(repository),
        repository,
        personalization_service=personalization,
    )
    now = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    collector._previous = ActivitySample(
        monotonic_s=100.0,
        wall_time=now,
        idle_s=0.0,
        app_category="CODE",
        state=ActivityKind.ACTIVE,
        is_foreground_change=True,
        observation_ok=True,
    )
    collector.continuous_active_seconds = 42 * 60

    at_original_threshold = coordinator.evaluate(now=now, is_recent_switch=True)
    assert at_original_threshold.visible
    assert coordinator.policy.config.break_candidate_minutes == 40

    controller.set_paused(True)
    collector.continuous_active_seconds = 100 * 60
    paused = coordinator.evaluate(now=now + timedelta(minutes=1), is_recent_switch=True)
    assert paused.decision.reason_codes == ("CONSENT_OR_PAUSE",)


@pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is required",
)
def test_settings_control_updates_consent_and_can_restore_default(tmp_path):
    from PySide6.QtWidgets import QApplication

    from deskcare.config import ConfigStore
    from deskcare.ui.pages import SettingsPage

    app = QApplication.instance() or QApplication([])
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    controller = MonitoringController(FakeActivityProvider())
    collector = ActivityCollector(controller, repository)
    config_store = ConfigStore()
    service = ReminderPersonalizationService(repository)
    page = SettingsPage(
        config_store,
        controller,
        collector,
        personalization_service=service,
    )

    assert page.reminder_personalization.isChecked() is False
    assert page.reminder_personalization.isEnabled() is True
    page.reminder_personalization.setChecked(True)
    app.processEvents()
    assert service.enabled is True
    assert repository.get_consent("reminder_personalization") is True
    assert config_store.config.reminder_personalization_enabled is True

    page.reset_personalization.click()
    app.processEvents()
    assert service.enabled is False
    assert page.reminder_personalization.isChecked() is False
    assert repository.get_consent("reminder_personalization") is False


@pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is required for the settings scroll test",
)
def test_settings_privacy_controls_remain_reachable_in_short_window(tmp_path):
    from PySide6.QtWidgets import QApplication

    from deskcare.config import ConfigStore
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.activity_service import ActivityCollector
    from deskcare.services.consent_service import MonitoringController
    from deskcare.ui.pages import SettingsPage

    app = QApplication.instance() or QApplication([])
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    controller = MonitoringController(FakeActivityProvider())
    page = SettingsPage(
        ConfigStore(),
        controller,
        ActivityCollector(controller, repository),
        personalization_service=ReminderPersonalizationService(repository),
    )
    page.resize(760, 420)
    page.sections.setCurrentIndex(3)
    page.show()
    app.processEvents()

    scroll_bar = page.settings_scroll.verticalScrollBar()
    # Grouped privacy controls can fit without scrolling; either way the
    # destructive action must remain reachable in a short window.
    scroll_bar.setValue(scroll_bar.maximum())
    app.processEvents()
    assert page.clear_all_button.isVisible() is True
    assert page.clear_all_button.mapTo(page.settings_scroll.viewport(), page.clear_all_button.rect().center()).y() > 0
    assert page.clear_all_button.mapTo(page.settings_scroll.viewport(), page.clear_all_button.rect().center()).y() < page.settings_scroll.viewport().height()
