"""Strict, offline CSV task importer."""

from __future__ import annotations

import csv
import io
from datetime import datetime

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

EXPECTED_COLUMNS = {"title", "due_at", "estimated_minutes"}


def _parse_due(value: str, row: int) -> tuple[datetime | None, ImportIssue | None]:
    value = value.strip()
    if not value:
        return None, None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None, ImportIssue("invalid_due_at", "截止时间需使用 ISO 日期时间格式，例如 2026-10-14T18:00。", row)
    return parsed, None


def _parse_estimate(value: str, row: int) -> tuple[int | None, ImportIssue | None]:
    value = value.strip()
    if not value:
        return None, None
    try:
        minutes = int(value)
    except ValueError:
        return None, ImportIssue("invalid_estimated_minutes", "预计时长需为正整数分钟。", row)
    if not 1 <= minutes <= MAX_ESTIMATED_MINUTES:
        return None, ImportIssue("invalid_estimated_minutes", f"预计时长需在 1～{MAX_ESTIMATED_MINUTES} 分钟之间。", row)
    return minutes, None


def parse_csv_bytes(content: bytes, filename: str = "tasks.csv") -> ImportResult:
    if len(content) > MAX_FILE_BYTES:
        return ImportResult(filename, (), (ImportIssue("file_too_large", "文件超过 1 MB，未读取。"),))
    text, decode_issues = decode_utf8(content)
    if text is None:
        return ImportResult(filename, (), decode_issues)
    if not text.strip():
        return ImportResult(filename, (), (ImportIssue("empty_file", "文件为空，没有可预览的任务。"),))
    if any(len(line) > MAX_LINE_LENGTH for line in text.splitlines()):
        return ImportResult(filename, (), (ImportIssue("line_too_long", f"每行不能超过 {MAX_LINE_LENGTH} 个字符。"),))

    reader = csv.reader(io.StringIO(text), strict=True)
    try:
        rows = list(reader)
    except csv.Error:
        return ImportResult(filename, (), (ImportIssue("malformed_csv", "CSV 格式损坏，无法安全解析。"),))
    if not rows:
        return ImportResult(filename, (), (ImportIssue("empty_file", "文件为空，没有可预览的任务。"),))

    headers = [item.strip().casefold() for item in rows[0]]
    if "title" not in headers:
        return ImportResult(filename, (), (ImportIssue("missing_title_column", "CSV 必须包含 title 列。"),))
    unknown = sorted(set(headers) - EXPECTED_COLUMNS)
    if unknown:
        return ImportResult(filename, (), (ImportIssue("unknown_column", f"CSV 包含不支持的列：{', '.join(unknown)}。"),))
    if len(headers) != len(set(headers)):
        return ImportResult(filename, (), (ImportIssue("duplicate_column", "CSV 列名不能重复。"),))

    drafts: list[TaskDraft] = []
    issues: list[ImportIssue] = []
    for row_number, values in enumerate(rows[1:], start=2):
        if row_number > MAX_TASKS_PER_IMPORT + 1:
            issues.append(ImportIssue("too_many_tasks", f"一次最多导入 {MAX_TASKS_PER_IMPORT} 项任务。"))
            break
        if len(values) != len(headers):
            issues.append(ImportIssue("wrong_column_count", "该行列数与表头不一致。", row_number))
            continue
        fields = dict(zip(headers, values))
        title = " ".join(fields.get("title", "").split())
        title_issue = validate_title(title, row_number)
        if title_issue:
            issues.append(title_issue)
            continue
        due_at, due_issue = _parse_due(fields.get("due_at", ""), row_number)
        estimate, estimate_issue = _parse_estimate(fields.get("estimated_minutes", ""), row_number)
        if due_issue:
            issues.append(due_issue)
        if estimate_issue:
            issues.append(estimate_issue)
        if due_issue or estimate_issue:
            continue
        drafts.append(TaskDraft(title, due_at, estimate, row_number))
    issues.extend(duplicate_issues(drafts))
    return ImportResult(filename, tuple(drafts), tuple(issues))
