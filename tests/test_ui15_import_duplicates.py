from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog

from deskcare.domain.types import TaskDraft, TaskStatus
from deskcare.domain.task_duplicates import review_import
from deskcare.importers.base import ImportResult
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.task_dialog import ImportPreviewDialog


@pytest.fixture(scope="module", autouse=True)
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance
    instance.processEvents()


@pytest.fixture
def service(tmp_path):
    return TaskService(UsageRepository(tmp_path / "fictional.sqlite3"))


def preview(service, *drafts):
    return ImportPreviewDialog(ImportResult("fictional.md", tuple(drafts)), existing_tasks=service.list_all)


@pytest.mark.parametrize("status", list(TaskStatus))
def test_existing_tasks_all_statuses_and_renamed_files(service, status):
    day = date(2031, 1, 2)
    task = service.add_manual("CTF 练习", planned_for=day, notes="保留我的备注", estimated_minutes=30)
    service.set_status(task.id, status)
    before = service.list_all()[0]
    assert service.confirm_import([TaskDraft("ＣＴＦ  练习", planned_for=day)], "renamed.csv") == []
    assert service.list_all() == [before]


def test_ai_estimated_minutes_do_not_create_duplicates(service):
    day = date.today()
    service.add_manual("实验报告", planned_for=day, estimated_minutes=90)
    draft = TaskDraft("实验报告", estimated_minutes=120, estimate_is_suggestion=True, planned_for=day)
    assert review_import([draft], service.list_all())[0].kind == "duplicate"
    assert not service.confirm_import([draft], "ai.md")


@pytest.mark.parametrize("changes", [{"notes": "附加说明"}, {"estimated_minutes": 120}])
def test_new_user_details_are_reviewable_not_silently_lost(service, changes):
    service.add_manual("实验报告", planned_for=date.today(), estimated_minutes=60)
    draft = TaskDraft("实验报告", planned_for=date.today(), **changes)
    dialog = preview(service, draft)
    assert "可能重复" in dialog.table.item(0, 5).text()
    assert not dialog.confirm.isEnabled()
    dialog.table.item(0, 5).setCheckState(Qt.CheckState.Checked)
    dialog._accept()
    assert dialog.result() == QDialog.DialogCode.Accepted
    assert dialog.drafts == (replace(draft, source_row=1),)
    assert len(service.list_all()) == 1  # preview never writes
    dialog.close()


def test_different_dates_and_clock_times_are_distinct(service):
    day = date(2031, 1, 2)
    start = datetime(2031, 1, 2, 9)
    service.add_manual("例会", planned_for=day, starts_at=start, ends_at=start+timedelta(hours=1))
    drafts = [TaskDraft("例会", planned_for=day+timedelta(days=1)),
              TaskDraft("例会", planned_for=day, starts_at=start+timedelta(hours=2))]
    assert [m.kind for m in review_import(drafts, service.list_all())] == ["new", "new"]
    assert len(service.confirm_import(drafts, "weekly.md")) == 2


def test_long_task_same_range_skipped_different_range_preserved(service):
    start, end = datetime(2031, 1, 2), datetime(2031, 1, 5, 23, 59)
    task = service.add_manual("CTF 比赛", planned_for=start.date(), starts_at=start, ends_at=end)
    same = TaskDraft("CTF 比赛", planned_for=start.date(), starts_at=start, ends_at=end)
    changed = replace(same, ends_at=end+timedelta(days=1))
    assert [m.kind for m in review_import([same, changed], [task])] == ["duplicate", "new"]
    assert len(service.confirm_import([same, changed], "ctf.md")) == 1


def test_timezone_and_inferred_date_equivalence(service):
    due = datetime(2031, 1, 2, 18).astimezone()
    service.add_manual("交作业", due_at=due, planned_for=due.date())
    draft = TaskDraft("交作业", due_at=due.astimezone(timezone.utc))
    assert not service.confirm_import([draft], "utc.csv")


def test_missing_time_or_similar_name_only_warns(service):
    service.add_manual("完成实验报告", planned_for=date.today(), due_at=datetime.combine(date.today(), datetime.min.time()))
    for draft in [TaskDraft("完成实验报告"), TaskDraft("实验报告")]:
        assert review_import([draft], service.list_all())[0].kind == "possible"


def test_duplicate_batch_retained_visually_and_only_new_imported(service):
    service.add_manual("已有任务")
    dialog = preview(service, TaskDraft("已有任务"), TaskDraft("新任务"), TaskDraft(" 新任务 "))
    assert dialog.table.rowCount() == 3
    assert [dialog.table.item(i, 5).checkState() for i in range(3)] == [Qt.CheckState.Unchecked, Qt.CheckState.Checked, Qt.CheckState.Unchecked]
    assert "将导入 1 项，跳过 2 项" in dialog.issue_label.text()
    dialog._accept()
    assert [d.title for d in dialog.drafts] == ["新任务"]
    assert len(service.confirm_import(dialog.drafts, "fictional.md")) == 1
    dialog.close()


def test_editing_schedule_rechecks_and_manual_uncheck_survives_refresh(service):
    service.add_manual("已有任务", planned_for=date.today())
    dialog = preview(service, TaskDraft("已有任务", planned_for=date.today()))
    dialog.table.item(0, 1).setText((date.today()+timedelta(days=1)).isoformat())
    assert dialog.confirm.isEnabled()
    assert dialog.table.item(0, 5).text() == "新任务"
    dialog.table.item(0, 5).setCheckState(Qt.CheckState.Unchecked)
    dialog._refresh_validation()
    assert not dialog.confirm.isEnabled()
    dialog.close()


