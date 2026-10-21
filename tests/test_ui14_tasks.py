from dataclasses import replace
from datetime import date, datetime, time, timedelta

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from deskcare.domain.types import TaskStatus
from deskcare.importers.task_times import split_task_time, task_time_text
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.task_dialog import TaskFormDialog
from test_ui4_tasks import task_page


def test_completed_tasks_are_independent_and_grouped_by_real_finish_day(tmp_path):
    repo = UsageRepository(tmp_path / "tasks.sqlite3")
    service = TaskService(repo)
    today = date.today()
    old = service.add_manual("旧计划今天完成", planned_for=today-timedelta(days=5))
    future = service.add_manual("未来计划提前完成", planned_for=today+timedelta(days=7))
    open_task = service.add_manual("未完成", planned_for=today)
    service.set_status(old.id, TaskStatus.DONE)
    first_completed_at = service.list_completed()[0].completed_at
    service.set_status(old.id, TaskStatus.DONE)
    assert service.list_completed()[0].completed_at == first_completed_at
    service.set_status(future.id, TaskStatus.DONE)
    assert [task.id for task in service.list_today()] == [open_task.id]
    assert service.list_later() == []
    assert {task.id for task in service.list_completed(today)} == {old.id, future.id}
    assert not service.list_completed(today-timedelta(days=5))
    service.set_status(old.id, TaskStatus.TODO)
    assert old.id in [task.id for task in service.list_today()]
    assert old.id not in [task.id for task in service.list_completed()]


def test_unrecorded_completion_day_is_not_made_up(tmp_path):
    repo = UsageRepository(tmp_path / "tasks.sqlite3")
    service = TaskService(repo)
    task = service.add_manual("旧版日期缺失")
    with repo._connect() as connection:
        connection.execute("UPDATE tasks SET status='done', completed_at=NULL WHERE id=?", (task.id,))
    assert service.completed_day(service.list_completed()[0]) is None
    assert not service.list_completed(date.today())
    assert not service.list_today()


def test_long_event_stays_one_task_across_dates_and_never_finishes_itself(tmp_path):
    repo = UsageRepository(tmp_path / "tasks.sqlite3")
    service = TaskService(repo)
    start, end = date(2026, 10, 21), date(2026, 10, 25)
    task = service.add_manual("CTF 比赛", planned_for=start,
                             starts_at=datetime.combine(start, time.min), ends_at=datetime.combine(end, time(23,59)))
    assert task in service.list_later(start-timedelta(days=1))
    assert not service.list_today(start-timedelta(days=1))
    for offset in range(5):
        assert [row.id for row in service.list_today(start+timedelta(days=offset))] == [task.id]
    assert len(service.list_all()) == 1 and TaskService.is_long_task(task)
    assert "10/21–10/25" in TaskService.schedule_text(task)
    assert task in service.list_today(end+timedelta(days=1))  # Explicitly remains unfinished, not silently dropped.
    assert service.next_confirmed_deadline(day=start, now=datetime.combine(start, time(12)).astimezone()) is None
    assert TaskService(UsageRepository(repo.path)).list_all()[0].ends_at.date() == end


def test_long_form_creation_reload_update_and_date_validation(tmp_path):
    app = QApplication.instance() or QApplication([])
    dialog = TaskFormDialog()
    dialog.title_edit.setText("CTF 比赛")
    dialog.task_kind.setCurrentIndex(1)
    dialog.planned_edit.setText("2026-10-21")
    dialog.range_end_edit.setText("2026-10-25")
    dialog.due_edit.setText("22:00")
    details = dialog.details()
    assert details["starts_at"].date() == date(2026,10,21)
    assert details["ends_at"].date() == date(2026,10,25)
    assert dialog.values()[1].date() == date(2026,10,25)
    service = TaskService(UsageRepository(tmp_path / "tasks.sqlite3"))
    task = service.add_manual(*dialog.values(), **details)
    edit = TaskFormDialog(task=task)
    assert edit.task_kind.currentIndex() == 1 and edit.range_end_edit.text() == "2026-10-25"
    edit.range_end_edit.setText("2026-10-28")
    saved = service.update(task.id, title=task.title, due_at=task.due_at, **edit.details())
    assert saved.ends_at.date() == date(2026,10,28)
    edit.range_end_edit.setText("2026-10-20")
    with pytest.raises(ValueError): edit.details()
    edit.range_end_edit.setText("2026-10-25")
    edit.start_edit.setText("2026-10-22T10:00")
    with pytest.raises(ValueError): edit.details()
    dialog.close()
    edit.close()


def test_explicit_date_range_import_roundtrip_does_not_invent_work_duration():
    draft = split_task_time("CTF 比赛（2026-10-21 至 2026-10-25）", None, date(2026,10,21))
    assert draft.title == "CTF 比赛"
    assert draft.starts_at.date() == date(2026,10,21) and draft.ends_at.date() == date(2026,10,25)
    assert draft.estimated_minutes is None and draft.due_at is None
    assert "2026-10-25" in task_time_text(draft)
    reimport = split_task_time("CTF 比赛 " + task_time_text(draft), draft.planned_for, date(2026,10,21))
    assert reimport.ends_at == draft.ends_at
    malformed = split_task_time("CTF 2026-10-25 至 2026-10-21", None, date(2026,10,21))
    assert not malformed.starts_at and malformed.uncertainty


def test_ui_completed_date_filter_pagination_and_undo(task_page):
    app, page, service, first, second = task_page
    repo = service.repository
    yesterday = date.today()-timedelta(days=1)
    service.set_status(first.id, TaskStatus.DONE)
    service.set_status(second.id, TaskStatus.DONE)
    with repo._connect() as connection:
        connection.execute("UPDATE tasks SET completed_at=? WHERE id=?",
                           (datetime.combine(yesterday, time(18)).astimezone().isoformat(), second.id))
    page.task_scope.setCurrentIndex(2)
    app.processEvents()
    assert page.completed_date.isVisible()
    assert page.task_table.horizontalHeaderItem(2).text() == "完成时间"
    page.completed_date.setCurrentIndex(page.completed_date.findData(yesterday.isoformat()))
    assert len(page._tasks) == 1 and page._tasks[0].id == second.id
    control = page.task_table.cellWidget(0,0)
    control.setCurrentIndex(control.findData(TaskStatus.TODO))
    app.processEvents()
    page.task_scope.setCurrentIndex(0)
    assert [task.id for task in page._tasks] == [second.id]
    page._show_task(service.list_completed()[0])
    assert page.task_scope.currentIndex() == 2 and page._selected_task().id == first.id


def test_completed_unknown_date_filter_and_long_date_display(task_page):
    app, page, service, first, second = task_page
    with service.repository._connect() as connection:
        connection.execute("UPDATE tasks SET status='done', completed_at=NULL WHERE id=?", (first.id,))
    page.task_scope.setCurrentIndex(2)
    page.completed_date.setCurrentIndex(page.completed_date.findData("unknown"))
    assert len(page._tasks) == 1 and "未记录" in page.task_table.item(0,2).text()
    day = date.today()
    task = service.add_manual("CTF", planned_for=day, starts_at=datetime.combine(day,time.min),
                              ends_at=datetime.combine(day+timedelta(days=3), time(23,59)))
    page._show_task(task)
    row = next(i for i, row in enumerate(page._tasks) if row.id == task.id)
    assert "长期" in page.task_table.item(row,2).text()
