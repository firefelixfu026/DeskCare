"""Local-only import review. Similarity is a warning, never an AI merge."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import unicodedata

from deskcare.domain.types import Task, TaskDraft, TaskStatus


def normalized_title(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _stamp(value):
    # Persistence stores local, minute-precision timestamps. An offset-aware
    # import and its local civil equivalent must compare identically.
    return value.astimezone().replace(second=0, microsecond=0).isoformat() if value else None


def _day(task, today):
    return (task.planned_for or (task.starts_at.astimezone().date() if task.starts_at else None)
            or (task.due_at.astimezone().date() if task.due_at else None)
            or (task.confirmed_at.astimezone().date() if isinstance(task, Task) and task.confirmed_at else today))


def import_identity(task, today: date):
    return (normalized_title(task.title), _day(task, today), _stamp(task.due_at),
            _stamp(task.starts_at), _stamp(task.ends_at), normalized_title(task.time_hint))


def _relation(incoming, other, left, right):
    same_title = left[0] == right[0]
    # A bounded, conservative name warning: added/removed words may refer to
    # the same task. Do not use expensive all-pairs semantic/fuzzy matching in
    # an editable table, and never automatically merge different titles.
    if not same_title and not (min(len(left[0]), len(right[0])) >= 4
            and (left[0] in right[0] or right[0] in left[0])
            and 2 * min(len(left[0]), len(right[0])) >= .8 * (len(left[0]) + len(right[0]))):
        return None
    # Explicitly different dates or clock times are separate occurrences.
    explicit_left = incoming.planned_for or incoming.starts_at or incoming.due_at
    explicit_right = other.planned_for or other.starts_at or other.due_at
    if left[1] != right[1] and explicit_left and explicit_right:
        return None
    if any(a is not None and b is not None and a != b for a, b in zip(left[2:5], right[2:5])):
        return None
    adds_notes = bool(incoming.notes.strip() and incoming.notes.strip() != other.notes.strip())
    changes_estimate = (incoming.estimated_minutes is not None and not incoming.estimate_is_suggestion
                        and incoming.estimated_minutes != other.estimated_minutes)
    if same_title and left == right and not adds_notes and not changes_estimate:
        return "duplicate"
    return "possible"


@dataclass(frozen=True)
class ImportMatch:
    kind: str
    message: str
    matched_ids: tuple[int, ...] = ()


def review_import(drafts, existing=(), *, today: date | None = None) -> tuple[ImportMatch, ...]:
    """Include completed tasks, ignore filenames, preserve every original row."""
    today = today or date.today()
    existing = [(task, import_identity(task, today)) for task in existing]
    previous = []
    reviews = []
    labels = {TaskStatus.TODO: "待处理", TaskStatus.DOING: "进行中", TaskStatus.DONE: "已完成"}
    for row, draft in enumerate(drafts, 1):
        identity = import_identity(draft, today)
        candidates = []
        for task, other_identity in existing:
            kind = _relation(draft, task, identity, other_identity)
            if kind:
                candidates.append(ImportMatch(kind,
                    f"{'已存在' if kind == 'duplicate' else '可能重复'} · {labels[task.status]} · {task.title}", (task.id,)))
        for number, other, other_identity in previous:
            kind = _relation(draft, other, identity, other_identity)
            if kind:
                candidates.append(ImportMatch(kind, f"{'本批重复' if kind == 'duplicate' else '本批可能重复'} · 第 {number} 行"))
        reviews.append(next((item for item in candidates if item.kind == "duplicate"),
                            candidates[0] if candidates else ImportMatch("new", "新任务")))
        previous.append((draft.source_row or row, draft, identity))
    return tuple(reviews)
