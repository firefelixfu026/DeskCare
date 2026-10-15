"""Local persistence for DeskCare."""

from deskcare.storage.database import UsageRepository, get_default_database_path

__all__ = ["UsageRepository", "get_default_database_path"]
