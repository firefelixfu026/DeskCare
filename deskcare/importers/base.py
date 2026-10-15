"""Common limits and result types for M2 task imports."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from deskcare.domain.types import TaskDraft

MAX_FILE_BYTES = 1_000_000
MAX_LINE_LENGTH = 400
MAX_TASKS_PER_IMPORT = 500
MAX_TITLE_LENGTH = 240
MAX_ESTIMATED_MINUTES = 24 * 60


@dataclass(frozen=True)
class ImportIssue:
    """A user-visible validation message; source content is not retained."""

    code: str
    message: str
    row: int | None = None
    fatal: bool = True


@dataclass(frozen=True)
class ImportResult:
    source_name: str
    drafts: tuple[TaskDraft, ...]
    issues: tuple[ImportIssue, ...] = ()

    @property
    def can_confirm(self) -> bool:
        return bool(self.drafts) and not any(issue.fatal for issue in self.issues)


def validate_selected_path(path: str | Path, allowed_suffixes: set[str]) -> tuple[Path | None, tuple[ImportIssue, ...]]:
    """Validate only the file explicitly selected by the user."""

    candidate = Path(path)
    if candidate.suffix.lower() not in allowed_suffixes:
        return None, (ImportIssue("unsupported_type", "请选择 .txt、.md 或 .csv 文件。"),)
    try:
        if not candidate.is_file():
            return None, (ImportIssue("not_a_file", "所选路径不是可读取的文件。"),)
        if candidate.stat().st_size > MAX_FILE_BYTES:
            return None, (ImportIssue("file_too_large", "文件超过 1 MB，未读取。"),)
    except OSError:
        return None, (ImportIssue("file_unreadable", "无法读取所选文件，请检查权限后重试。"),)
    return candidate, ()


def decode_utf8(content: bytes) -> tuple[str | None, tuple[ImportIssue, ...]]:
    try:
        return content.decode("utf-8-sig"), ()
    except UnicodeDecodeError:
        return None, (ImportIssue("invalid_encoding", "文件不是有效的 UTF-8 文本，未导入。"),)


def validate_title(title: str, row: int | None = None) -> ImportIssue | None:
    cleaned = " ".join(title.split())
    if not cleaned:
        return ImportIssue("empty_title", "任务标题不能为空。", row)
    if len(cleaned) > MAX_TITLE_LENGTH:
        return ImportIssue("title_too_long", f"任务标题不能超过 {MAX_TITLE_LENGTH} 个字符。", row)
    return None


def duplicate_issues(drafts: list[TaskDraft]) -> list[ImportIssue]:
    seen: dict[str, int] = {}
    issues: list[ImportIssue] = []
    for draft in drafts:
        key = " ".join(draft.title.casefold().split())
        if key in seen:
            issues.append(
                ImportIssue(
                    "duplicate_title",
                    f"第 {draft.source_row or '?'} 行与第 {seen[key]} 行标题重复，请编辑或删除其中一项。",
                    draft.source_row,
                )
            )
        else:
            seen[key] = draft.source_row or 0
    return issues
