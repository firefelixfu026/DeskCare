from datetime import date, datetime, timedelta, timezone
import json
import sqlite3

import pytest

from deskcare.domain.types import TaskDraft, TaskStatus, WellnessLevel
from deskcare.services.health_journal_service import HealthJournalService
from deskcare.services.report_engine import LocalReportService, ReportPeriod
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository


@pytest.fixture
def journal(tmp_path):
    repo = UsageRepository(tmp_path / "synthetic.sqlite3")
    tasks = TaskService(repo)
    now = datetime(2026, 10, 20, 12, tzinfo=timezone.utc)
    service = HealthJournalService(repo, tasks, now=lambda: now)
    return repo, tasks, service, now


def record(service, now, **values):
    return service.save(occurred_at=now-timedelta(hours=1), description="虚构感受，不是真实健康记录", **values)


def test_independent_opt_in_no_inherited_authorization(journal):
    repo, tasks, service, now = journal
    for scope in ("wellness_checkin", "local_ai", "cloud_ai", "activity_monitoring"):
        repo.set_consent(scope, True)
    assert not service.enabled and service.events() == []
    with pytest.raises(PermissionError):
        record(service, now)
    with repo._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM health_events").fetchone()[0] == 0
    service.set_enabled(True)
    assert service.enabled
    entry = record(service, now, duration_minutes=0)
    assert entry.severity is None and entry.duration_minutes == 0
    assert entry.body_area == "" and entry.notes == ""


def test_multiple_events_edit_and_reopen_preserve_daily_choice(journal):
    repo, tasks, service, now = journal
    repo.upsert_wellness_entry(now.date(), WellnessLevel.COMFORTABLE)
    service.set_enabled(True)
    first = record(service, now, notes="虚构原备注")
    second = record(service, now, severity="mild")
    changed = service.save(event_id=first.id, occurred_at=first.occurred_at,
                           description="修改后的虚构感受", notes="我自己修改")
    other = HealthJournalService(UsageRepository(repo.path), now=lambda: now)
    assert len(other.events()) == 2
    assert other.repository.event(first.id).notes == "我自己修改"
    assert changed.id == first.id != second.id
    assert repo.wellness_for_day(now.date()).comfort_level is WellnessLevel.COMFORTABLE


@pytest.mark.parametrize("field,value", [("description", ""), ("description", "x"*501),
    ("notes", "x"*2001), ("body_area", "x"*81), ("severity", "diagnosed"),
    ("duration_minutes", -1), ("duration_minutes", 10081), ("duration_minutes", True)])
def test_invalid_input_does_not_write(journal, field, value):
    repo, tasks, service, now = journal
    service.set_enabled(True)
    values = dict(occurred_at=now, description="虚构示例")
    values[field] = value
    with pytest.raises(ValueError):
        service.save(**values)
    assert not service.events()


def test_followups_are_explicit_chronological_and_removable(journal):
    repo, tasks, service, now = journal
    service.set_enabled(True)
    entry = record(service, now)
    assert "尚未补记" in service.review(entry.id)
    for when, change in ((entry.occurred_at-timedelta(minutes=1), "better"),
                          (now+timedelta(hours=1), "better"), (now, None)):
        with pytest.raises(ValueError):
            service.followup(entry.id, recorded_at=when, change=change)
    assert not service.repository.followups(entry.id)
    service.followup(entry.id, recorded_at=now, change="unsure", note="虚构补记")
    service.followup(entry.id, recorded_at=now-timedelta(minutes=10), change="same")
    followups = service.repository.followups(entry.id)
    assert [row.change for row in followups] == ["same", "unsure"]
    assert "说不准" in service.review(entry.id)
    with pytest.raises(ValueError):
        service.save(event_id=entry.id, occurred_at=now, description=entry.description)
    service.delete_followup(entry.id, followups[1].id)
    assert "虚构补记" not in service.review(entry.id)
    assert service.events()[0].followup_count == 1


def test_future_event_rejected_and_backdated_filter(journal):
    repo, tasks, service, now = journal
    service.set_enabled(True)
    with pytest.raises(ValueError):
        service.save(occurred_at=now+timedelta(hours=1), description="未来不是已发生记录")
    record(service, now)
    old = service.save(occurred_at=now-timedelta(days=40), description="虚构旧记录")
    assert len(service.events((now-timedelta(days=7)).date(), now.date())) == 1
    assert len(service.events()) == 2


