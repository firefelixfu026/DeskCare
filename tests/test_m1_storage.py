from datetime import date

from deskcare.storage.database import UsageRepository


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
