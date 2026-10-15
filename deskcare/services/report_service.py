"""Compatibility exports for the M4 report service boundary."""

from collections.abc import Mapping
from typing import Protocol

from deskcare.services.report_engine import (
    LocalReportService,
    ReportFactsBuilder,
    ReportPeriod,
    TemplateNarrator,
)


class ReportService(Protocol):
    """Report output must be grounded in structured local facts."""

    def build_facts(self, period: ReportPeriod) -> Mapping[str, object]: ...

    def narrate(self, facts: Mapping[str, object]) -> str: ...


__all__ = [
    "LocalReportService",
    "ReportFactsBuilder",
    "ReportPeriod",
    "ReportService",
    "TemplateNarrator",
]

