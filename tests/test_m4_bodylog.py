from datetime import date

import pytest

from deskcare.domain.types import WellnessLevel
from deskcare.services.bodylog_service import BodyLogService
from deskcare.storage.database import UsageRepository


def test_m4_migration_and_independent_bodylog_consent(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    service = BodyLogService(repository)

    assert service.enabled is False
    assert repository.get_consent("wellness_checkin") is None
    with pytest.raises(PermissionError):
        service.save_today(WellnessLevel.COMFORTABLE, date(2026, 10, 14))

    service.set_enabled(True)
    entry = service.save_today(WellnessLevel.SOME_DISCOMFORT, date(2026, 10, 14))
    assert entry.comfort_level is WellnessLevel.SOME_DISCOMFORT
    assert repository.wellness_for_day(date(2026, 10, 14)) == entry

    service.delete_today(date(2026, 10, 14))
    assert repository.wellness_for_day(date(2026, 10, 14)) is None
    service.save_today(WellnessLevel.PREFER_NOT_TO_SAY, date(2026, 10, 14))
    service.clear_all()
    assert repository.wellness_entries_for_period(date(2026, 10, 1), date(2026, 10, 31)) == []

    with repository._connect() as connection:
        versions = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert 4 in versions
    assert "wellness_entries" in tables
