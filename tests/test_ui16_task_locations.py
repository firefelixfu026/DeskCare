from datetime import date, datetime
from dataclasses import replace
import json
from time import monotonic, sleep

import pytest
from PySide6.QtWidgets import QApplication

from deskcare.ai.optional_local_llm import LocalLLMClient
from deskcare.importers.task_locations import checked_location, merge_notes
from deskcare.importers.text_importer import parse_text_bytes
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.task_dialog import ImportPreviewDialog
from deskcare.domain.task_duplicates import review_import


@pytest.fixture(scope="module", autouse=True)
def app():
    instance = QApplication.instance() or QApplication([])
    yield instance
    instance.processEvents()


def parse(source, *tasks, filename="fictional.md"):
    return LocalLLMClient._to_import_result({"tasks": list(tasks)}, source, filename)


def test_location_moves_to_notes_without_losing_time_or_source_title():
    source = "# 2031-10-23\n- CSSU全员大会（19:00-20:00）（地点：东1A-101）\n"
    result = parse(source, dict(title="CSSU全员大会", location="东1A-101", source_row=2, estimated_minutes=120))
    task = result.drafts[0]
    assert task.title == "CSSU全员大会"
    assert task.notes == "地点：东1A-101"
    assert task.planned_for == date(2031, 10, 23)
    assert task.starts_at.hour == 19 and task.ends_at.hour == 20
    assert task.estimated_minutes == 60 and not task.estimate_is_suggestion


def test_location_with_deadline_estimate_and_long_range():
    source = "# 2031-10-23\n- 提交比赛材料（ddl 24:00）（地点：活动中心201）\n- CTF比赛（2031-10-24 至 2031-10-27）（地点：线上平台）\n"
    result = parse(source, dict(title="提交比赛材料", location="活动中心201", source_row=2, estimated_minutes=45),
                   dict(title="CTF比赛", location="线上平台", source_row=3, estimated_minutes=120))
    first, long = result.drafts
    assert first.due_at == datetime(2031, 10, 24)
    assert first.notes == "地点：活动中心201"
    assert long.title == "CTF比赛" and long.notes == "地点：线上平台"
    assert long.starts_at.date() == date(2031, 10, 24) and long.ends_at.date() == date(2031, 10, 27)


@pytest.mark.parametrize("location,row", [("西2-888", 2), ("东1A-101", 1), ("东1A-101", True),
    ("东1A-101", 999), ("东1A-101", "2"), ("东1A-101\n地点", 2), ({"text": "东1A-101"}, 2), ("x"*161, 2)])
def test_invalid_or_hallucinated_places_never_enter_notes(location, row):
    source = "# 2031-10-23\n- 例会（地点：东1A-101）\n"
    result = parse(source, dict(title="例会（地点：东1A-101）", location=location, source_row=row))
    assert result.drafts[0].notes == ""
    assert "东1A-101" in result.drafts[0].title  # source text is not erased


def test_missing_location_supported_without_changing_legacy_result():
    result = parse("- 整理笔记\n", dict(title="整理笔记", estimated_minutes=30))
    assert result.drafts[0].title == "整理笔记" and result.drafts[0].notes == ""


def test_missing_line_number_only_accepts_a_unique_literal_source_line():
    assert checked_location("东1A-101", None, "- 例会 东1A-101\n") == ("东1A-101", 1)
    assert checked_location("东1A-101", None, "- 例会 东1A-101\n- 自习 东1A-101\n") is None
    result = parse("- 例会（地点：东1A-101）\n", dict(title="例会", location="东1A-101"))
    assert result.drafts[0].notes == "地点：东1A-101"


def test_locations_are_bound_to_their_own_activities():
    source = "- 组会（地点：东1A-101）\n- 社团例会（地点：西2-202）\n"
    result = parse(source, dict(title="组会", location="西2-202", source_row=2),
                   dict(title="社团例会", location="东1A-101", source_row=1))
    assert [task.notes for task in result.drafts] == ["", ""]
    assert "东1A-101" in result.drafts[0].title
    assert "西2-202" in result.drafts[1].title


def test_same_named_activities_keep_separate_locations():
    source = "# 2031-10-23\n- 例会（19:00-20:00）（地点：东1A-101）\n- 例会（21:00-22:00）（地点：西2-202）\n"
    result = parse(source, dict(title="例会", location="西2-202", source_row=3),
                   dict(title="例会", location="东1A-101", source_row=2))
    assert [task.notes for task in result.drafts] == ["地点：东1A-101", "地点：西2-202"]
    assert [task.starts_at.hour for task in result.drafts] == [19, 21]


