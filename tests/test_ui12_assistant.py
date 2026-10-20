import json
from dataclasses import replace
from datetime import timedelta

import pytest

from test_ui11_reminder_advice import setup, output, transport
from deskcare.services.assistant_service import AssistantService
from deskcare.services.reminder_advice import AdviceError


def assistant(s, raw, calls=None, during=None):
    return AssistantService(s.repo, s.coord, s.tasks, cloud_ai=s.cloud, now=lambda: s.now[0],
                            request_fn=transport(raw, calls if calls is not None else [], during))


def plan(service, message, raw):
    service.request_fn = transport(raw, [])
    request = service.prepare(message, "cloud")
    return service.analyze(request, confirmed=True)


def test_tiny_interval_does_not_trap_ai_in_five_minute_choices(setup):
    s = setup
    s.coord.set_interval(1)
    task = s.tasks.add_manual("两小时项目", estimated_minutes=120)
    context = s.service.capture(task.id)
    assert context.data["interval_choices"] == [20, 25, 30, 40, 45, 50, 60]
    assert s.service.fallback(context).interval_minutes == 40
    with pytest.raises(AdviceError):
        s.service.validate(output(interval=5, evidence=["task"]), context, source="AI")
    with pytest.raises(AdviceError):
        s.service.validate(output(interval=40, evidence=["feedback"]), context, source="AI")
    result = s.service.validate(output(interval=50, evidence=["task", "mode"]), context, source="rule")
    s.service.apply(result, context, confirmed=True)
    assert s.coord.policy.config.break_candidate_minutes == 50


def test_feedback_banner_also_escapes_tiny_test_interval(setup):
    from test_ui11_reminder_advice import add_feedback
    setup.coord.set_interval(1)
    add_feedback(setup)
    assert setup.personal.snapshot.suggested_minutes == 40


def test_human_preview_is_complete_personal_data_but_not_json(setup):
    from deskcare.ai.reminder_advisor import ReminderAIAdvisor
    s = setup
    task = s.tasks.add_manual("计划标题", estimated_minutes=120, notes="不应上传的备注")
    advisor = ReminderAIAdvisor(s.service, cloud_ai=s.cloud)
    request = advisor.prepare(s.service.capture(task.id, "comfortable"), "cloud")
    text = request.human_preview()
    assert "计划标题" in text and "120" in text and "无明显不适" in text
    assert "response_format" not in text and "thinking" not in text and "不应上传的备注" not in text
    assert json.loads(request.body)["messages"]  # Machine format remains internal.


def test_assistant_consent_preview_and_single_use_confirmed_write(setup):
    s = setup
    calls = []
    service = assistant(s, {"tool": "set_interval", "arguments": {"minutes": 45}}, calls)
    s.repo.set_consent("reminder_context_ai", True)
    request = service.prepare("把提醒间隔改成45分钟", "cloud")
    assert not calls
    with pytest.raises(AdviceError): service.analyze(request, confirmed=True)
    service.set_enabled(True)
    request = service.prepare("把提醒间隔改成45分钟", "cloud")
    with pytest.raises(AdviceError): service.analyze(request)
    proposal = service.analyze(request, confirmed=True)
    assert len(calls) == 1 and calls[0].data == request.body
    assert s.coord.policy.config.break_candidate_minutes == 40
    with pytest.raises(AdviceError): service.execute(proposal)
    outcome = service.execute(proposal, confirmed=True)
    assert s.coord.policy.config.break_candidate_minutes == 45 and "已保存" in outcome.text
    with pytest.raises(AdviceError): service.execute(proposal, confirmed=True)


@pytest.mark.parametrize("text,minutes", [("把提醒改成四十分钟", 40), ("每隔30分钟提醒", 30),
                                         ("把间隔设为5分钟", 5)])
def test_explicit_user_interval_and_not_ai_preference(setup, text, minutes):
    service = assistant(setup, {})
    service.set_enabled(True)
    proposal = plan(service, text, {"tool": "set_interval", "arguments": {"minutes": minutes}})
    service.execute(proposal, confirmed=True)
    assert setup.coord.policy.config.break_candidate_minutes == minutes


