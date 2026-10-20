from datetime import date, datetime, time, timedelta
import sqlite3

import pytest

from deskcare.domain.types import TaskDraft, TaskStatus
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository


def test_task_migration_confirmation_edit_status_and_delete(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    service = TaskService(repository)
    target_day = date.today()
    drafts = [
        TaskDraft("完成练习", datetime.combine(target_day, time(18, 0)), 60, 2),
        TaskDraft("整理笔记", None, 30, 3),
    ]
    assert repository.tasks_for_day(target_day) == []
    tasks = service.confirm_import(drafts, r"C:\private\today.csv")
    assert len(tasks) == 2
    assert tasks[0].source == "today.csv"
    assert repository.tasks_for_day(target_day)[0].title == "完成练习"

    updated = service.update(tasks[0].id, title="完成修改后的练习", due_at=None, estimated_minutes=45)
    assert updated.title == "完成修改后的练习"
    done = service.set_status(tasks[0].id, TaskStatus.DONE)
    assert done.status is TaskStatus.DONE
    assert done.completed_at is not None
    reopened = service.set_status(tasks[0].id, TaskStatus.TODO)
    assert reopened.completed_at is None
    service.delete(tasks[1].id)
    assert len(repository.tasks_for_day(target_day)) == 1


def test_future_task_is_in_later_scope_not_today(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    service = TaskService(repository)
    task = service.add_manual("下周准备材料", datetime.now() + timedelta(days=7), 20)
    assert task not in service.list_today()
    assert task in service.list_later()
    assert task in service.list_all()


def test_naive_local_deadline_is_timezone_safe_and_fake_clock_selects_its_day(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    service = TaskService(repository)
    due_local = datetime(2031, 2, 3, 18, 0)
    task = service.add_manual("跨日期测试任务", due_local, 20)
    local_tz = datetime.now().astimezone().tzinfo
    fake_now = datetime(2031, 2, 3, 17, 0, tzinfo=local_tz)

    deadline = service.next_confirmed_deadline(now=fake_now)

    assert task.due_at is not None and task.due_at.tzinfo is not None
    assert deadline is not None and deadline.tzinfo is not None
    assert deadline.astimezone().replace(tzinfo=None) == due_local


def test_cancel_or_unconfirmed_drafts_do_not_change_database(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    service = TaskService(repository)
    drafts = [TaskDraft("仅预览", None, None, 1)]
    assert repository.tasks_for_day(date.today()) == []
    # No confirm_import call: a draft is not persistence.
    assert service.list_today() == []


def test_duplicate_confirmation_is_atomic(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    service = TaskService(repository)
    with pytest.raises(ValueError):
        service.confirm_import(
            [TaskDraft("同名", None), TaskDraft(" 同名 ", None)],
            "dup.txt",
        )
    assert repository.tasks_for_day() == []


def test_m1_database_is_upgraded_without_losing_usage_or_consent(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as connection:
        connection.executescript(
            """CREATE TABLE schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
               CREATE TABLE consents(scope TEXT PRIMARY KEY, granted INTEGER NOT NULL, updated_at TEXT NOT NULL);
               CREATE TABLE usage_daily(
                   day TEXT NOT NULL, category TEXT NOT NULL,
                   active_seconds REAL NOT NULL DEFAULT 0,
                   idle_seconds REAL NOT NULL DEFAULT 0,
                   unknown_seconds REAL NOT NULL DEFAULT 0,
                   updated_at TEXT NOT NULL,
                   PRIMARY KEY(day, category)
               );
               INSERT INTO schema_migrations VALUES (1, '2026-10-14T10:00:00');
               INSERT INTO consents VALUES ('activity_monitoring', 1, '2026-10-14T10:00:00');
               INSERT INTO usage_daily VALUES ('2026-10-14', 'CODE', 42, 3, 1, '2026-10-14T10:00:00');"""
        )
    repository = UsageRepository(path)
    assert repository.get_consent("activity_monitoring") is True
    assert repository.usage_for_day("2026-10-14")[0].active_seconds == 42
    with repository._connect() as connection:
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'tasks'"
        ).fetchone() is not None
