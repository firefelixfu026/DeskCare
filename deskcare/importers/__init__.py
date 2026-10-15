"""User-selected task file importers.

Importers only produce in-memory drafts. Persistence is handled by the task
service after an explicit user confirmation.
"""

from deskcare.importers.base import ImportIssue, ImportResult
from deskcare.importers.csv_importer import parse_csv_bytes
from deskcare.importers.loader import parse_selected_file
from deskcare.importers.text_importer import parse_text_bytes

__all__ = ["ImportIssue", "ImportResult", "parse_csv_bytes", "parse_selected_file", "parse_text_bytes"]
