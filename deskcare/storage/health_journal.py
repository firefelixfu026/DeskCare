"""Separate consent-gated health tables; never exposed through AI FactSheets."""

from datetime import datetime

from deskcare.domain.health_journal import HealthEvent, HealthFollowup, LinkedAction

SCOPE = "health_journal"


class HealthJournalRepository:
    def __init__(self, repository):
        self.store = repository

    @staticmethod
    def _require_enabled(connection):
        consent = connection.execute("SELECT granted FROM consents WHERE scope=?", (SCOPE,)).fetchone()
        if consent is None or not consent[0]:
            raise PermissionError("请先单独开启不适记录。")

    @property
    def enabled(self):
        return self.store.get_consent(SCOPE) is True

    def set_enabled(self, enabled):
        with self.store._connect() as connection:
            if not enabled:
                self._clear(connection)
            connection.execute("""INSERT INTO consents VALUES (?, ?, ?)
                ON CONFLICT(scope) DO UPDATE SET granted=excluded.granted, updated_at=excluded.updated_at""",
                (SCOPE, int(bool(enabled)), self.store._now()))

    @staticmethod
    def _clear(connection):
        for table in ("health_action_links", "health_followups", "health_events"):
            connection.execute(f"DELETE FROM {table}")

    def clear(self):
        with self.store._connect() as connection:
            self._clear(connection)

    @staticmethod
    def _event(row):
        values = dict(row)
        for name in ("occurred_at", "created_at", "updated_at"):
            values[name] = datetime.fromisoformat(values[name])
        return HealthEvent(**values)

    def events(self, start=None, end=None):
        if not self.enabled:
            return []
        clauses, params = [], []
        if start:
            clauses.append("substr(occurred_at,1,10)>=?")
            params.append(start.isoformat())
        if end:
            clauses.append("substr(occurred_at,1,10)<=?")
            params.append(end.isoformat())
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self.store._connect() as connection:
            return [self._event(row) for row in connection.execute(
                "SELECT e.*, (SELECT COUNT(*) FROM health_followups f WHERE f.event_id=e.id) AS followup_count "
                "FROM health_events e" + where + " ORDER BY occurred_at DESC, id DESC", params)]

    def event(self, event_id):
        with self.store._connect() as connection:
            self._require_enabled(connection)
            row = connection.execute("SELECT * FROM health_events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise KeyError("这条记录已不存在。")
        return self._event(row)

    def save_event(self, event_id, values):
        with self.store._connect() as connection:
            self._require_enabled(connection)
            now = self.store._now()
            if event_id is None:
                cursor = connection.execute("""INSERT INTO health_events(
                    occurred_at,body_area,description,severity,duration_minutes,notes,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?)""", (*values, now, now))
                event_id = int(cursor.lastrowid)
            else:
                cursor = connection.execute("""UPDATE health_events SET occurred_at=?,body_area=?,description=?,
                    severity=?,duration_minutes=?,notes=?,updated_at=? WHERE id=?""", (*values, now, event_id))
                if cursor.rowcount != 1:
                    raise KeyError("这条记录已不存在。")
        return self.event(event_id)

    def delete_event(self, event_id):
        with self.store._connect() as connection:
            self._require_enabled(connection)
            connection.execute("DELETE FROM health_events WHERE id=?", (event_id,))

    def followups(self, event_id):
        self.event(event_id)
        with self.store._connect() as connection:
            return [HealthFollowup(row["id"], row["event_id"], datetime.fromisoformat(row["recorded_at"]),
                                   row["change"], row["note"]) for row in connection.execute(
                "SELECT * FROM health_followups WHERE event_id=? ORDER BY recorded_at,id", (event_id,))]

    def add_followup(self, event_id, when, change, note):
        with self.store._connect() as connection:
            self._require_enabled(connection)
            connection.execute("""INSERT INTO health_followups(event_id,recorded_at,change,note,created_at)
                VALUES (?,?,?,?,?)""", (event_id, when.isoformat(timespec="minutes"), change, note, self.store._now()))

    def delete_followup(self, event_id, followup_id):
        with self.store._connect() as connection:
            self._require_enabled(connection)
            connection.execute("DELETE FROM health_followups WHERE id=? AND event_id=?", (followup_id, event_id))

    def actions(self, event_id):
        self.event(event_id)
        with self.store._connect() as connection:
            return [LinkedAction(**dict(row)) for row in connection.execute("""SELECT l.id,l.task_id,t.title,t.status
                FROM health_action_links l LEFT JOIN tasks t ON t.id=l.task_id
                WHERE l.event_id=? ORDER BY l.id""", (event_id,))]

    def add_action(self, event_id, draft):
        with self.store._connect() as connection:
            self._require_enabled(connection)
            if connection.execute("SELECT id FROM health_events WHERE id=?", (event_id,)).fetchone() is None:
                raise KeyError("这条记录已不存在。")
            task_id = self.store._insert_confirmed_task(connection, draft, "manual")
            connection.execute("INSERT INTO health_action_links(event_id,task_id,created_at) VALUES (?,?,?)",
                               (event_id, task_id, self.store._now()))
            row = connection.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return self.store._task_from_row(row)
