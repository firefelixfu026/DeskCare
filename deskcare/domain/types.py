"""Shared data contracts for activity, tasks and future policy services."""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class ActivityKind(str, Enum):
    ACTIVE = "active"
    IDLE = "idle"
    UNKNOWN = "unknown"


class BreakAction(str, Enum):
    NONE = "none"
    SOFT_NOTIFY = "soft_notify"
    DEFER = "defer"


class TaskStatus(str, Enum):
    TODO = "todo"
    DOING = "doing"
    DONE = "done"


class WellnessLevel(str, Enum):
    """A coarse, user-entered comfort signal; never a medical measurement."""

    COMFORTABLE = "comfortable"
    SOME_DISCOMFORT = "some_discomfort"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


WELLNESS_LEVEL_LABELS = {
    WellnessLevel.COMFORTABLE: "无明显不适",
    WellnessLevel.SOME_DISCOMFORT: "有些不适",
    WellnessLevel.PREFER_NOT_TO_SAY: "不想记录",
}


@dataclass(frozen=True)
class Task:
    """A user-confirmed task.

    A ``Task`` is intentionally separate from :class:`TaskDraft`: drafts are
    disposable preview data and must never be used by policy code before the
    user confirms them.
    """

    id: int
    title: str
    due_at: datetime | None = None
    estimated_minutes: int | None = None
    status: TaskStatus = TaskStatus.TODO
    confirmed_at: datetime | None = None
    completed_at: datetime | None = None
    source: str = "manual"


@dataclass(frozen=True)
class ActivitySample:
    """A bounded activity observation; no keyboard content or window title."""

    monotonic_s: float
    wall_time: datetime
    idle_s: float | None
    app_category: str | None
    state: ActivityKind
    is_foreground_change: bool
    observation_ok: bool
    app_id: str | None = None


@dataclass(frozen=True)
class TaskDraft:
    """A future importer output that is not persisted until user confirmation."""

    title: str
    due_at: datetime | None = None
    estimated_minutes: int | None = None
    source_row: int | None = None
    uncertainty: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicyContext:
    """Policy input contract for the pure M3 break decision."""

    monitored: bool
    mode: str
    continuous_active_minutes: float
    idle_seconds: float | None
    is_recent_switch: bool
    next_confirmed_deadline: datetime | None
    now: datetime
    last_prompt_at: datetime | None = None
    last_response: str | None = None
    manual_pause: bool = False
    observation_is_unknown: bool = False
    just_confirmed_task_done: bool = False
    postpone_until: datetime | None = None
    last_feedback_at: datetime | None = None


@dataclass(frozen=True)
class PolicyDecision:
    """Policy output contract reserved for M3."""

    action: BreakAction
    reason_codes: tuple[str, ...]
    human_explanation: str
    next_check_in_seconds: int

