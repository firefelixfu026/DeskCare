from datetime import datetime, timedelta

from deskcare.demo_scenario import prepare_demo_scenario
from deskcare.storage.database import UsageRepository, get_demo_database_path, get_demo_scenario_database_path


def test_demo_scenario_is_complete_labelled_and_idempotent(tmp_path):
    now = datetime.now().astimezone().replace(hour=14, minute=0, second=0, microsecond=0)
    repository = UsageRepository(tmp_path / "scenario.sqlite3")

    first = prepare_demo_scenario(repository, now)

    assert first["seeded"] is True
    assert first["facts"]["data_quality"]["demo_data"] is True
    assert first["facts"]["tasks"] == {
        "confirmed_total": 2,
        "completed_by_user": 1,
        "open": 1,
    }
    assert first["facts"]["usage"]["active_minutes_estimate"] == 40.0
    assert first["facts"]["reminders"]["shown"] == 1
    assert first["facts"]["reminders"]["snoozed"] == 1
    assert first["facts"]["wellness"]["recorded_days"] == 1
    assert "# 【演示数据】DeskCare 日报" in first["report"]
    assert "不是本机真实记录" in first["report"]
    assert "未使用 AI" in first["report"]

    second = prepare_demo_scenario(repository, now + timedelta(minutes=1))

    assert second["seeded"] is False
    assert second["facts"]["tasks"]["confirmed_total"] == 2
    assert second["facts"]["reminders"]["shown"] == 1
    assert len(repository.tasks_for_day(now.date())) == 2


def test_scenario_database_is_separate_from_normal_demo_and_user_data(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    scenario_path = get_demo_scenario_database_path()

    assert scenario_path.parent == tmp_path / "DeskCare" / "demo"
    assert scenario_path != get_demo_database_path()
    assert scenario_path.name.startswith("scenario-")
    assert not (tmp_path / "DeskCare" / "deskcare.sqlite3").exists()


def test_demo_scenario_keeps_full_activity_in_today_report_around_midnight(tmp_path):
    shortly_after_midnight = datetime.now().astimezone().replace(
        hour=0, minute=15, second=0, microsecond=0
    )
    repository = UsageRepository(tmp_path / "midnight-scenario.sqlite3")

    result = prepare_demo_scenario(repository, shortly_after_midnight)

    assert result["facts"]["usage"]["active_minutes_estimate"] == 40.0
    today_rows = repository.usage_for_day(shortly_after_midnight.date())
    previous_day = shortly_after_midnight.date() - timedelta(days=1)
    previous_day_rows = repository.usage_for_day(previous_day)
    assert sum(row.active_seconds for row in today_rows) == 40 * 60
    assert previous_day_rows == []
