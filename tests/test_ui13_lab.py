import json
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

import pytest

from test_ui11_reminder_advice import setup, transport
from test_ui12_assistant import assistant, plan
from deskcare.domain.durations import explicit_reminder_minutes
from deskcare.domain.lab_reading import LabRow, parse_lab_text, reference_bounds, render_reading, unit_key
from deskcare.importers.lab_source import LabSourceError, _ocr_rows, read_selected_lab_source, windows_ocr
from deskcare.services.lab_reading_service import LabReadingService
from deskcare.services.reminder_advice import AdviceError


@pytest.mark.parametrize("text,expected", [
    ("把休息提醒改成一个小时，我准备专注地做浙客松的项目，预计22点30之前做完", 60),
    ("把提醒间隔改成一个小时", 60), ("把提醒改成半小时", 30),
    ("把提醒改成一个半小时", 90), ("把提醒改成1.5小时", 90),
    ("每隔一小时二十分钟提醒", 80), ("把提醒设置为两小时", 120),
    ("把间隔设为一刻钟", 15), ("把提醒改为四十五分钟", 45),
    ("把提醒改成一个小时，任务预计120分钟", 60),
    ("任务预计两小时，预计22点30完成", None), ("不要把提醒改成60分钟", None),
    ("把提醒改成30分钟；把提醒改成60分钟", None),
    ("提醒间隔合理吗？两小时任务", None), ("把提醒改成22点30", None),
])
def test_explicit_duration(text, expected):
    assert explicit_reminder_minutes(text) == expected


def test_user_hour_phrase_becomes_a_confirmable_sixty_not_task_deadline(setup):
    service = assistant(setup, {})
    service.set_enabled(True)
    text = "把休息提醒改成一个小时，我准备专注地做浙客松的项目，预计22点30之前做完"
    proposal = plan(service, text, {"tool": "set_interval", "arguments": {"minutes": 60}})
    assert json.loads(proposal.request.body)["messages"][1]["content"].find('"explicit_reminder_minutes": 60') >= 0
    assert setup.coord.policy.config.break_candidate_minutes == 40
    with pytest.raises(AdviceError): service.execute(proposal)
    service.execute(proposal, confirmed=True)
    assert setup.coord.policy.config.break_candidate_minutes == 60
    assert setup.coord.mode == "normal" and not setup.tasks.list_all()


def test_assistant_only_opens_independent_lab_entry(setup):
    service = assistant(setup, {})
    service.set_enabled(True)
    proposal = plan(service, "打开检验单阅读", {"tool": "open_lab", "arguments": {}})
    assert service.execute(proposal).open_view == "lab"
    assert not setup.repo.get_consent("lab_reading")


@pytest.mark.parametrize("value,reference,state", [
    ("3.5", "3.5-9.5", "within"), ("9.5", "3.5–9.5", "within"),
    ("9.6", "3.5～9.5", "high"), ("3.4", "3.5至9.5", "low"),
    ("4", "<4", "high"), ("4", "<=4", "within"),
    ("4", ">4", "low"), ("4", "≥4", "within"),
    ("nan", "3.5-9.5", "unknown"), ("<2", "3.5-9.5", "unknown"),
    ("6", "", "unknown"), ("6", "男3-9 女4-10", "unknown"),
    ("6", "9.5-3.5", "unknown"), ("-1", "3-9", "unknown"),
])
def test_report_only_range_arithmetic(value, reference, state):
    assert LabRow("WBC", value, "10^9/L", reference, True).check()[0] == state


def test_unconfirmed_unknown_units_and_markers_never_get_invented_ranges():
    row = LabRow("WBC", "6", "10^9/L", "3.5-9.5")
    assert row.check()[0] == "unknown"
    assert replace(row, confirmed=True, unit="g/L").check()[0] == "unknown"
    assert replace(row, confirmed=True, name="其他指标").check()[0] == "unknown"
    assert unit_key("×10⁹ / L") == "10^9/l"
    assert reference_bounds("1-2-3") is None


def test_parse_leaves_numbers_for_human_verification_and_unknown_lines_visible():
    rows, missed = parse_lab_text("白细胞计数 10.2 ↑ 10^9/L 3.5-9.5\nHb 130 g/L 120-170\nPLT 200 10^9/L\n患者示例 123\n其他指标 6 mmol/L 3-9")
    assert len(rows) == 3 and missed == 2
    assert rows[0].result == "10.2" and rows[0].reference == "3.5-9.5" and rows[0].unit == "10^9/L"
    assert rows[1].code == "HGB" and not any(row.confirmed for row in rows)
    assert rows[2].reference == ""
    with pytest.raises(ValueError): render_reading(rows)
    hct, _ = parse_lab_text("HCT 0.41 L/L 0.35-0.45")
    assert hct[0].unit == "L/L"


def lab(s, raw=None, calls=None, during=None):
    service = LabReadingService(s.repo, cloud_ai=s.cloud, now=lambda: s.now[0],
                               request_fn=transport(raw or {"focus_codes": ["WBC"], "question_ids": ["repeat"]},
                                                    calls if calls is not None else [], during))
    return service


