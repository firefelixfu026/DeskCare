"""Explicitly labelled deterministic provider for M0 demos and tests."""

from datetime import datetime
from time import monotonic

from deskcare.domain.types import ActivityKind, ActivitySample


class FakeActivityProvider:
    """Return safe, synthetic observations without touching the operating system."""

    is_demo = True

    def __init__(self) -> None:
        self.read_count = 0

    def read_sample(self) -> ActivitySample:
        self.read_count += 1
        return ActivitySample(
            monotonic_s=monotonic(),
            wall_time=datetime.now().astimezone(),
            idle_s=8.0,
            app_category="CODE",
            state=ActivityKind.ACTIVE,
            is_foreground_change=False,
            observation_ok=True,
        )

