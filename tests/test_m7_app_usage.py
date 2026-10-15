from datetime import date, datetime, timedelta, timezone

import pytest

from deskcare.app import _build_provider
from deskcare.domain.types import ActivityKind, ActivitySample
from deskcare.sensors.windows import _app_id_for_executable
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.storage.database import UsageRepository


class ScriptedProvider:
    is_demo = False

    def __init__(self, samples):
        self.samples = iter(samples)
        self.read_count = 0
        self.app_names_enabled = False

    def read_sample(self):
        self.read_count += 1
        return next(self.samples)

    def set_app_name_enabled(self, enabled):
        self.app_names_enabled = bool(enabled)


def sample(at, offset, app_id):
    return ActivitySample(
        monotonic_s=offset,
        wall_time=at,
        idle_s=0,
        app_category="CODE",
        state=ActivityKind.ACTIVE,
        is_foreground_change=False,
        observation_ok=True,
        app_id=app_id,
    )


def test_app_details_are_not_persisted_without_independent_consent(tmp_path):
    start = datetime(2026, 10, 15, 10, tzinfo=timezone.utc)
    provider = ScriptedProvider(
        [sample(start, 0, "code"), sample(start + timedelta(seconds=10), 10, "code")]
    )
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    collector = ActivityCollector(MonitoringController(provider, initially_enabled=True), repository)

    collector.poll_once()
    collector.poll_once()

    assert repository.app_usage_for_period(start.date(), start.date()) == []


def test_app_usage_is_aggregated_by_day_and_revocation_deletes_it(tmp_path):
    first = datetime(2026, 10, 15, 23, 59, 55, tzinfo=timezone.utc)
    provider = ScriptedProvider(
        [
            sample(first, 0, "code"),
            sample(first + timedelta(seconds=10), 10, "chrome"),
            sample(first + timedelta(seconds=20), 20, "chrome"),
        ]
    )
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    repository.set_consent("app_name_stats", True)
    collector = ActivityCollector(MonitoringController(provider, initially_enabled=True), repository)

    for _ in range(3):
        collector.poll_once()

    rows = repository.app_usage_for_period(date(2026, 10, 15), date(2026, 10, 16))
    assert [(row.app_id, row.active_seconds) for row in rows] == [("chrome", 10.0), ("code", 10.0)]
    assert {row.app_id: row.active_seconds for row in repository.app_usage_for_period(
        date(2026, 10, 15), date(2026, 10, 15)
    )} == {"code": 5.0}

    collector.set_app_name_enabled(False)

    assert repository.get_consent("app_name_stats") is False
    assert repository.app_usage_for_period(date(2026, 10, 15), date(2026, 10, 16)) == []
    assert provider.app_names_enabled is False


def test_app_identity_is_a_normalized_executable_stem_only():
    assert _app_id_for_executable(r"C:\Program Files\Google\Chrome\chrome.exe") == "chrome"
    assert _app_id_for_executable(r"C:\Apps\哔哩哔哩.exe") == "哔哩哔哩"
    assert _app_id_for_executable(r"C:\Users\private\Tool With Spaces.exe") is None
    assert _app_id_for_executable(None) is None


def test_repository_rejects_path_like_app_ids_and_clear_usage_clears_both_levels(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    with pytest.raises(ValueError):
        repository.add_app_usage(date(2026, 10, 15), r"C:\private\secret.exe", 5)
    repository.add_usage(date(2026, 10, 15), "CODE", active_seconds=5)
    repository.add_app_usage(date(2026, 10, 15), "code", 5)

    repository.clear_usage()

    assert repository.usage_for_day(date(2026, 10, 15)) == []
    assert repository.app_usage_for_period(date(2026, 10, 15), date(2026, 10, 15)) == []


def test_demo_provider_does_not_enable_app_identity_collection():
    provider = _build_provider(True, include_app_name=True)
    assert provider.is_demo is True


def test_settings_app_details_opt_in_and_revoke_clear_only_app_rows(tmp_path):
    from PySide6.QtWidgets import QApplication

    from deskcare.config import ConfigStore
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.ui.pages import SettingsPage

    app = QApplication.instance() or QApplication([])
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    controller = MonitoringController(FakeActivityProvider())
    collector = ActivityCollector(controller, repository)
    page = SettingsPage(ConfigStore(), controller, collector)

    page.app_names.setChecked(True)
    assert repository.get_consent("app_name_stats") is True
    repository.add_app_usage(date.today(), "chrome", 60)
    page.app_names.setChecked(False)

    assert repository.get_consent("app_name_stats") is False
    assert repository.app_usage_for_period(date.today(), date.today()) == []
    assert page.config_store.config.app_name_stats_enabled is False
    page.close()


def test_activity_suggestion_preference_is_saved(tmp_path):
    from PySide6.QtWidgets import QApplication

    from deskcare.config import ConfigStore
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.ui.pages import SettingsPage

    app = QApplication.instance() or QApplication([])
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    controller = MonitoringController(FakeActivityProvider())
    page = SettingsPage(ConfigStore(), controller, ActivityCollector(controller, repository))

    assert page.activity_tips.isChecked() is True
    page.activity_tips.setChecked(False)

    assert repository.get_setting("activity_tips_enabled") == "false"
    page.close()
