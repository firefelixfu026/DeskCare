"""M1 activity session estimation and daily category aggregation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from collections.abc import Callable

from deskcare.domain.types import ActivityKind, ActivitySample
from deskcare.services.consent_service import MonitoringController
from deskcare.storage.database import UsageRepository, UsageRow


@dataclass(frozen=True)
class PollResult:
    sampled: bool
    recorded_seconds: float = 0.0
    discarded_gap_seconds: float = 0.0
    reason: str = ""


def _day_segments(start: datetime, end: datetime, seconds: float) -> list[tuple[date, float]]:
    """Split a short monotonic interval at local midnight."""

    if seconds <= 0:
        return []
    if start.date() == end.date() or end <= start:
        return [(start.date(), seconds)]
    total_wall = (end - start).total_seconds()
    if total_wall <= 0:
        return [(end.date(), seconds)]
    result: list[tuple[date, float]] = []
    cursor = start
    remaining = seconds
    while cursor.date() != end.date():
        next_midnight = datetime.combine(
            cursor.date() + timedelta(days=1), time.min, tzinfo=cursor.tzinfo
        )
        fraction = max(0.0, min(1.0, (next_midnight - cursor).total_seconds() / total_wall))
        segment = min(remaining, seconds * fraction)
        if segment > 0:
            result.append((cursor.date(), segment))
        remaining -= segment
        cursor = next_midnight
    if remaining > 0:
        result.append((end.date(), remaining))
    return result


class ActivityCollector:
    """Turn consent-gated samples into non-identifying daily aggregates."""

    def __init__(
        self,
        controller: MonitoringController,
        repository: UsageRepository,
        *,
        max_interval_s: float = 60.0,
    ) -> None:
        self.controller = controller
        self.repository = repository
        self.max_interval_s = float(max_interval_s)
        self._previous: ActivitySample | None = None
        self._recent_switch = False
        self.continuous_active_seconds = 0.0
        self._listeners: list[Callable[[PollResult], None]] = []
        self.last_result = PollResult(False, reason="not_sampled")
        controller.subscribe(self._on_controller_state)

    def _on_controller_state(self, enabled: bool, paused: bool) -> None:
        if not enabled or paused:
            # A pause/disable is a hard session boundary, even if the next
            # timer tick has not happened yet.
            self.reset_session()

    def subscribe(self, listener: Callable[[PollResult], None]) -> None:
        self._listeners.append(listener)

    def _finish(self, result: PollResult) -> PollResult:
        self.last_result = result
        for listener in tuple(self._listeners):
            listener(result)
        return result

    def notify(self) -> None:
        """Refresh observers after a non-sampling data operation."""

        for listener in tuple(self._listeners):
            listener(self.last_result)

    def reset_session(self) -> None:
        self._previous = None
        self._recent_switch = False
        self.continuous_active_seconds = 0.0

    @property
    def latest_sample(self) -> ActivitySample | None:
        """Expose the latest bounded in-memory observation to M3 only."""

        return self._previous

    def consume_recent_switch(self) -> bool:
        """Return and clear the one-tick foreground-change signal."""

        changed = self._recent_switch
        self._recent_switch = False
        return changed

    def poll_once(self) -> PollResult:
        try:
            sample = self.controller.read_sample_if_allowed()
        except Exception:
            # Keep provider details out of the UI and logs; a failed sample is
            # simply not counted and the next successful sample starts fresh.
            self.reset_session()
            return self._finish(PollResult(False, reason="provider_error"))
        if sample is None:
            self.reset_session()
            return self._finish(PollResult(False, reason="consent_or_pause"))
        self._recent_switch = bool(sample.is_foreground_change)
        if not sample.observation_ok:
            self._previous = sample
            self.continuous_active_seconds = 0.0
            return self._finish(PollResult(True, reason="observation_unavailable"))
        previous = self._previous
        self._previous = sample
        if previous is None:
            self.continuous_active_seconds = 0.0
            return self._finish(PollResult(True, reason="session_started"))
        elapsed = sample.monotonic_s - previous.monotonic_s
        if elapsed <= 0:
            self.continuous_active_seconds = 0.0
            return self._finish(PollResult(True, reason="non_monotonic_sample"))
        if elapsed > self.max_interval_s:
            self.continuous_active_seconds = 0.0
            return self._finish(PollResult(True, discarded_gap_seconds=elapsed, reason="long_gap"))

        if previous.state is ActivityKind.ACTIVE and sample.state is ActivityKind.ACTIVE:
            self.continuous_active_seconds += elapsed
        else:
            self.continuous_active_seconds = 0.0

        if previous.state is ActivityKind.ACTIVE:
            category = previous.app_category or "UNKNOWN"
            kwargs = {"active_seconds": 0.0, "idle_seconds": 0.0, "unknown_seconds": 0.0}
            kwargs["active_seconds"] = elapsed
        elif previous.state is ActivityKind.IDLE:
            category = "IDLE"
            kwargs = {"active_seconds": 0.0, "idle_seconds": elapsed, "unknown_seconds": 0.0}
        else:
            category = "UNKNOWN"
            kwargs = {"active_seconds": 0.0, "idle_seconds": 0.0, "unknown_seconds": elapsed}
        for bucket, duration in _day_segments(previous.wall_time, sample.wall_time, elapsed):
            bucket_kwargs = {key: value * duration / elapsed for key, value in kwargs.items()}
            self.repository.add_usage(bucket, category, **bucket_kwargs)
        return self._finish(PollResult(True, recorded_seconds=elapsed, reason="recorded"))

    def usage_for_day(self, day: date | str | None = None) -> list[UsageRow]:
        return self.repository.usage_for_day(day)
