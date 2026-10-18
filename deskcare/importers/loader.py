"""Dispatch for a single, user-selected task file."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from deskcare.importers.base import ImportIssue, ImportResult, validate_selected_path
from deskcare.importers.csv_importer import parse_csv_bytes
from deskcare.importers.text_importer import parse_text_bytes
from deskcare.importers.xlsx_importer import parse_xlsx_bytes


def parse_selected_file(path: str | Path, *, reference_now: datetime | None = None) -> ImportResult:
    candidate, issues = validate_selected_path(Path(path), {".txt", ".md", ".csv", ".xlsx"})
    if candidate is None:
        return ImportResult(Path(path).name or str(path), (), issues)
    try:
        content = candidate.read_bytes()
    except OSError:
        return ImportResult(candidate.name, (), (ImportIssue("file_unreadable", "无法读取所选文件。"),))
    if candidate.suffix.lower() == ".csv":
        return parse_csv_bytes(content, candidate.name)
    if candidate.suffix.lower() == ".xlsx":
        return parse_xlsx_bytes(content, candidate.name)
    return parse_text_bytes(content, candidate.name, reference_now=reference_now)
