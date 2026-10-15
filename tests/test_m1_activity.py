from datetime import datetime, timedelta, timezone

from deskcare.domain.types import ActivityKind, ActivitySample
from deskcare.app import _build_provider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.sensors.windows import _category_for_executable, _tick_delta_ms
from deskcare.storage.database import UsageRepository


class ScriptedProvider:
    is_demo = False

    def __init__(self, samples):
        self.samples = iter(samples)
        self.read_count = 0

    def read_sample(self):
        self.read_count += 1
        return next(self.samples)


class FailingProvider:
    is_demo = False

    def read_sample(self):
        raise OSError("synthetic provider failure")


def sample(at, *, state=ActivityKind.ACTIVE, category="CODE", monotonic_s=0.0):
    return ActivitySample(
        monotonic_s=monotonic_s,
        wall_time=at,
        idle_s=0.0 if state is ActivityKind.ACTIVE else 120.0,
        app_category=category,
        state=state,
        is_foreground_change=False,
        observation_ok=True,
    )


def test_collector_is_consent_gated_and_splits_midnight(tmp_path):
    tz = timezone.utc
    first = datetime(2026, 10, 14, 23, 59, 40, tzinfo=tz)
    second = first + timedelta(seconds=30)
    provider = ScriptedProvider(
        [sample(first, monotonic_s=10.0), sample(second, monotonic_s=40.0)]
    )
    controller = MonitoringController(provider)
    repository = UsageRepository(tmp_path / "activity.sqlite3")
    collector = ActivityCollector(controller, repository)

    assert collector.poll_once().reason == "consent_or_pause"
    assert provider.read_count == 0
    controller.set_enabled(True)
    assert collector.poll_once().reason == "session_started"
    result = collector.poll_once()

    assert result.recorded_seconds == 30.0
    day_one = repository.usage_for_day("2026-10-14")
    day_two = repository.usage_for_day("2026-10-15")
    assert day_one[0].active_seconds == 20.0
    assert day_two[0].active_seconds == 10.0


def test_collector_drops_long_gaps_and_records_idle_without_calling_it_rest(tmp_path):
    tz = timezone.utc
    first = datetime(2026, 10, 14, 10, 0, tzinfo=tz)
    provider = ScriptedProvider(
        [
            sample(first, monotonic_s=0.0),
            sample(first + timedelta(seconds=61), monotonic_s=61.0),
            sample(first + timedelta(seconds=70), state=ActivityKind.IDLE, monotonic_s=70.0),
            sample(first + timedelta(seconds=80), state=ActivityKind.IDLE, monotonic_s=80.0),
        ]
    )
    controller = MonitoringController(provider, initially_enabled=True)
    repository = UsageRepository(tmp_path / "activity.sqlite3")
    collector = ActivityCollector(controller, repository)

    collector.poll_once()
    gap = collector.poll_once()
    assert gap.reason == "long_gap"
    assert repository.usage_for_day(first.date()) == []
    collector.poll_once()
    collector.poll_once()
    rows = repository.usage_for_day(first.date())
    idle_row = next(row for row in rows if row.category == "IDLE")
    assert idle_row.idle_seconds == 10.0


def test_provider_error_is_visible_and_does_not_escape_the_poll_loop(tmp_path):
    controller = MonitoringController(FailingProvider(), initially_enabled=True)
    collector = ActivityCollector(controller, UsageRepository(tmp_path / "activity.sqlite3"))
    notifications = []
    collector.subscribe(notifications.append)

    result = collector.poll_once()

    assert result.reason == "provider_error"
    assert collector.last_result.reason == "provider_error"
    assert notifications[-1] == result


def test_pause_immediately_breaks_the_session_boundary(tmp_path):
    start = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    provider = ScriptedProvider(
        [sample(start, monotonic_s=0.0), sample(start + timedelta(seconds=10), monotonic_s=10.0)]
    )
    controller = MonitoringController(provider, initially_enabled=True)
    repository = UsageRepository(tmp_path / "activity.sqlite3")
    collector = ActivityCollector(controller, repository)

    assert collector.poll_once().reason == "session_started"
    controller.set_paused(True)
    assert collector.poll_once().reason == "consent_or_pause"
    assert provider.read_count == 1
    controller.set_paused(False)
    assert collector.poll_once().reason == "session_started"
    assert repository.usage_for_day(start.date()) == []


def test_windows_category_mapping_never_returns_the_executable_name():
    assert _category_for_executable(r"C:\Program Files\Microsoft VS Code\Code.exe") == "CODE"
    assert _category_for_executable(r"C:\Program Files\Google\Chrome\chrome.exe") == "BROWSER"
    assert _category_for_executable(r"C:\Tools\private-study-app.exe") == "OTHER"
    assert _category_for_executable(None) == "UNKNOWN"


def test_collector_can_refresh_observers_after_data_clear(tmp_path):
    collector = ActivityCollector(
        MonitoringController(ScriptedProvider([])),
        UsageRepository(tmp_path / "activity.sqlite3"),
    )
    notifications = []
    collector.subscribe(notifications.append)

    collector.notify()

    assert notifications == [collector.last_result]


def test_windows_tick_delta_handles_32_bit_wraparound():
    assert _tick_delta_ms(0x1_0000_0010, 0xFFFF_FFF0) == 32
    assert _tick_delta_ms(12_345, 12_000) == 345


def test_collector_tracks_only_the_current_continuous_active_session(tmp_path):
    start = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    provider = ScriptedProvider(
        [
            sample(start, monotonic_s=0.0),
            sample(start + timedelta(seconds=10), monotonic_s=10.0),
            sample(start + timedelta(seconds=20), state=ActivityKind.IDLE, monotonic_s=20.0),
        ]
    )
    controller = MonitoringController(provider, initially_enabled=True)
    collector = ActivityCollector(controller, UsageRepository(tmp_path / "activity.sqlite3"))

    collector.poll_once()
    collector.poll_once()
    assert collector.continuous_active_seconds == 10.0
    collector.poll_once()
    assert collector.continuous_active_seconds == 0.0


def test_explicit_demo_mode_uses_only_the_labelled_fake_provider():
    provider = _build_provider(True)
    assert provider.is_demo is True
