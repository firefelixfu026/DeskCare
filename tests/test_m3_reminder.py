from datetime import datetime, timedelta, timezone

from deskcare.domain.types import ActivityKind, ActivitySample, BreakAction
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.services.reminder_service import ReminderCoordinator
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository


def _active_sample(at: datetime) -> ActivitySample:
    return ActivitySample(
        monotonic_s=100.0,
        wall_time=at,
        idle_s=0.0,
        app_category="CODE",
        state=ActivityKind.ACTIVE,
        is_foreground_change=True,
        observation_ok=True,
    )


def _coordinator(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    controller = MonitoringController(FakeActivityProvider(), initially_enabled=True)
    collector = ActivityCollector(controller, repository)
    task_service = TaskService(repository)
    coordinator = ReminderCoordinator(controller, collector, task_service, repository)
    return repository, controller, collector, coordinator


def test_coordinator_persists_soft_notification_and_feedback(tmp_path):
    repository, _controller, collector, coordinator = _coordinator(tmp_path)
    now = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    collector._previous = _active_sample(now)
    collector.continuous_active_seconds = 45 * 60

    snapshot = coordinator.evaluate(now=now, is_recent_switch=True)

    assert snapshot.visible is True
    assert snapshot.decision.action is BreakAction.SOFT_NOTIFY
    event = repository.latest_reminder_event()
    assert event is not None
    assert event.response is None
    assert event.active_minutes == 45

    coordinator.respond("BAD_TIMING", now=now + timedelta(seconds=1))
    event = repository.latest_reminder_event()
    assert event is not None
    assert event.response == "BAD_TIMING"
    assert event.response_at == now + timedelta(seconds=1)

    collector._previous = _active_sample(now + timedelta(minutes=1))
    after_feedback = coordinator.evaluate(now=now + timedelta(minutes=1))
    assert after_feedback.visible is False
    assert after_feedback.decision.reason_codes == ("COOLDOWN",)


def test_coordinator_hard_gates_consent_and_pause(tmp_path):
    _repository, controller, collector, coordinator = _coordinator(tmp_path)
    now = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    collector._previous = _active_sample(now)
    collector.continuous_active_seconds = 45 * 60

    controller.set_paused(True)
    snapshot = coordinator.evaluate(now=now)
    assert snapshot.visible is False
    assert snapshot.decision.reason_codes == ("CONSENT_OR_PAUSE",)

    controller.set_paused(False)
    controller.set_enabled(False)
    snapshot = coordinator.evaluate(now=now)
    assert snapshot.visible is False
    assert snapshot.decision.reason_codes == ("CONSENT_OR_PAUSE",)


def test_coordinator_accepts_user_entered_naive_deadline(tmp_path):
    repository, _controller, collector, coordinator = _coordinator(tmp_path)
    now = datetime.now().astimezone().replace(second=0, microsecond=0)
    repository.add_task("临近截止任务", (now + timedelta(minutes=5)).replace(tzinfo=None))
    collector._previous = _active_sample(now)
    # Check within the new five-minute soft-delay window, not at its upper bound.
    collector.continuous_active_seconds = 42 * 60

    snapshot = coordinator.evaluate(now=now, is_recent_switch=True)

    assert snapshot.decision.reason_codes == ("SCHEDULE_OR_FOCUS_CONSTRAINT",)
