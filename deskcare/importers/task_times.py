"""Explicit task dates/times. Ambiguous text remains visible, never discarded."""

from dataclasses import replace
from datetime import date, datetime, time, timedelta
import re
import unicodedata
from collections import Counter

from deskcare.domain.types import TaskDraft

HEADING = re.compile(r"^(?:(\d{4})[-/.年])?(\d{1,2})[./月-](\d{1,2})日?\s*$")
CLOCK = r"\d{1,2}\s*:\s*\d{2}"
RANGE = re.compile(r"(?:(\d{4}-\d{2}-\d{2})[ T])?" + rf"({CLOCK})\s*[-~–—至]\s*"
                   + r"(?:(\d{4}-\d{2}-\d{2})[ T])?" + rf"({CLOCK})")
DEADLINE = re.compile(r"(?:ddl|deadline|截止(?:时间)?)\s*[:：]?\s*(?:(\d{4}-\d{2}-\d{2})[ T])?" + rf"({CLOCK})", re.I)
DATE_RANGE = re.compile(r"(?<!\d)(\d{4}-\d{2}-\d{2})\s*(?:至|到|~|～|—|–|-)\s*(\d{4}-\d{2}-\d{2})(?!\d)")
ESTIMATE = re.compile(r"(?<![\d.])(?:预计|耗时|用时)?\s*(-?\d{1,5}(?:\.\d+)?)\s*(分钟|minutes?|mins?|小时|hours?|hrs?|h)(?![a-z])", re.I)


def heading_day(text: str, reference: date) -> tuple[date | None, bool]:
    match = HEADING.fullmatch(unicodedata.normalize("NFKC", text).lstrip("# ").strip())
    if not match:
        return None, False
    try:
        return date(int(match[1] or reference.year), int(match[2]), int(match[3])), match[1] is None
    except ValueError:
        return None, False


def clock_at(value: str, day: date) -> datetime:
    hour, minute = (int(part.strip()) for part in value.split(":"))
    if hour == 24 and minute == 0:
        return datetime.combine(day + timedelta(days=1), time.min)
    return datetime.combine(day, time(hour, minute))


def task_time_text(task) -> str:
    if task.starts_at:
        value = task.starts_at.strftime("%Y-%m-%d %H:%M" if task.planned_for and task.starts_at.date() != task.planned_for else "%H:%M")
        if task.ends_at:
            value += "–" + task.ends_at.strftime("%Y-%m-%d %H:%M" if task.ends_at.date() > task.starts_at.date() else "%H:%M")
        return value
    if task.due_at:
        day = task.planned_for
        value = ("24:00" if day and task.due_at.date() == day + timedelta(days=1)
                 and task.due_at.time().replace(tzinfo=None) == time.min else task.due_at.strftime("%H:%M"))
        if day and task.due_at.date() != day and value != "24:00":
            value = task.due_at.strftime("%Y-%m-%d %H:%M")
        return "截止 " + value
    return task.time_hint or ""


