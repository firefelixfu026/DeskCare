from datetime import date, datetime
import sqlite3

from deskcare.storage.database import (
    UsageRepository,
    get_default_database_path,
    get_demo_database_path,
)


def test_m1_migration_creates_consent_and_daily_usage_tables(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")

    repository.set_consent("activity_monitoring", True)
    assert repository.get_consent("activity_monitoring") is True
    assert repository.get_consent("wellness") is None

    repository.add_usage(date(2026, 10, 14), "CODE", active_seconds=12.5)
    repository.add_usage(date(2026, 10, 14), "CODE", active_seconds=7.5)
    rows = repository.usage_for_day(date(2026, 10, 14))
    assert len(rows) == 1
    assert rows[0].active_seconds == 20.0

    repository.clear_usage()
    assert repository.usage_for_day(date(2026, 10, 14)) == []
    assert repository.get_consent("activity_monitoring") is True

    with repository._connect() as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
    assert {"schema_migrations", "consents", "usage_daily"} <= tables


def test_v7_migration_adds_empty_decision_context_without_losing_events(tmp_path):
    path = tmp_path / "pre-m7.sqlite3"
    repository = UsageRepository(path)
    from deskcare.domain.types import BreakAction, PolicyDecision

    event = repository.add_reminder_event(
        occurred_at=datetime.now().astimezone(),
        decision=PolicyDecision(BreakAction.SOFT_NOTIFY, ("TEST",), "test", 60),
        mode="normal",
        active_minutes=40,
    )
    with sqlite3.connect(path) as connection:
        connection.execute("ALTER TABLE reminder_events DROP COLUMN decision_context_json")
        connection.execute("DELETE FROM schema_migrations WHERE version = 7")

    migrated = UsageRepository(path).latest_reminder_event()
    assert migrated.id == event.id
    assert migrated.decision_context == {}


def test_demo_database_is_separate_from_normal_database(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    normal = get_default_database_path()
    demo = get_demo_database_path()

    assert demo != normal
    assert demo.parent.name == "demo"
    assert demo.name == "deskcare-demo.sqlite3"