def test_recheck_if_task_added_during_preview_and_before_persistence(service):
    dialog = preview(service, TaskDraft("并发任务"))
    service.add_manual("并发任务")
    dialog._accept()
    assert not dialog.drafts
    assert dialog.result() != QDialog.DialogCode.Accepted
    assert not service.confirm_import([TaskDraft("并发任务")], "changed.md")
    assert len(service.list_all()) == 1
    dialog.close()


def test_atomic_rollback_on_invalid_new_row(service):
    service.add_manual("保留任务")
    with pytest.raises(ValueError):
        service.confirm_import([TaskDraft("新任务"), TaskDraft("坏任务", estimated_minutes=-1)], "invalid.csv")
    assert [t.title for t in service.list_all()] == ["保留任务"]


def test_parallel_imports_serialize_recheck(service):
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda name: service.repository.import_tasks([TaskDraft("同一事项")], name), ["a.md", "b.csv"]))
    assert sorted(map(len, results)) == [0, 1]
    assert len(service.list_all()) == 1


def test_notes_and_completion_never_overwritten_by_import(service):
    task = service.add_manual("已完成事项", notes="原有备注", estimated_minutes=50)
    service.set_status(task.id, TaskStatus.DONE)
    original = service.list_all()[0]
    assert not service.confirm_import([TaskDraft("已完成事项", estimated_minutes=45, estimate_is_suggestion=True)], "new.md")
    assert service.list_all() == [original]


def test_deselected_invalid_row_does_not_block_other_tasks(service):
    dialog = preview(service, TaskDraft("有效任务"), TaskDraft("修改中的任务"))
    dialog.table.item(1, 3).setText("not minutes")
    assert not dialog.confirm.isEnabled()
    dialog.table.item(1, 5).setCheckState(Qt.CheckState.Unchecked)
    assert dialog.confirm.isEnabled()
    dialog._accept()
    assert [d.title for d in dialog.drafts] == ["有效任务"]
    dialog.close()


def test_cancel_and_all_duplicates_make_no_changes(service):
    service.add_manual("已完成记录")
    before = service.list_all()
    dialog = preview(service, TaskDraft("已完成记录"))
    assert not dialog.confirm.isEnabled()
    dialog.reject()
    assert service.list_all() == before
    assert not dialog.drafts
    dialog.close()


def test_ai_completion_rechecks_same_local_database(service):
    service.add_manual("原有任务")
    dialog = preview(service, TaskDraft("原有任务"), TaskDraft("原始新任务"))
    result = ImportResult("fictional.md", (TaskDraft("原有任务", estimated_minutes=80, estimate_is_suggestion=True),
                                           TaskDraft("AI新任务"), TaskDraft("AI新任务")))
    dialog._on_ai_finished(dialog._ai_generation, result, "")
    assert dialog.table.item(0, 5).checkState() == Qt.CheckState.Unchecked
    dialog._accept()
    assert [d.title for d in dialog.drafts] == ["AI新任务"]
    assert [t.title for t in service.list_all()] == ["原有任务"]
    dialog.close()


def test_cloud_request_does_not_upload_existing_task_library(service):
    from deskcare.ai.cloud_task_assistant import CloudTaskAssistant
    from test_m9_cloud import MemoryCredentials, Response
    service.add_manual("PRIVATE_EXISTING_TASK_DO_NOT_SEND")
    calls = []
    def transport(request, **kwargs):
        calls.append(json.loads(request.data))
        return Response({"choices": [{"message": {"content": json.dumps({"tasks": [
            {"title": "新条目", "estimated_minutes": 30}, {"title": "新条目", "estimated_minutes": 30}]})}}]})
    cloud = CloudTaskAssistant(service.repository, MemoryCredentials(), request_fn=transport)
    cloud.configure("https://api.example.test/chat", "fake-model")
    cloud.set_enabled(True)
    cloud.save_key("fictional-test-credential")
    request = cloud.prepare("- 新条目\n".encode(), "selected.md")
    assert calls == []
    assert "PRIVATE_EXISTING" not in request.preview()
    assert "同一日期和时段" in request.preview()
    result = cloud.parse(request)
    assert len(calls) == 1
    dialog = preview(service, *result.drafts)
    dialog._accept()
    assert len(service.confirm_import(dialog.drafts, result.source_name)) == 1
    assert len(service.list_all()) == 2
    dialog.close()


def test_model_paraphrase_keeps_source_name_and_is_checked_again(service):
    from deskcare.ai.optional_local_llm import LocalLLMClient
    day = date.today()
    source = f"# {day.isoformat()}\n- 实验报告（ddl 23:00）\n"
    due = datetime.combine(day, datetime.min.time()).replace(hour=23)
    service.add_manual("实验报告", planned_for=day, due_at=due)
    result = LocalLLMClient._to_import_result({"tasks": [
        {"title": "完成实验报告", "estimated_minutes": 90, "due_at": None}]}, source, "new-name.md")
    assert result.drafts[0].title == "实验报告"
    assert result.drafts[0].due_at == due
    dialog = preview(service, *result.drafts)
    assert "已存在" in dialog.table.item(0, 5).text()
    assert not dialog.confirm.isEnabled()
    dialog.close()