def verified(service):
    service.set_enabled(True)
    service.replace_rows((LabRow("白细胞", "10.2", "10^9/L", "3.5-9.5", True),))


def test_report_scopes_are_separate_session_only_and_readable_preview(setup):
    service, calls = lab(setup), []
    setup.repo.set_consent("assistant_tools_ai", True)
    setup.repo.set_consent("cloud_task_ai", True)
    with pytest.raises(AdviceError): service.replace_rows((LabRow("WBC", "1", "", ""),))
    verified(service)
    assert "高于报告范围" in service.local_reading()
    with pytest.raises(AdviceError): service.prepare("cloud")
    service.set_ai_enabled(True)
    service.request_fn = transport({"focus_codes": ["WBC"], "question_ids": ["repeat"]}, calls)
    request = service.prepare("cloud")
    assert not calls and "response_format" not in request.human_preview()
    payload = json.loads(json.loads(request.body)["messages"][1]["content"])
    assert set(payload) == {"verified_indicators", "codes", "question_choices"}
    assert payload["verified_indicators"][0] == {"code": "WBC", "result": "10.2", "unit": "10^9/L",
                                               "report_reference": "3.5-9.5", "comparison": "high"}
    with pytest.raises(AdviceError): service.analyze(request)
    result = service.analyze(request, confirmed=True)
    assert "AI 选择先阅读" in result and "MedlinePlus" in result and "10.2" in result
    assert len(calls) == 1 and calls[0].data == request.body
    with pytest.raises(AdviceError): service.analyze(request, confirmed=True)
    service.clear()
    assert service.rows == ()
    service.set_enabled(False)
    assert not service.ai_enabled


@pytest.mark.parametrize("change", ["edit", "clear", "revoke", "regrant", "config", "expire", "new_request"])
def test_inflight_medical_request_cannot_survive_state_changes(setup, change):
    service = lab(setup)
    verified(service)
    service.set_ai_enabled(True)
    request = service.prepare("cloud")
    def mutate():
        if change == "edit": service.replace_rows((LabRow("WBC", "2", "10^9/L", "3-9", True),))
        elif change == "clear": service.clear()
        elif change in {"revoke", "regrant"}:
            service.set_ai_enabled(False)
            if change == "regrant": service.set_ai_enabled(True)
        elif change == "config": setup.cloud.model = "changed"
        elif change == "expire": setup.now[0] += timedelta(minutes=6)
        else: service.prepare("cloud")
    service.request_fn = transport({"focus_codes": ["WBC"], "question_ids": ["repeat"]}, [], mutate)
    with pytest.raises(AdviceError): service.analyze(request, confirmed=True)


@pytest.mark.parametrize("raw", [
    {"focus_codes": ["WBC"], "question_ids": ["repeat"], "diagnosis": "anything"},
    {"focus_codes": ["HGB"], "question_ids": ["repeat"]},
    {"focus_codes": ["WBC", "WBC"], "question_ids": ["repeat"]},
    {"focus_codes": ["WBC"], "question_ids": ["medicine"]},
    {"focus_codes": [], "question_ids": ["repeat"]},
    {"focus_codes": [True], "question_ids": ["repeat"]},
])
def test_ai_cannot_inject_clinical_prose_or_unprovided_indicators(setup, raw):
    service = lab(setup, raw)
    verified(service)
    service.set_ai_enabled(True)
    request = service.prepare("cloud")
    with pytest.raises(AdviceError): service.analyze(request, confirmed=True)
    assert "高于报告范围" in service.local_reading()


def test_unknown_missing_ranges_do_not_enter_ai(setup):
    service = lab(setup)
    verified(service)
    service.set_ai_enabled(True)
    service.replace_rows((LabRow("WBC", "6", "10^9/L", "", True),))
    assert "暂不能对照" in service.local_reading()
    with pytest.raises(AdviceError): service.prepare("cloud")


def test_text_import_only_selected_file_and_fixed_ocr_arguments(tmp_path):
    selected = tmp_path / "report.txt"
    selected.write_text("WBC 6 10^9/L 3-9", encoding="utf-8")
    assert read_selected_lab_source(selected).text == "WBC 6 10^9/L 3-9"
    bad = tmp_path / "report.exe"
    with pytest.raises(LabSourceError): read_selected_lab_source(bad)
    calls = []
    def runner(args, **kwargs):
        calls.append((args, kwargs))
        words = [{"text": "WBC", "x": 0, "y": 0, "height": 20, "width": 35},
                 {"text": "6.2", "x": 100, "y": 1, "height": 20, "width": 30}]
        return SimpleNamespace(returncode=0, stdout=json.dumps({"words": words}))
    assert windows_ocr(selected, runner=runner) == "WBC\t6.2"
    args, kwargs = calls[0]
    assert "-File" in args and str(selected) not in args and "-Command" not in args
    assert json.loads(kwargs["input"])["path"] == str(selected.resolve())
    assert kwargs["timeout"] == 35 and "lab_ocr.ps1" in args[-1]
    assert _ocr_rows([]) == ""
