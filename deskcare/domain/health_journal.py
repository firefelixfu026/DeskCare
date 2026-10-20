"""User-authored events only; no clinical inference or activity-derived scores."""

from dataclasses import dataclass
from datetime import datetime

SEVERITY_LABELS = {None: "未填写", "mild": "轻微", "moderate": "中等", "strong": "明显"}
CHANGE_LABELS = {"better": "感觉减轻", "same": "差不多", "worse": "感觉加重", "unsure": "说不准"}


@dataclass(frozen=True)
class HealthEvent:
    id: int
    occurred_at: datetime
    body_area: str
    description: str
    severity: str | None
    duration_minutes: int | None
    notes: str
    created_at: datetime
    updated_at: datetime
    followup_count: int = 0


@dataclass(frozen=True)
class HealthFollowup:
    id: int
    event_id: int
    recorded_at: datetime
    change: str
    note: str


@dataclass(frozen=True)
class LinkedAction:
    id: int
    task_id: int | None
    title: str | None
    status: str | None
