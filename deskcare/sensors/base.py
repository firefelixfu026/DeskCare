"""Provider contract for bounded activity observations.

M1 selects a bounded Windows provider on Windows and uses the labelled
FakeActivityProvider elsewhere for safe demos and tests.
"""

from typing import Protocol

from deskcare.domain.types import ActivitySample


class ActivityProvider(Protocol):
    """Read one bounded sample only when the consent gate permits it."""

    def read_sample(self) -> ActivitySample: ...

