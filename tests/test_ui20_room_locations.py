"""Room fallback must be literal, task-bound, editable and model-independent."""
from datetime import date, datetime
import json

import pytest

from deskcare.ai.optional_local_llm import LocalLLMClient
from deskcare.importers.csv_importer import parse_csv_bytes
from deskcare.importers.task_locations import split_room_location
from deskcare.importers.text_importer import parse_text_bytes
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository


def ai(source, *items):
    return LocalLLMClient._to_import_result({'tasks': list(items)}, source, 'fictional.md')


@pytest.mark.parametrize('room', ['北4-205', '北2-112', '东1A-101', '西2-202', '南12-1205', '中2-301',
                                  '北４－２０５', '北4–205', '北4—205', '北4 - 205', '北4-205教室'])
def test_literal_room_survives_offline_import_with_schedule(room):
    source = f'# 2031-10-23\n- CSSU全员大会（{room}）（15:00-17:00）\n'
    result = parse_text_bytes(source.encode())
    task = result.drafts[0]
    assert task.title == 'CSSU全员大会'
    assert task.notes == '地点：' + room
    assert task.source_row == 2
    assert task.planned_for == date(2031, 10, 23)
    assert (task.starts_at.hour, task.ends_at.hour, task.estimated_minutes) == (15, 17, 120)
    assert 'rule_room_location' in task.uncertainty


@pytest.mark.parametrize('text', ['例会 北4-205', '例会（北4-205）', '例会(北4-205',
                                 '例会（地点：北4-205）', '例会 @北4-205', '例会在北4-205',
                                 '例会，北4-205', '例会（教室：北4-205）'])
def test_supported_contexts(text):
    task = parse_text_bytes(('- ' + text).encode()).drafts[0]
    assert task.title == '例会'
    assert task.notes == '地点：北4-205'


@pytest.mark.parametrize('text', [
    '提交材料（ddl 24:00）', '准备会议（15:00-17:00）', '任务 2026-10-23',
    '完成题目 4-205', 'HW4-205', 'CTF A4-205', '北4-205', '任务编号（北4-205）',
    '版本 北4-205', '工单：北4-205', '讲解北4-205漏洞', '不要在北4-205',
    '例会（北4-205或北2-112）', '例会（北4-205、北2-112）', '地点未定',
    '- 例会 北4-205\n- 自习 北2-112', '例会（北4-2050X9）',
])
def test_ambiguous_or_non_location_text_is_not_extracted(text):
    assert split_room_location(text) == (text, '')


@pytest.mark.parametrize('clock,attr', [('10:00', 'starts_at'), ('ddl 24:00', 'due_at')])
def test_single_clock_and_deadline_not_broken_by_location_removal(clock, attr):
    task = parse_text_bytes(f'# 2031-10-23\n- 例会（北4-205）（{clock}）'.encode()).drafts[0]
    assert task.title == '例会' and task.notes == '地点：北4-205'
    assert getattr(task, attr) == (datetime(2031, 10, 23, 10) if attr == 'starts_at' else datetime(2031, 10, 24))


def test_shared_parentheses_and_long_task_keep_times_and_estimate():
    source = '# 2031-10-23\n- 例会（北4-205，15:00-17:00）\n- CTF比赛（北2-112）（2031-10-24 至 2031-10-27）（预计2小时）'
    first, long = parse_text_bytes(source.encode()).drafts
    assert first.title == '例会' and first.notes == '地点：北4-205'
    assert first.starts_at.hour == 15 and first.ends_at.hour == 17
    assert long.title == 'CTF比赛' and long.notes == '地点：北2-112'
    assert long.starts_at.date() == date(2031, 10, 24) and long.ends_at.date() == date(2031, 10, 27)
    assert long.estimated_minutes == 120


@pytest.mark.parametrize('location,row', [(None, 2), ('北4-205教室', 2), ('西2-999', 2), ('北4-205', 1), ('北4-205', None)])
def test_ai_omission_rewrite_hallucination_wrong_row_does_not_lose_source_room(location, row):
    source = '# 2031-10-23\n- CSSU全员大会（北4-205）（15:00-17:00）'
    task = ai(source, {'title': 'CSSU全员大会', 'location': location, 'source_row': row, 'estimated_minutes': 30}).drafts[0]
    assert task.title == 'CSSU全员大会' and task.notes == '地点：北4-205'
    assert (task.starts_at.hour, task.ends_at.hour, task.estimated_minutes) == (15, 17, 120)


def test_same_name_different_rooms_and_empty_model_items_keep_their_own_source():
    source = '# 2031-10-23\n- 例会（北4-205）（15:00-17:00）\n- 例会（北2-112）（19:00-20:00）'
    tasks = ai(source, {'title': '例会', 'location': None}).drafts
    assert [t.notes for t in tasks] == ['地点：北4-205', '地点：北2-112']
    assert [t.starts_at.hour for t in tasks] == [15, 19]


def test_rule_room_preserves_ai_estimate_for_task_without_explicit_duration():
    task = ai('- 准备材料（北4-205）', {'title': '准备材料', 'estimated_minutes': 45}).drafts[0]
    assert task.title == '准备材料' and task.notes == '地点：北4-205'
    assert task.estimated_minutes == 45 and task.estimate_is_suggestion


