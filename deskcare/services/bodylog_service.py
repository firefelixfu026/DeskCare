"""M4 BodyLog consent and coarse self-report service."""

from __future__ import annotations

from collections.abc import Callable
from datetime import date

from deskcare.domain.types import WellnessLevel
from deskcare.storage.database import UsageRepository, WellnessEntry


class BodyLogService:
    """Own the independent health self-report permission and local writes.

    BodyLog stores only one coarse, user-authored comfort choice per day. It
    never derives a health value from activity or task data and never writes
    entries while the independent consent is disabled.
    """

    CONSENT_SCOPE = "wellness_checkin"

    def __init__(self, repository: UsageRepository, initially_enabled: bool = False) -> None:
        self.repository = repository
        self._enabled = bool(initially_enabled)
        self._listeners: list[Callable[[bool], None]] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def subscribe(self, listener: Callable[[bool], None]) -> None:
        self._listeners.append(listener)
        listener(self._enabled)

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener(self._enabled)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.repository.set_consent(self.CONSENT_SCOPE, self._enabled)
        self._notify()

    @staticmethod
    def _validate_level(level: WellnessLevel | str) -> WellnessLevel:
        if not isinstance(level, WellnessLevel):
            level = WellnessLevel(str(level))
        return level

    def today_entry(self, day: date | None = None) -> WellnessEntry | None:
        if not self._enabled:
            return None
        return self.repository.wellness_for_day(day or date.today())

    def save_today(
        self,
        level: WellnessLevel | str,
        day: date | None = None,
    ) -> WellnessEntry:
        if not self._enabled:
            raise PermissionError("BodyLog consent is not enabled")
        entry = self.repository.upsert_wellness_entry(day or date.today(), self._validate_level(level))
        self._notify()
        return entry

    def delete_today(self, day: date | None = None) -> None:
        if not self._enabled:
            return
        self.repository.delete_wellness_entry(day or date.today())
        self._notify()

    def clear_all(self) -> None:
        """Delete all self-reported BodyLog entries, retaining consent."""

        self.repository.clear_wellness()
        self._notify()

