from datetime import date, datetime, timedelta, timezone
import sqlite3

import pytest

from deskcare.ai.optional_local_llm import LocalLLMClient
from deskcare.config import ConfigStore
from deskcare.domain.types import ActivityKind, ActivitySample, TaskStatus
from deskcare.importers.text_importer import parse_text_bytes
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository


SCHEDULE = """# 10.20
- [ ] 准备演示（ddl 23：00）
- [ ] 整理实验记录（ddl 24：00）
## 10.21
- [ ] 参加交流（19：00-20：00）
- [ ] 参加讨论（暂定下午）
- [ ] 整理笔记 预计 25 分钟
"""


def test_schedule_sections_midnight_ranges_and_ambiguous_text_are_not_lost():
    result = parse_text_bytes(SCHEDULE.encode(), reference_now=datetime(2026, 10, 20, 12))
    assert result.can_confirm and len(result.drafts) == 5
    a, b, c, d, e = result.drafts
    assert a.title == "准备演示" and a.due_at == datetime(2026, 10, 20, 23)
    assert b.planned_for == date(2026, 10, 20) and b.due_at == datetime(2026, 10, 21)
    assert c.starts_at == datetime(2026, 10, 21, 19) and c.ends_at == datetime(2026, 10, 21, 20)
    assert c.estimated_minutes == 60
    assert d.due_at is None and d.starts_at is None and d.time_hint == "暂定下午"
    assert e.title == "整理笔记" and e.estimated_minutes == 25
    assert all("year_assumed" in draft.uncertainty for draft in result.drafts)


def test_model_cannot_erase_original_dates_omit_tasks_or_override_written_estimate():
    source = SCHEDULE
    model = {"tasks": [
        {"title": "准备演示", "estimated_minutes": 45, "due_at": "1999-01-01T10:00"},
        {"title": "整理笔记", "estimated_minutes": 999},
    ]}
    result = LocalLLMClient._to_import_result(model, source, "selected.md")
    assert len(result.drafts) == 5
    assert result.drafts[0].due_at.hour == 23
    assert result.drafts[0].planned_for.month == 10 and result.drafts[0].planned_for.day == 20
    assert result.drafts[0].estimated_minutes == 45 and result.drafts[0].estimate_is_suggestion
    assert result.drafts[-1].estimated_minutes == 25 and not result.drafts[-1].estimate_is_suggestion
    assert result.drafts[1].due_at.hour == 0


def test_recurring_same_title_on_different_dates_is_not_a_duplicate(tmp_path):
    result = parse_text_bytes(b"# 10.20\n- Meeting\n# 10.21\n- Meeting\n")
    assert result.can_confirm
    repo = UsageRepository(tmp_path / "repeat.sqlite3")
    assert len(repo.confirm_tasks(result.drafts)) == 2


def test_tasks_later_scope_notes_times_and_early_completion_persist(tmp_path):
    repo = UsageRepository(tmp_path / "tasks.sqlite3")
    service = TaskService(repo)
    today = date.today()
    future = today + timedelta(days=2)
    task = service.add_manual("以后安排", planned_for=future, notes="我自己的说明")
    assert not service.list_today() and task in service.list_later()
    start = datetime.combine(future, datetime.min.time()).replace(hour=19)
    service.update(task.id, title=task.title, planned_for=future, starts_at=start,
                   ends_at=start + timedelta(hours=1), notes="更新备注", estimated_minutes=60)
    loaded = TaskService(UsageRepository(repo.path)).list_later()[0]
    assert loaded.notes == "更新备注" and loaded.starts_at.hour == 19 and loaded.ends_at.hour == 20
    assert loaded.estimated_minutes == 60
    service.update(task.id, title=task.title, planned_for=today)
    assert service.list_today()[0].notes == "更新备注"


