"""Explicit rule fallback for the optional M6 local-model path."""

from datetime import datetime

from deskcare.importers.text_importer import parse_text_bytes


def parse_with_rules(
    content: bytes,
    filename: str,
    *,
    reference_now: datetime | None = None,
):
    """Return the existing conservative importer result unchanged."""

    return parse_text_bytes(content, filename, reference_now=reference_now)
