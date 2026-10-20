"""Plain text and Markdown task list importer with conservative parsing."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime

from deskcare.domain.types import TaskDraft
from deskcare.importers.task_times import heading_day, split_task_time
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
    section_day = None
    assumed_year = False
    list_mode = any(_CHECKBOX.match(line) or _BULLET.match(line) for line in text.splitlines())
    for row_number, raw_line in enumerate(text.splitlines(), start=1):
        if len(drafts) >= MAX_TASKS_PER_IMPORT:
            issues.append(ImportIssue("too_many_tasks", f"一次最多导入 {MAX_TASKS_PER_IMPORT} 项任务。"))
            break
        line = raw_line.strip()
        heading, implicit_year = heading_day(line, now.date())
        if heading is not None:
            section_day, assumed_year = heading, implicit_year
            continue
        if not line or line.startswith("#") or line.startswith(">"):
            continue
        if re.fullmatch(r"(?:[-*+]\s*)?\[\s*[xX]?\s*\]", line):
            continue
        checkbox_match = _CHECKBOX.match(line)
        marked_done = bool(checkbox_match and checkbox_match.group(0).lower().find("[x]") >= 0)
        if checkbox_match:
            title = checkbox_match.group(1).strip()
        else:
            bullet_match = _BULLET.match(line)
            if list_mode and bullet_match is None:
                continue
            title = bullet_match.group(1).strip() if bullet_match else line
        draft = split_task_time(title, section_day, now.date())
        if marked_done:
            draft = replace(draft, uncertainty=draft.uncertainty + ("source_marked_done_needs_confirmation",))
        if assumed_year:
            draft = replace(draft, uncertainty=draft.uncertainty + ("year_assumed",))
        issue = validate_title(draft.title, row_number)
        if issue:
            issues.append(issue)
            continue
        if draft.estimated_minutes is not None and not 1 <= draft.estimated_minutes <= MAX_ESTIMATED_MINUTES:
            issues.append(ImportIssue("invalid_estimated_minutes", "预计时长超出允许范围。", row_number))
            continue
        drafts.append(replace(draft, source_row=row_number))
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