def test_v8_migration_preserves_old_data_and_clear_includes_managed_backup(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    repo = UsageRepository(path)
    repo.add_task("已有任务")
    repo.add_usage(date.today(), "CODE", active_seconds=20)
    repo.set_consent("activity_monitoring", True)
    with sqlite3.connect(path) as conn:
        for column in ("planned_for", "starts_at", "ends_at", "notes", "time_hint", "estimate_is_suggestion"):
            conn.execute(f"ALTER TABLE tasks DROP COLUMN {column}")
        conn.execute("DROP TABLE usage_hourly")
        conn.execute("DELETE FROM schema_migrations WHERE version=8")
    migrated = UsageRepository(path)
    assert migrated.all_tasks()[0].title == "已有任务"
    assert migrated.all_tasks()[0].notes == ""
    assert migrated.usage_for_day()[0].active_seconds == 20
    assert migrated.get_consent("activity_monitoring")
    backup = path.with_name(path.name + ".before-ui8")
    assert backup.is_file()
    migrated.clear_all_data()
    with sqlite3.connect(backup) as conn:
        assert conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 0


def test_hourly_default_off_cross_hour_midnight_pause_and_revoke(tmp_path):
    repo = UsageRepository(tmp_path / "hourly.sqlite3")
    first = datetime(2026, 10, 20, 23, 59, 50, tzinfo=timezone.utc)
    samples = iter(ActivitySample(t, first + timedelta(seconds=t), 0, "CODE", ActivityKind.ACTIVE, False, True)
                   for t in (0, 20, 40, 60))
    class Provider:
        def read_sample(self):
            return next(samples)
    ctl = MonitoringController(Provider(), initially_enabled=True)
    collector = ActivityCollector(ctl, repo)
    collector.poll_once()
    collector.poll_once()
    assert repo.get_consent("hourly_stats") is None
    with repo._connect() as conn:
        assert conn.execute("SELECT COUNT(*) FROM usage_hourly").fetchone()[0] == 0
    # A fresh authorized boundary must not backfill the unauthorized interval.
    collector.set_hourly_enabled(True)
    collector.poll_once()
    collector.poll_once()
    rows = repo.hourly_usage(date(2026, 10, 21))
    assert len(rows) == 1 and rows[0]["hour"] == 0 and rows[0]["active_seconds"] == 20
    collector.set_hourly_enabled(False)
    assert repo.hourly_usage(date(2026, 10, 21)) == []
    assert repo.usage_for_day(date(2026, 10, 21))


def test_hourly_splits_a_cross_midnight_interval_and_distinguishes_observed_zero(tmp_path):
    repo = UsageRepository(tmp_path / "split.sqlite3")
    repo.set_consent("hourly_stats", True)
    first = datetime(2026, 10, 20, 23, 59, 50, tzinfo=timezone.utc)
    samples = iter(ActivitySample(t, first + timedelta(seconds=t), 0, "CODE", ActivityKind.ACTIVE, False, True)
                   for t in (0, 20))
    class Provider:
        def read_sample(self):
            return next(samples)
    ctl = MonitoringController(Provider(), initially_enabled=True)
    collector = ActivityCollector(ctl, repo)
    collector.poll_once()
    collector.poll_once()
    assert repo.hourly_usage(date(2026, 10, 20))[0]["active_seconds"] == 10
    assert repo.hourly_usage(date(2026, 10, 21))[0]["active_seconds"] == 10
    repo.add_hourly_usage(date(2026, 10, 21), 2, "IDLE", idle_seconds=10)
    assert repo.hourly_usage(date(2026, 10, 21))[-1]["active_seconds"] == 0
    repo.clear_usage()
    assert not repo.hourly_usage(date(2026, 10, 21))


def test_preview_uses_user_notes_not_codes_and_roundtrips_times():
    from PySide6.QtWidgets import QApplication
    from deskcare.ui.task_dialog import ImportPreviewDialog
    app = QApplication.instance() or QApplication([])
    source = parse_text_bytes(SCHEDULE.encode())
    dialog = ImportPreviewDialog(source)
    assert dialog.table.item(0, 4).text() == ""
    assert "截止 23:00" == dialog.table.item(0, 2).text()
    assert "截止 24:00" == dialog.table.item(1, 2).text()
    assert dialog.table.item(2, 2).text() == "19:00–20:00"
    dialog.table.item(0, 4).setText("记得带材料")
    dialog._accept()
    assert dialog.drafts[0].notes == "记得带材料"
    assert dialog.drafts[1].due_at.date() == dialog.drafts[1].planned_for + timedelta(days=1)
    assert dialog.drafts[2].starts_at.hour == 19
    assert dialog.drafts[3].time_hint == "暂定下午"
    dialog.close()
    app.processEvents()


def test_tasks_expand_paginate_and_notes_context_edit_without_losing_fields(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QInputDialog
    from deskcare.ui.pages import TodayPage
    app = QApplication.instance() or QApplication([])
    repo = UsageRepository(tmp_path / "pages.sqlite3")
    service = TaskService(repo)
    for index in range(25):
        service.add_manual(f"测试任务 {index}")
    service.add_manual("未来安排", planned_for=date.today() + timedelta(days=3))
    page = TodayPage(MonitoringController(FakeActivityProvider()), service)
    page.resize(900, 650)
    page.show()
    for _ in range(3):
        app.processEvents()
    assert page.task_pager.pages > 1
    assert page.task_table.rowCount() <= page._page_size
    assert page.task_table.verticalScrollBar().maximum() == 0
    first_id = page._tasks[0].id
    page.task_pager.next.click()
    assert page._tasks[0].id != first_id
    page.task_table.setCurrentCell(0, 1)
    target = page._selected_task()
    monkeypatch.setattr(QInputDialog, "getMultiLineText", lambda *args: ("用户备注", True))
    page._edit_notes()
    assert next(t for t in service.list_all() if t.id == target.id).notes == "用户备注"
    page.task_scope.setCurrentIndex(1)
    assert [t.title for t in page._tasks] == ["未来安排"]
    assert page.monitoring_badge.isHidden()
    page.close()


def test_usage_daily_weekly_history_hours_and_paged_apps(tmp_path):
    from PySide6.QtWidgets import QApplication
    from deskcare.ui.pages import UsagePage, SettingsPage
    app = QApplication.instance() or QApplication([])
    repo = UsageRepository(tmp_path / "history.sqlite3")
    today, yesterday = date.today(), date.today() - timedelta(days=1)
    repo.add_usage(today, "CODE", active_seconds=120)
    repo.add_usage(yesterday, "BROWSER", active_seconds=240)
    repo.set_consent("hourly_stats", True)
    repo.set_consent("app_name_stats", True)
    repo.add_hourly_usage(today, 9, "CODE", active_seconds=120)
    repo.add_hourly_usage(today, 10, "IDLE", idle_seconds=60)
    for index in range(20):
        repo.add_app_usage(today, f"app{index}", 20-index)
    ctl = MonitoringController(FakeActivityProvider(), initially_enabled=True)
    collector = ActivityCollector(ctl, repo)
    page = UsagePage(ctl, collector)
    assert len(page.week_chart.entries) == 24
    assert page.week_chart.entries[9].seconds == 120
    assert page.week_chart.entries[10].seconds == 0
    assert page.week_chart.entries[8].seconds is None
    assert page.app_pager.pages > 1
    page.period_previous.click()
    assert page.period_range() == (yesterday, yesterday)
    assert "4.0" in page.active_value.text()
    assert not page.week_chart.entries  # historical totals are not fabricated hourly data
    page.period_choice.setCurrentIndex(1)
    start, end = page.period_range()
    assert start.weekday() == 0 and end.weekday() == 6
    page.period_previous.click()
    assert page.period_range()[0] == start - timedelta(days=7)
    page.period_today.click()
    assert page.anchor_day == today
    settings = SettingsPage(ConfigStore(), ctl, collector)
    settings.reminder_interval.setValue(17)
    assert repo.get_setting("reminder_interval_minutes") == "17"
    settings.hourly_stats.setChecked(False)
    assert not repo.hourly_usage(today)
    assert repo.usage_for_day(today)
    page.close()
    settings.close()


def test_arranged_day_different_from_deadline_and_event_roundtrips(tmp_path):
    from PySide6.QtWidgets import QApplication
    from deskcare.ui.task_dialog import ImportPreviewDialog, TaskFormDialog
    from deskcare.domain.types import TaskDraft
    from deskcare.importers.base import ImportResult
    from deskcare.importers.task_times import task_time_text
    app = QApplication.instance() or QApplication([])
    today = date.today()
    later = today + timedelta(days=3)
    start = datetime.combine(later, datetime.min.time()).replace(hour=19)
    draft = TaskDraft("提前准备", due_at=start, planned_for=today)
    dialog = ImportPreviewDialog(ImportResult("demo.md", (draft,)))
    dialog._accept()
    assert dialog.drafts[0].due_at == start
    assert dialog.drafts[0].planned_for == today
    dialog.close()
    repo = UsageRepository(tmp_path / "offday.sqlite3")
    task = repo.add_task("活动准备", planned_for=today, starts_at=start, ends_at=start+timedelta(hours=1))
    assert str(later) in task_time_text(task)
    form = TaskFormDialog(task=task)
    assert form.details()["starts_at"].date() == later
    assert form.details()["ends_at"].date() == later
    form.close()


def test_hourly_storage_never_runs_without_monitoring_and_keeps_only_thirty_days(tmp_path):
    repo = UsageRepository(tmp_path / "guard.sqlite3")
    ctl = MonitoringController(FakeActivityProvider())
    collector = ActivityCollector(ctl, repo)
    collector.set_hourly_enabled(True)
    assert collector.poll_once().sampled is False
    assert not repo.hourly_usage(date.today())
    repo.add_hourly_usage(date.today()-timedelta(days=40), 1, "CODE", active_seconds=5)
    repo.add_hourly_usage(date.today(), 1, "CODE", active_seconds=5)
    assert not repo.hourly_usage(date.today()-timedelta(days=40))
    assert repo.hourly_usage(date.today())


def test_deadline_manual_clock_and_arbitrary_reminder_minutes(tmp_path):
    from PySide6.QtWidgets import QApplication
    from deskcare.ui.task_dialog import TaskFormDialog
    from deskcare.services.reminder_service import ReminderCoordinator
    QApplication.instance() or QApplication([])
    form = TaskFormDialog()
    form.title_edit.setText("手工安排")
    form.due_edit.setText("24:00")
    assert form.values()[1].date() == date.today()+timedelta(days=1)
    form.close()
    repo = UsageRepository(tmp_path / "interval.sqlite3")
    ctl = MonitoringController(FakeActivityProvider())
    collector = ActivityCollector(ctl, repo)
    coordinator = ReminderCoordinator(ctl, collector, TaskService(repo), repo)
    coordinator.set_interval(13)
    assert ReminderCoordinator.saved_interval(repo) == 13
    coordinator.set_interval(1)
    assert coordinator.policy.config.cooldown_minutes == 1


def test_decimal_hours_are_not_misread_as_multiple_hours():
    result = parse_text_bytes("- 整理演示 预计1.5小时\n- 阅读 20 minutes\n".encode())
    assert result.can_confirm
    assert result.drafts[0].estimated_minutes == 90
    assert result.drafts[1].estimated_minutes == 20


@pytest.mark.parametrize("jump", [timedelta(days=30), -timedelta(hours=1)])
def test_clock_change_does_not_fabricate_intervening_hours(tmp_path, jump):
    repo = UsageRepository(tmp_path / "clock.sqlite3")
    repo.set_consent("hourly_stats", True)
    first = datetime(2026, 10, 20, 9, tzinfo=timezone.utc)
    values = iter((ActivitySample(0, first, 0, "CODE", ActivityKind.ACTIVE, False, True),
                   ActivitySample(20, first + jump, 0, "CODE", ActivityKind.ACTIVE, False, True)))
    class Provider:
        def read_sample(self):
            return next(values)
    collector = ActivityCollector(MonitoringController(Provider(), initially_enabled=True), repo)
    collector.poll_once()
    assert collector.poll_once().reason == "clock_change"
    assert not repo.usage_for_day(first.date())
    assert not repo.hourly_usage(first.date())


def test_new_future_task_selects_its_scope_and_page(tmp_path):
    from PySide6.QtWidgets import QApplication
    from deskcare.ui.pages import TodayPage
    app = QApplication.instance() or QApplication([])
    repo = UsageRepository(tmp_path / "selected.sqlite3")
    service = TaskService(repo)
    future = date.today() + timedelta(days=1)
    for i in range(20):
        service.add_manual(f"已有安排 {i}", planned_for=future)
    page = TodayPage(MonitoringController(FakeActivityProvider()), service)
    task = service.add_manual("刚添加的后续安排", planned_for=future)
    page._show_task(task)
    assert page.task_scope.currentIndex() == 1
    assert page.task_pager.index > 0
    assert page._selected_task().id == task.id
    page.close()
    app.processEvents()