@pytest.mark.parametrize("raw,text", [
    ({"tool": "shell", "arguments": {"cmd": "anything"}}, "执行命令"),
    ({"tool": "delete_task", "arguments": {"id": 1}}, "删除任务"),
    ({"tool": "set_interval", "arguments": {"minutes": 5}}, "我有一个两小时任务，怎么安排？"),
    ({"tool": "set_interval", "arguments": {"minutes": 120}}, "这个任务120分钟，提醒间隔合理吗？"),
    ({"tool": "set_interval", "arguments": {"minutes": 180}}, "把提醒改成40分钟"),
    ({"tool": "set_interval", "arguments": {"minutes": True}}, "把提醒改成1分钟"),
    ({"tool": "set_mode", "arguments": {"mode": "quiet"}}, "查看今天的任务"),
    ({"tool": "set_mode", "arguments": {"mode": {}}}, "安静"),
    ({"tool": "show_today", "arguments": {"path": "private"}}, "查看任务"),
    ({"tool": "add_task", "arguments": {"title": "invented", "estimated_minutes": 30, "day_offset": 0}}, "你能做什么"),
    ({"tool": "add_task", "arguments": {"title": "x", "estimated_minutes": 30, "day_offset": -1}}, "添加任务"),
    ({"tool": "show_today", "arguments": {}, "reply": "made up facts"}, "查看任务"),
])
def test_bad_tools_arguments_or_unsupported_authority_are_rejected(setup, raw, text):
    service = assistant(setup, raw)
    service.set_enabled(True)
    with pytest.raises(AdviceError): plan(service, text, raw)
    assert not setup.tasks.list_all() and setup.coord.policy.config.break_candidate_minutes == 40


def test_read_results_stay_local_and_no_duplicate_task_on_retry(setup):
    s = setup
    service = assistant(s, {})
    service.set_enabled(True)
    proposal = plan(service, "添加明天整理材料的任务，预计30分钟", {"tool": "add_task", "arguments": {
        "title": "整理材料", "estimated_minutes": 30, "day_offset": 1}})
    with pytest.raises(AdviceError): service.execute(proposal)
    service.execute(proposal, confirmed=True)
    with pytest.raises(AdviceError): service.execute(proposal, confirmed=True)
    assert len(s.tasks.list_all()) == 1
    task = s.tasks.list_all()[0]
    assert task.planned_for == s.now[0].date()+timedelta(days=1)
    secret = s.tasks.add_manual("private user task", notes="private note")
    proposal = plan(service, "今天的任务是什么", {"tool": "show_today", "arguments": {}})
    result = service.execute(proposal)
    assert secret.title in result.text
    next_request = service.prepare("当前提醒设置是什么", "cloud")
    assert secret.title.encode() not in next_request.body
    assert b"private note" not in next_request.body


@pytest.mark.parametrize("change", ["revoke", "regrant", "mode", "interval", "expired", "cancel", "config"])
def test_late_assistant_response_is_discarded(setup, change):
    s = setup
    service = assistant(s, {})
    service.set_enabled(True)
    def during():
        if change in {"revoke", "regrant"}: service.set_enabled(False)
        if change == "regrant": service.set_enabled(True)
        if change == "mode": s.coord.set_mode("quiet")
        if change == "interval": s.coord.set_interval(15)
        if change == "expired": s.now[0] += timedelta(minutes=6)
        if change == "cancel": service.invalidate()
        if change == "config": s.cloud.model = "changed"
    service.request_fn = transport({"tool": "set_interval", "arguments": {"minutes": 45}}, [], during)
    request = service.prepare("把提醒改成45分钟", "cloud")
    with pytest.raises(AdviceError): service.analyze(request, confirmed=True)
    assert s.coord.policy.config.break_candidate_minutes == (15 if change == "interval" else 40)


def test_proposal_stale_canceled_or_tampered_cannot_execute(setup):
    s = setup
    service = assistant(s, {})
    service.set_enabled(True)
    proposal = plan(service, "我准备专注一会儿", {"tool": "set_mode", "arguments": {"mode": "focus"}})
    with pytest.raises(AdviceError): service.execute(replace(proposal, arguments_json='{"mode":"quiet"}'), confirmed=True)
    s.coord.set_interval(30)
    with pytest.raises(AdviceError): service.execute(proposal, confirmed=True)
    assert s.coord.mode == "normal"
    proposal = plan(service, "我准备专注一会儿", {"tool": "set_mode", "arguments": {"mode": "focus"}})
    s.cloud.model = "changed-after-analysis"
    with pytest.raises(AdviceError): service.execute(proposal, confirmed=True)
    assert s.coord.mode == "normal"


def test_assistant_pure_tools_do_not_require_monitoring_and_cannot_read_health(setup, monkeypatch):
    s = setup
    s.controller.set_enabled(False)
    service = assistant(s, {})
    service.set_enabled(True)
    monkeypatch.setattr(s.repo, "wellness_for_day", lambda *a, **k: pytest.fail("must not read health"))
    for name in ("show_reminder", "show_today", "show_usage", "analyze_reminder", "unsupported", "help", "clarify"):
        proposal = plan(service, "测试：查看支持能力", {"tool": name, "arguments": {}})
        assert service.execute(proposal).text
