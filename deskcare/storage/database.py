"""Small, parameterized SQLite store used by the M1/M2 local layers."""

from __future__ import annotations

import json
import os
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from deskcare.domain.types import PolicyDecision, Task, TaskDraft, TaskStatus, WellnessLevel


@dataclass(frozen=True)
class UsageRow:
    day: str
    category: str
    active_seconds: float
    idle_seconds: float
    unknown_seconds: float


@dataclass(frozen=True)
class AppUsageRow:
    day: str
    app_id: str
    active_seconds: float


@dataclass(frozen=True)
class ReminderEvent:
    id: int
    occurred_at: datetime
    decision: str
    reason_codes: tuple[str, ...]
    mode: str
    active_minutes: float
    response: str | None = None
    response_at: datetime | None = None
    decision_context: dict[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class WellnessEntry:
    """One coarse, user-authored BodyLog entry for a local calendar day."""

    day: date
    comfort_level: WellnessLevel
    created_at: datetime
    updated_at: datetime


def get_default_database_path() -> Path:
    """Return a user-local path without creating or scanning other folders."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return root / "DeskCare" / "deskcare.sqlite3"


def get_demo_database_path() -> Path:
    """Return an isolated database for synthetic demo data.

    Demo runs may persist their simulated observations, but they must never
    share the user's everyday activity history or reports.
    """

    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    return root / "DeskCare" / "demo" / "deskcare-demo.sqlite3"


def get_demo_scenario_database_path(day: date | None = None) -> Path:
    """Return an isolated, per-day database for the scripted demo journey."""

    local_app_data = os.environ.get("LOCALAPPDATA")
    root = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    scenario_day = day or date.today()
    return root / "DeskCare" / "demo" / f"scenario-{scenario_day.isoformat()}.sqlite3"


class UsageRepository:
    """Own M1/M2 migrations and local aggregate/task writes.

    Raw samples are deliberately not persisted. Only bounded daily aggregates
    and an explicit consent flag are stored.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        # Ask SQLite to overwrite deleted cell content on this connection.
        # This improves local privacy but is not a claim of forensic erasure:
        # filesystem snapshots and external backups can still retain copies.
        connection.execute("PRAGMA secure_delete = ON")
        return connection

    def _migrate(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )"""
            )
            applied = {
                row[0]
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            if 1 not in applied:
                connection.executescript(
                    """CREATE TABLE consents (
                        scope TEXT PRIMARY KEY,
                        granted INTEGER NOT NULL CHECK (granted IN (0, 1)),
                        updated_at TEXT NOT NULL
                    );
                    CREATE TABLE usage_daily (
                        day TEXT NOT NULL,
                        category TEXT NOT NULL,
                        active_seconds REAL NOT NULL DEFAULT 0,
                        idle_seconds REAL NOT NULL DEFAULT 0,
                        unknown_seconds REAL NOT NULL DEFAULT 0,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (day, category)
                    );
                    INSERT INTO schema_migrations(version, applied_at)
                    VALUES (1, datetime('now'));
                    """
                )
            if 2 not in applied:
                connection.executescript(
                    """CREATE TABLE IF NOT EXISTS tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        title TEXT NOT NULL,
                        due_at TEXT,
                        estimated_minutes INTEGER,
                        status TEXT NOT NULL CHECK (status IN ('todo', 'doing', 'done')),
                        confirmed_at TEXT NOT NULL,
                        completed_at TEXT,
                        source TEXT NOT NULL DEFAULT 'manual',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_tasks_due_at ON tasks(due_at);
                    INSERT INTO schema_migrations(version, applied_at)
                    VALUES (2, datetime('now'));
                    """
                )
            if 3 not in applied:
                connection.executescript(
                    """CREATE TABLE IF NOT EXISTS reminder_events (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        occurred_at TEXT NOT NULL,
                        decision TEXT NOT NULL,
                        reason_codes_json TEXT NOT NULL,
                        mode TEXT NOT NULL,
                        active_minutes REAL NOT NULL,
                        response TEXT,
                        response_at TEXT
                    );
                    CREATE INDEX IF NOT EXISTS idx_reminder_events_occurred
                        ON reminder_events(occurred_at);
                    INSERT INTO schema_migrations(version, applied_at)
                    VALUES (3, datetime('now'));
                    """
                )
            if 4 not in applied:
                connection.executescript(
                    """CREATE TABLE IF NOT EXISTS wellness_entries (
                        entry_day TEXT PRIMARY KEY,
                        comfort_level TEXT NOT NULL CHECK (
                            comfort_level IN ('comfortable', 'some_discomfort', 'prefer_not_to_say')
                        ),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO schema_migrations(version, applied_at)
                    VALUES (4, datetime('now'));
                    """
                )
            if 5 not in applied:
                connection.executescript(
                    """CREATE TABLE IF NOT EXISTS app_settings (
                        setting_key TEXT PRIMARY KEY,
                        setting_value TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );
                    INSERT INTO schema_migrations(version, applied_at)
                    VALUES (5, datetime('now'));
                    """
                )
            if 6 not in applied:
                connection.executescript(
                    """CREATE TABLE IF NOT EXISTS app_usage_daily (
                        day TEXT NOT NULL,
                        app_id TEXT NOT NULL,
                        active_seconds REAL NOT NULL DEFAULT 0 CHECK (active_seconds >= 0),
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY (day, app_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_app_usage_daily_day
                        ON app_usage_daily(day);
                    INSERT INTO schema_migrations(version, applied_at)
                    VALUES (6, datetime('now'));
                    """
                )
            if 7 not in applied:
                connection.executescript(
                    """ALTER TABLE reminder_events
                        ADD COLUMN decision_context_json TEXT NOT NULL DEFAULT '{}';
                    INSERT INTO schema_migrations(version, applied_at)
                    VALUES (7, datetime('now'));
                    """
                )

    @staticmethod
    def _now() -> str:
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def get_consent(self, scope: str) -> bool | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT granted FROM consents WHERE scope = ?", (scope,)
            ).fetchone()
        return None if row is None else bool(row[0])

    def set_consent(self, scope: str, granted: bool) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO consents(scope, granted, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(scope) DO UPDATE SET
                     granted = excluded.granted,
                     updated_at = excluded.updated_at""",
                (scope, int(bool(granted)), self._now()),
            )

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT setting_value FROM app_settings WHERE setting_key = ?", (key,)
            ).fetchone()
        return default if row is None else str(row[0])

    def set_setting(self, key: str, value: str) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO app_settings(setting_key, setting_value, updated_at)
                   VALUES (?, ?, ?)
                   ON CONFLICT(setting_key) DO UPDATE SET
                     setting_value = excluded.setting_value,
                     updated_at = excluded.updated_at""",
                (key, str(value), self._now()),
            )

    def delete_setting(self, key: str) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM app_settings WHERE setting_key = ?", (key,))

    # --- M4 BodyLog ---------------------------------------------------

    @staticmethod
    def _wellness_from_row(row: sqlite3.Row) -> WellnessEntry:
        return WellnessEntry(
            day=date.fromisoformat(str(row["entry_day"])),
            comfort_level=WellnessLevel(str(row["comfort_level"])),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
        )

    def upsert_wellness_entry(
        self,
        day: date,
        comfort_level: WellnessLevel,
    ) -> WellnessEntry:
        if not isinstance(comfort_level, WellnessLevel):
            comfort_level = WellnessLevel(str(comfort_level))
        now = self._now()
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO wellness_entries(
                       entry_day, comfort_level, created_at, updated_at
                   ) VALUES (?, ?, ?, ?)
                   ON CONFLICT(entry_day) DO UPDATE SET
                       comfort_level = excluded.comfort_level,
                       updated_at = excluded.updated_at""",
                (day.isoformat(), comfort_level.value, now, now),
            )
            row = connection.execute(
                """SELECT entry_day, comfort_level, created_at, updated_at
                   FROM wellness_entries WHERE entry_day = ?""",
                (day.isoformat(),),
            ).fetchone()
        return self._wellness_from_row(row)

    def wellness_for_day(self, day: date | str | None = None) -> WellnessEntry | None:
        day_text = (day or date.today()).isoformat() if not isinstance(day, str) else day
        with self._connect() as connection:
            row = connection.execute(
                """SELECT entry_day, comfort_level, created_at, updated_at
                   FROM wellness_entries WHERE entry_day = ?""",
                (day_text,),
            ).fetchone()
        return self._wellness_from_row(row) if row else None

    def wellness_entries_for_period(
        self,
        start: date,
        end: date,
    ) -> list[WellnessEntry]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT entry_day, comfort_level, created_at, updated_at
                   FROM wellness_entries
                   WHERE entry_day >= ? AND entry_day <= ?
                   ORDER BY entry_day""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [self._wellness_from_row(row) for row in rows]

    def delete_wellness_entry(self, day: date | str | None = None) -> None:
        day_text = (day or date.today()).isoformat() if not isinstance(day, str) else day
        with self._connect() as connection:
            connection.execute("DELETE FROM wellness_entries WHERE entry_day = ?", (day_text,))

    def clear_wellness(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM wellness_entries")

    def clear_all_data(self) -> None:
        """Delete all records and compact the local DB on a best-effort basis.

        The schema is retained so the running application can continue to use
        the same file. SQLite secure_delete plus VACUUM reduces recoverable
        content in free pages, but cannot remove external backups/snapshots.
        """

        with self._connect() as connection:
            for table in (
                "usage_daily",
                "app_usage_daily",
                "tasks",
                "reminder_events",
                "wellness_entries",
                "consents",
                "app_settings",
            ):
                connection.execute(f"DELETE FROM {table}")
        try:
            with self._connect() as connection:
                connection.execute("VACUUM")
        except sqlite3.DatabaseError:
            # The DELETE transaction has already committed. A transient lock
            # or low-disk condition must not turn successful user deletion
            # into an application crash; future writes still use secure_delete.
            pass

    def add_usage(
        self,
        day: date | str,
        category: str,
        *,
        active_seconds: float = 0.0,
        idle_seconds: float = 0.0,
        unknown_seconds: float = 0.0,
    ) -> None:
        day_text = day.isoformat() if isinstance(day, date) else str(day)
        values = (float(active_seconds), float(idle_seconds), float(unknown_seconds))
        if any(value < 0 for value in values):
            raise ValueError("usage durations must not be negative")
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO usage_daily(
                       day, category, active_seconds, idle_seconds,
                       unknown_seconds, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(day, category) DO UPDATE SET
                       active_seconds = active_seconds + excluded.active_seconds,
                       idle_seconds = idle_seconds + excluded.idle_seconds,
                       unknown_seconds = unknown_seconds + excluded.unknown_seconds,
                       updated_at = excluded.updated_at""",
                (day_text, category, *values, self._now()),
            )

    def usage_for_day(self, day: date | str | None = None) -> list[UsageRow]:
        day_text = (day or date.today()).isoformat() if not isinstance(day, str) else day
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT day, category, active_seconds, idle_seconds, unknown_seconds
                   FROM usage_daily WHERE day = ? ORDER BY category""",
                (day_text,),
            ).fetchall()
        return [UsageRow(**dict(row)) for row in rows]

    def clear_usage(self) -> None:
        """Delete category and app aggregates while preserving consent settings."""

        with self._connect() as connection:
            connection.execute("DELETE FROM usage_daily")
            connection.execute("DELETE FROM app_usage_daily")

    def add_app_usage(self, day: date | str, app_id: str, active_seconds: float) -> None:
        """Persist only a bounded executable stem and its active duration."""

        normalized = str(app_id).casefold().strip()
        if len(normalized) > 64 or re.fullmatch(r"[\w.-]+", normalized, flags=re.UNICODE) is None:
            raise ValueError("app_id must be a normalized short identifier")
        duration = float(active_seconds)
        if duration < 0:
            raise ValueError("app usage duration must not be negative")
        day_text = day.isoformat() if isinstance(day, date) else str(day)
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO app_usage_daily(day, app_id, active_seconds, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(day, app_id) DO UPDATE SET
                     active_seconds = active_seconds + excluded.active_seconds,
                     updated_at = excluded.updated_at""",
                (day_text, normalized, duration, self._now()),
            )

    def app_usage_for_period(self, start: date, end: date) -> list[AppUsageRow]:
        if end < start:
            raise ValueError("end date must not be earlier than start date")
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT app_id, SUM(active_seconds) AS active_seconds
                   FROM app_usage_daily WHERE day BETWEEN ? AND ?
                   GROUP BY app_id ORDER BY active_seconds DESC, app_id""",
                (start.isoformat(), end.isoformat()),
            ).fetchall()
        return [AppUsageRow(day=f"{start.isoformat()}..{end.isoformat()}", **dict(row)) for row in rows]

    def clear_app_usage(self) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM app_usage_daily")

    # --- M2 confirmed task repository ---------------------------------

    @staticmethod
    def _task_from_row(row: sqlite3.Row) -> Task:
        def parse(value: str | None) -> datetime | None:
            return datetime.fromisoformat(value) if value else None

        due_at = parse(row["due_at"])
        if due_at is not None and due_at.tzinfo is None:
            # Legacy/imported ISO values without an offset mean local civil
            # time. Make that meaning explicit before policy comparisons.
            due_at = due_at.astimezone()

        return Task(
            id=int(row["id"]),
            title=str(row["title"]),
            due_at=due_at,
            estimated_minutes=(
                int(row["estimated_minutes"])
                if row["estimated_minutes"] is not None
                else None
            ),
            status=TaskStatus(str(row["status"])),
            confirmed_at=parse(row["confirmed_at"]),
            completed_at=parse(row["completed_at"]),
            source=str(row["source"]),
        )

    @staticmethod
    def _task_values(
        title: str,
        due_at: datetime | None,
        estimated_minutes: int | None,
        source: str,
    ) -> tuple[str, str | None, int | None, str, str, str]:
        cleaned = " ".join(title.split())
        if not cleaned:
            raise ValueError("task title must not be empty")
        if len(cleaned) > 240:
            raise ValueError("task title is too long")
        if estimated_minutes is not None and not 1 <= int(estimated_minutes) <= 1440:
            raise ValueError("estimated minutes must be between 1 and 1440")
        if due_at is not None:
            # Naive values entered as e.g. ``2026-10-14T18:00`` are local
            # civil time. astimezone() also converts offset-aware imports to
            # the machine's local zone so SQL day bucketing stays coherent.
            due_at = due_at.astimezone()
        now = datetime.now().astimezone().isoformat(timespec="seconds")
        return (
            cleaned,
            due_at.isoformat(timespec="minutes") if due_at else None,
            int(estimated_minutes) if estimated_minutes is not None else None,
            now,
            now,
            str(source).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1] or "manual",
        )

    def confirm_tasks(self, drafts: list[TaskDraft] | tuple[TaskDraft, ...], source: str = "manual") -> list[Task]:
        """Persist only the explicitly confirmed draft list in one transaction."""

        normalized: set[str] = set()
        values = []
        for draft in drafts:
            key = " ".join(draft.title.casefold().split())
            if key in normalized:
                raise ValueError("duplicate task titles must be resolved before confirmation")
            normalized.add(key)
            title, due_at, estimate, confirmed_at, created_at, safe_source = self._task_values(
                draft.title, draft.due_at, draft.estimated_minutes, source
            )
            values.append((title, due_at, estimate, confirmed_at, safe_source, created_at))
        if not values:
            return []
        with self._connect() as connection:
            inserted_ids: list[int] = []
            for title, due_at, estimate, confirmed_at, safe_source, created_at in values:
                cursor = connection.execute(
                    """INSERT INTO tasks(
                           title, due_at, estimated_minutes, status,
                           confirmed_at, source, created_at, updated_at
                       ) VALUES (?, ?, ?, 'todo', ?, ?, ?, ?)""",
                    (title, due_at, estimate, confirmed_at, safe_source, created_at, confirmed_at),
                )
                inserted_ids.append(int(cursor.lastrowid))
            placeholders = ",".join("?" for _ in inserted_ids)
            rows = connection.execute(
                f"""SELECT id, title, due_at, estimated_minutes, status,
                           confirmed_at, completed_at, source
                    FROM tasks WHERE id IN ({placeholders})
                    ORDER BY id""",
                tuple(inserted_ids),
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def add_task(
        self,
        title: str,
        due_at: datetime | None = None,
        estimated_minutes: int | None = None,
        source: str = "manual",
    ) -> Task:
        values = self._task_values(title, due_at, estimated_minutes, source)
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO tasks(
                       title, due_at, estimated_minutes, status,
                       confirmed_at, source, created_at, updated_at
                   ) VALUES (?, ?, ?, 'todo', ?, ?, ?, ?)""",
                (values[0], values[1], values[2], values[3], values[5], values[4], values[3]),
            )
            row = connection.execute(
                """SELECT id, title, due_at, estimated_minutes, status,
                          confirmed_at, completed_at, source
                   FROM tasks WHERE id = ?""",
                (cursor.lastrowid,),
            ).fetchone()
        return self._task_from_row(row)

    def tasks_for_day(self, day: date | str | None = None) -> list[Task]:
        day_text = (day or date.today()).isoformat() if not isinstance(day, str) else day
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id, title, due_at, estimated_minutes, status,
                          confirmed_at, completed_at, source
                   FROM tasks
                   WHERE substr(confirmed_at, 1, 10) = ?
                      OR (due_at IS NOT NULL AND substr(due_at, 1, 10) = ?)
                   ORDER BY CASE WHEN due_at IS NULL THEN 1 ELSE 0 END, due_at, id""",
                (day_text, day_text),
            ).fetchall()
        return [self._task_from_row(row) for row in rows]

    def update_task(
        self,
        task_id: int,
        *,
        title: str,
        due_at: datetime | None = None,
        estimated_minutes: int | None = None,
    ) -> Task:
        values = self._task_values(title, due_at, estimated_minutes, "manual")
        with self._connect() as connection:
            connection.execute(
                """UPDATE tasks SET title = ?, due_at = ?, estimated_minutes = ?,
                          updated_at = ? WHERE id = ?""",
                (values[0], values[1], values[2], values[3], task_id),
            )
            row = connection.execute(
                """SELECT id, title, due_at, estimated_minutes, status,
                          confirmed_at, completed_at, source
                   FROM tasks WHERE id = ?""",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._task_from_row(row)

    def set_task_status(self, task_id: int, status: TaskStatus) -> Task:
        if not isinstance(status, TaskStatus):
            status = TaskStatus(status)
        completed_at = datetime.now().astimezone().isoformat(timespec="seconds") if status is TaskStatus.DONE else None
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET status = ?, completed_at = ?, updated_at = ? WHERE id = ?",
                (status.value, completed_at, self._now(), task_id),
            )
            row = connection.execute(
                """SELECT id, title, due_at, estimated_minutes, status,
                          confirmed_at, completed_at, source
                   FROM tasks WHERE id = ?""",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._task_from_row(row)

    def delete_task(self, task_id: int) -> None:
        with self._connect() as connection:
            connection.execute("DELETE FROM tasks WHERE id = ?", (task_id,))

    # --- M3 reminder history ------------------------------------------

    @staticmethod
    def _reminder_from_row(row: sqlite3.Row) -> ReminderEvent:
        return ReminderEvent(
            id=int(row["id"]),
            occurred_at=datetime.fromisoformat(row["occurred_at"]),
            decision=str(row["decision"]),
            reason_codes=tuple(json.loads(row["reason_codes_json"])),
            mode=str(row["mode"]),
            active_minutes=float(row["active_minutes"]),
            response=row["response"],
            response_at=(
                datetime.fromisoformat(row["response_at"])
                if row["response_at"]
                else None
            ),
            decision_context=json.loads(row["decision_context_json"] or "{}"),
        )

    def add_reminder_event(
        self,
        *,
        occurred_at: datetime,
        decision: PolicyDecision,
        mode: str,
        active_minutes: float,
        decision_context: dict[str, object] | None = None,
    ) -> ReminderEvent:
        if active_minutes < 0:
            raise ValueError("active minutes must not be negative")
        context_json = json.dumps(
            decision_context or {}, ensure_ascii=False, allow_nan=False
        )
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT INTO reminder_events(
                       occurred_at, decision, reason_codes_json,
                       mode, active_minutes, decision_context_json
                   ) VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    occurred_at.isoformat(timespec="seconds"),
                    decision.action.value,
                    json.dumps(list(decision.reason_codes), ensure_ascii=False),
                    mode,
                    float(active_minutes),
                    context_json,
                ),
            )
            row = connection.execute(
                """SELECT id, occurred_at, decision, reason_codes_json,
                          mode, active_minutes, response, response_at,
                          decision_context_json
                   FROM reminder_events WHERE id = ?""",
                (cursor.lastrowid,),
            ).fetchone()
        return self._reminder_from_row(row)

    def latest_reminder_event(self) -> ReminderEvent | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT id, occurred_at, decision, reason_codes_json,
                          mode, active_minutes, response, response_at,
                          decision_context_json
                   FROM reminder_events ORDER BY id DESC LIMIT 1"""
            ).fetchone()
        return self._reminder_from_row(row) if row else None

    def update_reminder_response(
        self,
        event_id: int,
        response: str,
        response_at: datetime,
    ) -> ReminderEvent:
        with self._connect() as connection:
            connection.execute(
                "UPDATE reminder_events SET response = ?, response_at = ? WHERE id = ?",
                (response, response_at.isoformat(timespec="seconds"), event_id),
            )
            row = connection.execute(
                """SELECT id, occurred_at, decision, reason_codes_json,
                          mode, active_minutes, response, response_at,
                          decision_context_json
                   FROM reminder_events WHERE id = ?""",
                (event_id,),
            ).fetchone()
        if row is None:
            raise KeyError(event_id)
        return self._reminder_from_row(row)

    def reminder_events_for_day(self, day: date | str | None = None) -> list[ReminderEvent]:
        day_text = (day or date.today()).isoformat() if not isinstance(day, str) else day
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT id, occurred_at, decision, reason_codes_json,
                          mode, active_minutes, response, response_at,
                          decision_context_json
                   FROM reminder_events WHERE substr(occurred_at, 1, 10) = ?
                   ORDER BY id""",
                (day_text,),
            ).fetchall()
        return [self._reminder_from_row(row) for row in rows]

    def recent_reminder_events(
        self,
        *,
        limit: int = 30,
        responded_only: bool = False,
    ) -> list[ReminderEvent]:
        if not 1 <= int(limit) <= 500:
            raise ValueError("reminder event limit must be between 1 and 500")
        response_filter = "WHERE response IS NOT NULL" if responded_only else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT id, occurred_at, decision, reason_codes_json,
                           mode, active_minutes, response, response_at,
                           decision_context_json
                    FROM reminder_events {response_filter}
                    ORDER BY id DESC LIMIT ?""",
                (int(limit),),
            ).fetchall()
        return [self._reminder_from_row(row) for row in rows]

    def close(self) -> None:
        """Compatibility hook; connections are short-lived by design."""

    def export_debug_summary(self) -> str:
        """Return non-sensitive schema diagnostics for local troubleshooting."""

        with self._connect() as connection:
            migration_count = connection.execute(
                "SELECT COUNT(*) FROM schema_migrations"
            ).fetchone()[0]
            row_count = connection.execute("SELECT COUNT(*) FROM usage_daily").fetchone()[0]
        return json.dumps({"schema_migrations": migration_count, "usage_rows": row_count})
