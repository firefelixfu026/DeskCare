"""Contracts for optional, user-authorized local AI capabilities."""

from __future__ import annotations

from collections.abc import Protocol

from deskcare.importers.base import ImportResult


class TaskCandidateParser(Protocol):
    """Parse only user-selected text into non-persisted task candidates."""

    def parse(self, content: bytes, filename: str) -> ImportResult: ...
