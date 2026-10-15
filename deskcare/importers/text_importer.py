"""Plain text and Markdown task list importer with conservative parsing."""

from __future__ import annotations

import re
from datetime import date, datetime, time

from deskcare.domain.types import TaskDraft
from deskcare.importers.base import (
    MAX_ESTIMATED_MINUTES,
    MAX_FILE_BYTES,
    MAX_LINE_LENGTH,
    MAX_TASKS_PER_IMPORT,
    ImportIssue,
    ImportResult,
    decode_utf8,
    duplicate_issues,
    validate_title,
)

_CHECKBOX = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)?\[(?: |x|X)\]\s*(.+)$")
_BULLET = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)(.+)$")
_TIME = re.compile(r"^(?P<time>\d{1,2}:\d{2})\s+(.+)$")
_ISO = re.compile(r"^(?P<date>\d{4}-\d{2}-\d{2})(?:[ T](?P<time>\d{1,2}:\d{2}))?\s+(.+)$")
_MINUTES = re.compile(r"\b(?:预计\s*)?(?P<minutes>\d{1,4})\s*(?:分钟|min|mins)\b", re.IGNORECASE)


def _parse_clock(value: str, today: date) -> datetime | None:
    try:
        parsed = time.fromisoformat(value)
    except ValueError:
        return None
    return datetime.combine(today, parsed)


def parse_text_bytes(content: bytes, filename: str = "tasks.txt", *, reference_now: datetime | None = None) -> ImportResult:
    if len(content) > MAX_FILE_BYTES:
        return ImportResult(filename, (), (ImportIssue("file_too_large", "文件超过 1 MB，未读取。"),))
    text, decode_issues = decode_utf8(content)
    if text is None:
        return ImportResult(filename, (), decode_issues)
    if not text.strip():
        return ImportResult(filename, (), (ImportIssue("empty_file", "文件为空，没有可预览的任务。"),))
    if any(len(line) > MAX_LINE_LENGTH for line in text.splitlines()):
        return ImportResult(filename, (), (ImportIssue("line_too_long", f"每行不能超过 {MAX_LINE_LENGTH} 个字符。"),))

    now = reference_now or datetime.now().astimezone().replace(tzinfo=None)
    drafts: list[TaskDraft] = []
    issues: list[ImportIssue] = []
    for row_number, raw_line in enumerate(text.splitlines(), start=1):
        if len(drafts) >= MAX_TASKS_PER_IMPORT:
            issues.append(ImportIssue("too_many_tasks", f"一次最多导入 {MAX_TASKS_PER_IMPORT} 项任务。"))
            break
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(">"):
            continue
        checkbox_match = _CHECKBOX.match(line)
        marked_done = bool(checkbox_match and checkbox_match.group(0).lower().find("[x]") >= 0)
        if checkbox_match:
            title = checkbox_match.group(1).strip()
        else:
            bullet_match = _BULLET.match(line)
            title = bullet_match.group(1).strip() if bullet_match else line
        due_at: datetime | None = None
        uncertainty: list[str] = []
        iso_match = _ISO.match(title)
        if iso_match:
            raw_date = iso_match.group("date")
            raw_time = iso_match.group("time")
            try:
                due_at = datetime.fromisoformat(f"{raw_date}T{raw_time or '00:00'}")
            except ValueError:
                issues.append(ImportIssue("invalid_due_at", "日期格式无法识别，请在预览中修正。", row_number))
            title = title[iso_match.end(2) + 1 :].strip() if raw_time else title[iso_match.end(1) + 1 :].strip()
        else:
            time_match = _TIME.match(title)
            if time_match:
                due_at = _parse_clock(time_match.group("time"), now.date())
                uncertainty.append("due_time_ambiguous")
                title = time_match.group(2).strip()
        estimate_match = _MINUTES.search(title)
        estimated_minutes = None
        if estimate_match:
            estimated_minutes = int(estimate_match.group("minutes"))
            if not 1 <= estimated_minutes <= MAX_ESTIMATED_MINUTES:
                issues.append(ImportIssue("invalid_estimated_minutes", "预计时长超出允许范围。", row_number))
                continue
            title = (title[: estimate_match.start()] + title[estimate_match.end() :]).strip(" -()")
        if marked_done:
            uncertainty.append("source_marked_done_needs_confirmation")
        title_issue = validate_title(title, row_number)
        if title_issue:
            issues.append(title_issue)
            continue
        drafts.append(TaskDraft(title, due_at, estimated_minutes, row_number, tuple(uncertainty)))
    issues.extend(duplicate_issues(drafts))
    return ImportResult(filename, tuple(drafts), tuple(issues))


def parse_text_file(path: str, *, reference_now: datetime | None = None) -> ImportResult:
    """Read an explicitly selected text file; no directory scanning occurs."""

    from deskcare.importers.base import validate_selected_path

    candidate, path_issues = validate_selected_path(path, {".txt", ".md"})
    if candidate is None:
        return ImportResult(str(path), (), path_issues)
    try:
        content = candidate.read_bytes()
    except OSError:
        return ImportResult(candidate.name, (), (ImportIssue("file_unreadable", "无法读取所选文件。"),))
    return parse_text_bytes(content, candidate.name, reference_now=reference_now)