def test_action_requires_confirmation_atomic_link_and_no_symptom_copy(journal):
    repo, tasks, service, now = journal
    service.set_enabled(True)
    entry = record(service, now, notes="PRIVATE_FAKE_HEALTH_NOTE")
    planned = now.date()+timedelta(days=2)
    draft = TaskDraft("自己安排调整时间", planned_for=planned)
    with pytest.raises(PermissionError):
        service.add_action(entry.id, draft)
    assert not tasks.list_all() and not service.repository.actions(entry.id)
    notices = []
    tasks.subscribe(lambda: notices.append(True))
    task = service.add_action(entry.id, draft, confirmed=True)
    assert notices == [True] and task.notes == "" and task.source == "manual"
    assert task in tasks.list_later(now.date())
    assert entry.description not in task.title
    tasks.set_status(task.id, TaskStatus.DONE)
    review = service.review(entry.id)
    assert "标记完成" in review and "尚未补记" in review
    assert "任务完成不等于不适改善" in review
    facts, report = LocalReportService(repo).render(ReportPeriod("daily", now.date(), now.date()))
    assert "PRIVATE_FAKE_HEALTH_NOTE" not in json.dumps(facts, ensure_ascii=False) + report
    assert "health_events" not in facts and "不适记录" not in report


def test_link_insert_failure_rolls_back_new_task(journal):
    repo, tasks, service, now = journal
    service.set_enabled(True)
    entry = record(service, now)
    with repo._connect() as conn:
        conn.execute("CREATE TRIGGER reject_link BEFORE INSERT ON health_action_links BEGIN SELECT RAISE(ABORT, 'test rollback'); END")
    with pytest.raises(sqlite3.IntegrityError):
        service.add_action(entry.id, TaskDraft("虚构行动"), confirmed=True)
    assert not tasks.list_all() and not service.repository.actions(entry.id)


def test_task_deletion_and_event_deletion_do_not_delete_each_other(journal):
    repo, tasks, service, now = journal
    service.set_enabled(True)
    entry = record(service, now)
    first = service.add_action(entry.id, TaskDraft("虚构一"), confirmed=True)
    second = service.add_action(entry.id, TaskDraft("虚构二"), confirmed=True)
    service.followup(entry.id, recorded_at=now, change="same")
    tasks.delete(first.id)
    assert service.repository.actions(entry.id)[0].task_id is None
    assert len(service.events()) == 1
    service.delete(entry.id)
    assert tasks.list_all()[0].id == second.id
    with repo._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM health_followups").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM health_action_links").fetchone()[0] == 0


def test_revocation_purges_health_only_and_reenable_does_not_restore(journal):
    repo, tasks, service, now = journal
    repo.add_usage(now.date(), "CODE", active_seconds=20)
    service.set_enabled(True)
    entry = record(service, now)
    service.followup(entry.id, recorded_at=now, change="better")
    service.add_action(entry.id, TaskDraft("用户确认的普通行动"), confirmed=True)
    service.set_enabled(False)
    assert not service.events() and len(tasks.list_all()) == 1
    assert repo.usage_for_day(now.date())
    with pytest.raises(PermissionError):
        service.review(entry.id)
    service.set_enabled(True)
    assert not service.events()
    for table in ("health_events", "health_followups", "health_action_links"):
        with repo._connect() as conn:
            assert conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


def test_migration_keeps_old_data_and_all_clear_includes_managed_backup(tmp_path):
    path = tmp_path / "upgrade.sqlite3"
    repo = UsageRepository(path)
    repo.add_task("旧任务")
    repo.set_consent("wellness_checkin", True)
    with repo._connect() as conn:
        for table in ("health_action_links", "health_followups", "health_events"):
            conn.execute(f"DROP TABLE {table}")
        conn.execute("DELETE FROM schema_migrations WHERE version=9")
    upgraded = UsageRepository(path)
    assert upgraded.all_tasks()[0].title == "旧任务"
    assert upgraded.get_consent("wellness_checkin") is True
    assert upgraded.get_consent("health_journal") is None
    backup = path.with_name(path.name+".before-ui10")
    assert backup.is_file()
    service = HealthJournalService(upgraded)
    service.set_enabled(True)
    entry = service.save(occurred_at=datetime.now(), description="虚构新记录")
    service.followup(entry.id, recorded_at=datetime.now(), change="same")
    upgraded.clear_all_data()
    assert not service.enabled and not upgraded.all_tasks()
    with upgraded._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM health_events").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM health_followups").fetchone()[0] == 0
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0