def test_csv_room_rule_does_not_replace_explicit_fields():
    source = 'title,due_at,estimated_minutes\n"讨论会（北4-205）",2031-10-23T18:00,60\n'
    task = parse_csv_bytes(source.encode()).drafts[0]
    assert (task.title, task.notes, task.estimated_minutes) == ('讨论会', '地点：北4-205', 60)
    assert task.due_at == datetime(2031, 10, 23, 18)


def test_xlsx_room_rule_uses_bounded_cell_extraction():
    from io import BytesIO
    from zipfile import ZipFile
    from test_m2_importers import _xlsx_bytes
    from deskcare.importers.xlsx_importer import parse_xlsx_bytes
    output = BytesIO()
    with ZipFile(BytesIO(_xlsx_bytes())) as source, ZipFile(output, 'w') as target:
        for name in source.namelist():
            target.writestr(name, source.read(name).replace('复习项目'.encode(), '例会（北4-205）'.encode()))
    task = parse_xlsx_bytes(output.getvalue()).drafts[0]
    assert (task.title, task.notes, task.estimated_minutes) == ('例会', '地点：北4-205', 30)
    assert task.due_at == datetime(2026, 10, 20, 18)


def test_invalid_model_generic_location_is_still_rejected():
    source = '- 讨论会（地点：活动中心201）'
    task = ai(source, {'title': '讨论会', 'location': '西2-999', 'source_row': 1}).drafts[0]
    assert task.notes == '' and '活动中心201' in task.title


@pytest.mark.parametrize('text', ['例会 北4-205（10:00）', '例会（10:00，北4-205）'])
def test_adjacent_room_and_single_clock_remain_separate(text):
    task = parse_text_bytes(('# 2031-10-23\n- ' + text).encode()).drafts[0]
    assert task.title == '例会' and task.notes == '地点：北4-205'
    assert task.starts_at == datetime(2031, 10, 23, 10)


def test_room_only_task_with_clock_does_not_disappear():
    task = parse_text_bytes('- （北4-205）（10:00）'.encode()).drafts[0]
    assert task.title == '北4-205' and task.notes == ''


def test_older_title_with_room_is_not_misreported_as_new_task(tmp_path):
    from deskcare.domain.task_duplicates import review_import
    repo = UsageRepository(tmp_path / 'fictional.sqlite3')
    service = TaskService(repo)
    old = service.add_manual('CSSU全员大会(北4-205', planned_for=date(2031, 10, 23),
                             starts_at=datetime(2031, 10, 23, 15), ends_at=datetime(2031, 10, 23, 17), estimated_minutes=120)
    incoming = parse_text_bytes('# 2031-10-23\n- CSSU全员大会（北4-205）（15:00-17:00）'.encode()).drafts
    assert review_import(incoming, [old])[0].kind == 'possible'


def test_preview_personal_notes_and_reimport_dedup_are_preserved(tmp_path):
    from PySide6.QtWidgets import QApplication
    from deskcare.ui.task_dialog import ImportPreviewDialog
    app = QApplication.instance() or QApplication([])
    repo = UsageRepository(tmp_path / 'fictional.sqlite3')
    service = TaskService(repo)
    source = '# 2031-10-23\n- 例会（北4-205）（15:00-17:00）'
    initial = parse_text_bytes(source.encode(), 'fictional.md')
    dialog = ImportPreviewDialog(initial, existing_tasks=service.list_all)
    assert '本机' in dialog.table.item(0, 4).toolTip()
    dialog.table.item(0, 4).setText('记得带电脑\n地点：北4-205')
    dialog._notes_before_ai = [(2, '例会', '记得带电脑\n地点：北4-205')]
    dialog._on_ai_finished(dialog._ai_generation, ai(source, {'title': '例会', 'location': None}), '')
    assert dialog.table.item(0, 4).text() == '记得带电脑\n地点：北4-205'
    assert not service.list_all()
    dialog._accept()
    added = service.confirm_import(dialog.drafts, 'fictional.md')
    assert added[0].title == '例会' and added[0].notes == '记得带电脑\n地点：北4-205'
    assert service.confirm_import(dialog.drafts, 'renamed.md') == []
    dialog.close()
    app.processEvents()


def test_cloud_uses_same_fallback_without_additional_upload(tmp_path):
    from deskcare.ai.cloud_task_assistant import CloudTaskAssistant
    from test_m9_cloud import MemoryCredentials, Response
    repo = UsageRepository(tmp_path / 'fictional.sqlite3')
    repo.add_task('PRIVATE_TASK_LIBRARY')
    calls = []
    def transport(request, **kwargs):
        calls.append(request.data)
        return Response({'choices': [{'message': {'content': json.dumps({'tasks': [
            {'title': '例会', 'location': None, 'source_row': 2}]}, ensure_ascii=False)}}]})
    cloud = CloudTaskAssistant(repo, MemoryCredentials(), request_fn=transport)
    cloud.configure('https://api.example.test/chat', 'fictional-model')
    cloud.set_enabled(True)
    cloud.save_key('fictional-test-credential')
    source = '# 2031-10-23\n- 例会（北4-205）（15:00-17:00）'
    request = cloud.prepare(source.encode(), 'fictional.md')
    assert not calls
    assert '北4-205' in cloud.SYSTEM_PROMPT
    assert 'PRIVATE_TASK_LIBRARY' not in request.preview()
    assert json.loads(request.body)['messages'][-1]['content'] == source
    task = cloud.parse(request).drafts[0]
    assert task.notes == '地点：北4-205' and task.title == '例会'
    assert len(calls) == 1