def test_csv_location_in_title_maps_to_correct_data_row():
    source = 'title,due_at,estimated_minutes\n"讨论会（地点：活动中心201）",2031-10-23T18:00,60\n'
    result = parse(source, dict(title="讨论会", location="活动中心201", source_row=2), filename="fictional.csv")
    task = result.drafts[0]
    assert task.title == "讨论会" and task.notes == "地点：活动中心201"
    assert task.due_at == datetime(2031, 10, 23, 18) and task.estimated_minutes == 60


def test_personal_notes_survive_async_ai_and_location_is_appended(app):
    source = "- 讨论会（地点：活动中心201）\n"
    initial = parse_text_bytes(source.encode(), "fictional.md")
    result = parse(source, dict(title="讨论会", location="活动中心201", source_row=1))
    dialog = ImportPreviewDialog(initial)
    dialog.table.item(0, 4).setText("记得带电脑")
    dialog._start_parser(lambda: result, "模拟整理", "虚构数据")
    end = monotonic()+5
    while dialog._ai_thread is not None and monotonic() < end:
        app.processEvents()
        sleep(.005)
    assert dialog._ai_thread is None
    assert dialog.table.item(0, 4).text() == "记得带电脑\n地点：活动中心201"
    dialog._accept()
    assert dialog.drafts[0].notes == "记得带电脑\n地点：活动中心201"
    dialog.close()


def test_location_notes_can_be_edited_and_only_persist_after_confirmation(tmp_path):
    source = "- 讨论会（地点：活动中心201）\n"
    result = parse(source, dict(title="讨论会", location="活动中心201", source_row=1))
    service = TaskService(UsageRepository(tmp_path / "fictional.sqlite3"))
    dialog = ImportPreviewDialog(result, existing_tasks=service.list_all)
    assert service.list_all() == []
    dialog.table.item(0, 4).setText("地点：活动中心201；记得带电脑")
    dialog._accept()
    added = service.confirm_import(dialog.drafts, "fictional.md")
    assert added[0].notes == "地点：活动中心201；记得带电脑"
    assert service.confirm_import(dialog.drafts, "renamed.md") == []
    dialog.close()


def test_legacy_title_with_location_is_still_flagged_as_possible_duplicate(tmp_path):
    service = TaskService(UsageRepository(tmp_path / "fictional.sqlite3"))
    old = service.add_manual("讨论会（地点：活动中心201）")
    result = parse("- 讨论会（地点：活动中心201）\n", dict(title="讨论会", location="活动中心201", source_row=1))
    assert review_import(result.drafts, [old])[0].kind == "possible"


def test_repeated_ai_notes_are_not_duplicated_or_overflowed():
    assert merge_notes("记得带电脑\n地点：东1A-101", "地点：东1A-101") == "记得带电脑\n地点：东1A-101"
    assert merge_notes("x"*4000, "地点：东1A-101") == "x"*4000 + "\n地点：东1A-101"


def test_over_limit_notes_are_preserved_for_editing_but_block_confirmation():
    source = "- 讨论会（地点：活动中心201）\n"
    result = parse(source, dict(title="讨论会", location="活动中心201", source_row=1))
    dialog = ImportPreviewDialog(result)
    dialog.table.item(0, 4).setText(merge_notes("x"*4000, result.drafts[0].notes))
    assert not dialog.confirm.isEnabled()
    assert "4000" in dialog.issue_label.text()
    assert "地点：活动中心201" in dialog.table.item(0, 4).text()
    dialog.close()


def test_cloud_prompt_requests_location_but_never_adds_library_to_payload(tmp_path):
    from deskcare.ai.cloud_task_assistant import CloudTaskAssistant
    from test_m9_cloud import MemoryCredentials, Response
    repo = UsageRepository(tmp_path / "fictional.sqlite3")
    repo.add_task("PRIVATE_TASK_LIBRARY")
    calls = []
    def transport(request, **kwargs):
        calls.append(request.data)
        return Response({"choices": [{"message": {"content": json.dumps({"tasks": [
            {"title": "讨论会", "location": "活动中心201", "source_row": 1}]}, ensure_ascii=False)}}]})
    cloud = CloudTaskAssistant(repo, MemoryCredentials(), request_fn=transport)
    cloud.configure("https://api.example.test/chat", "fictional-model")
    cloud.set_enabled(True)
    cloud.save_key("fictional-test-credential")
    source = "- 讨论会（地点：活动中心201）\n"
    request = cloud.prepare(source.encode(), "fictional.md")
    assert not calls
    assert "location" in request.preview() and "PRIVATE_TASK_LIBRARY" not in request.preview()
    assert json.loads(request.body)["messages"][-1]["content"] == source
    assert cloud.parse(request).drafts[0].notes == "地点：活动中心201"
