"""Small, testable configuration and consent state used by M0.

M0 intentionally keeps state in memory. The shape is ready to be backed by
SQLite in M1/M4 without making the UI responsible for persistence.
"""

from dataclasses import dataclass


@dataclass
class AppConfig:
    """User-controlled switches and product parameters.

    All sensitive or observational scopes are opt-in. These defaults are a
    safety property, not merely a UI default.
    """

    activity_monitoring_enabled: bool = False
    app_name_stats_enabled: bool = False
    wellness_checkin_enabled: bool = False
    local_ai_enabled: bool = False
    reminder_personalization_enabled: bool = False
    break_candidate_minutes: int = 40
    max_soft_delay_minutes: int = 20


class ConfigStore:
    """In-memory configuration facade for M0.

    Later milestones can replace this implementation with a SQLite-backed
    repository while keeping the service and UI contract stable.
    """

    def __init__(self, config: AppConfig | None = None) -> None:
        self._config = config or AppConfig()

    @property
    def config(self) -> AppConfig:
        return self._config