def split_task_time(title: str, planned_for: date | None, reference: date) -> TaskDraft:
    cleaned = unicodedata.normalize("NFKC", title).strip()
    due = starts = ends = None
    hints = []
    flags = []
    day = planned_for
    date_span = DATE_RANGE.search(cleaned)
    if date_span:
        try:
            first, last = date.fromisoformat(date_span[1]), date.fromisoformat(date_span[2])
            if last < first:
                raise ValueError("invalid date span")
            day = first
            starts, ends = datetime.combine(first, time.min), datetime.combine(last, time(23, 59))
            cleaned = cleaned[:date_span.start()] + cleaned[date_span.end():]
        except ValueError:
            flags.append("due_time_ambiguous")
            hints.append(date_span[0])
    # Prefix ISO date (optionally with a clock), including ISO's T separator.
    prefix = re.match(r"^(\d{4}-\d{2}-\d{2})(?:[ T](\d{1,2}:\d{2}))?\s+(.+)$", cleaned)
    if prefix:
        try:
            day = date.fromisoformat(prefix[1])
            due = clock_at(prefix[2], day) if prefix[2] else None
            cleaned = prefix[3]
        except ValueError:
            hints.append(prefix[0])
            flags.append("due_time_ambiguous")
    deadline = DEADLINE.search(cleaned)
    span = RANGE.search(cleaned)
    try:
        if deadline:
            deadline_day = date.fromisoformat(deadline[1]) if deadline[1] else day or reference
            due = clock_at(deadline[2], deadline_day)
            day = day or deadline_day
            cleaned = cleaned[:deadline.start()] + cleaned[deadline.end():]
        elif span:
            day = day or reference
            start_day = date.fromisoformat(span[1]) if span[1] else day
            end_day = date.fromisoformat(span[3]) if span[3] else start_day
            starts = clock_at(span[2], start_day)
            ends = clock_at(span[4], end_day)
            if ends < starts:
                ends += timedelta(days=1)
            if ends <= starts:
                raise ValueError("empty time range")
            cleaned = cleaned[:span.start()] + cleaned[span.end():]
        else:
            suffix = re.search(r"[（(]\s*(?:(\d{4}-\d{2}-\d{2})[ T])?" + rf"({CLOCK})\s*[)）]\s*$", cleaned)
            leading = re.match(rf"^({CLOCK})\s+(.+)$", cleaned)
            if suffix:
                day = day or reference
                starts = clock_at(suffix[2], date.fromisoformat(suffix[1]) if suffix[1] else day)
                cleaned = cleaned[:suffix.start()]
            elif leading:
                due = clock_at(leading[1], day or reference)
                cleaned = leading[2]
                flags.append("due_time_ambiguous")
    except ValueError:
        due = starts = ends = None
        hints.append(title)
        cleaned = title
        flags.append("due_time_ambiguous")
    ambiguous = re.search(r"[（(]([^()（）]*(?:暂定|待定|上午|下午|晚上)[^()（）]*)[)）]", cleaned)
    if ambiguous:
        hints.append(ambiguous[1])
        cleaned = cleaned[:ambiguous.start()] + cleaned[ambiguous.end():]
        flags.append("due_time_ambiguous")
    estimate = None
    duration = ESTIMATE.search(cleaned)
    if duration:
        value = float(duration[1]) * (60 if duration[2].casefold() in {"小时", "h", "hr", "hrs", "hour", "hours"} else 1)
        if value.is_integer():
            estimate = int(value)
        else:
            hints.append(duration[0])
            flags.append("model_estimate_needs_confirmation")
        cleaned = cleaned[:duration.start()] + cleaned[duration.end():]
    elif starts and ends and not date_span:
        minutes = int((ends - starts).total_seconds() / 60)
        estimate = minutes if 1 <= minutes <= 1440 else None
    cleaned = re.sub(r"[（(]\s*[)）]", "", cleaned).strip(" -()（）")
    return TaskDraft(cleaned, due, estimate, uncertainty=tuple(flags), planned_for=day,
                     starts_at=starts, ends_at=ends, time_hint="；".join(hints))


def merge_source_times(candidates: list[TaskDraft], source_text: str, filename: str) -> list[TaskDraft]:
    """Source schedule wins; AI estimates are editable suggestions, never facts."""
    from deskcare.importers.text_importer import parse_text_bytes

    rules = list(parse_text_bytes(source_text.encode("utf-8"), filename).drafts)
    if not rules:
        return candidates
    def key(title):
        return re.sub(r"[\W_]", "", title).casefold()
    def score(left, right):
        if left == right:
            return 1.0
        a, b = Counter(left), Counter(right)
        return 2 * sum((a & b).values()) / max(1, len(left) + len(right))
    remaining = list(enumerate(candidates))
    merged = []
    for original in rules:
        ranked = sorted(((score(key(original.title), key(item.title)), index, item)
                         for index, item in remaining), key=lambda entry: entry[0], reverse=True)
        if ranked and ranked[0][0] >= .8 and (len(ranked) == 1 or ranked[0][0] - ranked[1][0] >= .08):
            _, index, model = ranked[0]
            remaining = [(i, item) for i, item in remaining if i != index]
            flags = tuple(flag for flag in model.uncertainty if flag != "model_due_needs_confirmation"
                          or not (original.due_at or original.starts_at))
            merged.append(replace(original, title=original.title,
                estimated_minutes=original.estimated_minutes or model.estimated_minutes,
                estimate_is_suggestion=original.estimated_minutes is None and model.estimated_minutes is not None,
                uncertainty=tuple(dict.fromkeys(original.uncertainty + flags))))
        else:
            # Never let a model omission erase a source task or its time text.
            merged.append(original)
    return merged
