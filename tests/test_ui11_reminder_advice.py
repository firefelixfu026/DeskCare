import io
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from deskcare.ai.reminder_advisor import ReminderAIAdvisor
from deskcare.domain.types import ActivityKind, ActivitySample, BreakAction, PolicyDecision, TaskStatus
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.services.personalization_service import ReminderPersonalizationService
from deskcare.services.reminder_service import ReminderCoordinator
from deskcare.services.reminder_advice import AdviceError, ReminderAdviceService
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository


@pytest.fixture
def setup(tmp_path):
    repo = UsageRepository(tmp_path / "advice.sqlite3")
    controller = MonitoringController(FakeActivityProvider(), initially_enabled=True)
    collector = ActivityCollector(controller, repo)
    tasks = TaskService(repo)
    personal = ReminderPersonalizationService(repo, initially_enabled=True)
    coord = ReminderCoordinator(controller, collector, tasks, repo, personalization_service=personal)
    now = [datetime(2026, 10, 20, 10, tzinfo=timezone.utc)]
    collector._previous = ActivitySample(100, now[0], 0, "CODE", ActivityKind.ACTIVE, True, True, "secret-app")
    collector.continuous_active_seconds = 42 * 60
    service = ReminderAdviceService(repo, coord, tasks, now=lambda: now[0])
    cloud = SimpleNamespace(endpoint="https://api.deepseek.com/chat/completions", model="deepseek-flash",
                            credentials=SimpleNamespace(load=lambda: "fake-key-never-print"))
    return SimpleNamespace(repo=repo, controller=controller, collector=collector, tasks=tasks,
                           personal=personal, coord=coord, now=now, service=service, cloud=cloud)


def add_feedback(s, count=10, bad=8, mode="normal"):
    for i in range(count):
        event = s.repo.add_reminder_event(
            occurred_at=s.now[0] - timedelta(minutes=count-i),
            decision=PolicyDecision(BreakAction.SOFT_NOTIFY, ("TEST",), "synthetic", 60),
            mode=mode, active_minutes=40)
        s.repo.update_reminder_response(event.id, "BAD_TIMING" if i < bad else "BREAK_NOW", s.now[0])
    s.personal.refresh(mode)


def output(action="review_interval", evidence=None, interval=60):
    return {"action": action, "evidence": evidence or ["mode", "activity"], "interval_minutes": interval}


def transport(raw, calls, during=None, local=False):
    def call(request, **kwargs):
        calls.append(request)
        if during:
            during()
        message = {"content": json.dumps(raw)}
        envelope = {"message": message} if local else {"choices": [{"message": message}]}
        return io.BytesIO(json.dumps(envelope).encode())
    return call


def test_context_does_not_scan_screen_or_health_and_task_is_user_selected(setup, monkeypatch):
    s = setup
    task = s.tasks.add_manual("a confirmed task", notes="private notes", estimated_minutes=30)
    s.tasks.add_manual("another private task")
    for method in ("wellness_for_day", "health_events"):
        if hasattr(s.repo, method):
            monkeypatch.setattr(s.repo, method, lambda *a, **k: pytest.fail("health repository read"))
    default = s.service.capture()
    assert default.data["selected_task"] is None
    assert default.data["self_report_this_request"] is None
    selected = s.service.capture(task.id, "some_discomfort")
    assert selected.data["selected_task"]["title"] == task.title
    assert "private notes" not in selected.data_json
    assert "another private task" not in selected.data_json
    assert "secret-app" not in selected.data_json
    assert s.service.fallback(selected).action == "break_at_gap"


def test_local_feedback_recommends_instead_of_silently_adjusting_and_snoozes_review(setup):
    s = setup
    add_feedback(s)
    assert s.personal.snapshot.suggested_minutes == 60
    assert not s.personal.snapshot.applied
    assert s.personal.effective_config(s.coord.policy.config, "normal").break_candidate_minutes == 40
    s.personal.dismiss_current_suggestion()
    assert s.personal.snapshot.suggested_minutes is None
    add_feedback(s, count=4, bad=4)
    assert s.personal.snapshot.suggested_minutes is None
    add_feedback(s, count=1, bad=1)
    assert s.personal.snapshot.suggested_minutes == 60


def test_context_threshold_and_upper_bound(setup):
    s = setup
    add_feedback(s)
    s.coord.set_mode("focus")
    assert s.personal.snapshot.suggested_minutes is None
    s.coord.set_mode("normal")
    s.coord.set_interval(180)
    assert s.personal.snapshot.suggested_minutes is None
    assert max(s.service.capture().data["interval_choices"]) == 180
    s.personal.set_enabled(False)
    assert s.service.capture().data["feedback"]["total"] == 0


@pytest.mark.parametrize("change", ["pause", "off", "mode", "interval", "time", "unknown"])
def test_stale_context_cannot_apply_or_send(setup, change):
    s = setup
    context = s.service.capture()
    advice = s.service.validate(output(), context, source="rule")
    if change == "pause": s.controller.set_paused(True)
    if change == "off": s.controller.set_enabled(False)
    if change == "mode": s.coord.set_mode("quiet")
    if change == "interval": s.coord.set_interval(35)
    if change == "time": s.now[0] += timedelta(minutes=6)
    if change == "unknown": s.collector._previous = None
    with pytest.raises(AdviceError):
        s.service.apply(advice, context, confirmed=True)


def test_task_completion_edits_deletion_and_unconfirmed_write(setup):
    s = setup
    task = s.tasks.add_manual("selected", due_at=s.now[0] + timedelta(minutes=5))
    context = s.service.capture(task.id)
    assert "deadline" in s.service.available_evidence(context)
    assert s.service.fallback(context).action == "finish_step"
    advice = s.service.validate(output(), context, source="rule")
    with pytest.raises(AdviceError): s.service.apply(advice, context)
    s.tasks.set_status(task.id, TaskStatus.DONE)
    assert not s.service.is_current(context)
    with pytest.raises(AdviceError): s.service.capture(task.id)


def test_apply_requires_confirmation_persists_and_does_not_change_tasks(setup):
    s = setup
    task = s.tasks.add_manual("unchanged", due_at=s.now[0]+timedelta(hours=1))
    context = s.service.capture(task.id)
    advice = s.service.validate(output(), context, source="rule")
    s.service.apply(advice, context, confirmed=True)
    assert s.coord.policy.config.break_candidate_minutes == 60
    assert s.repo.get_setting("reminder_interval_minutes") == "60"
    assert s.tasks.list_all()[0] == task


@pytest.mark.parametrize("raw", [
    output(interval=999), output(interval=True), output(interval=41), output(interval=40),
    output(evidence=["comfort"]), output(evidence=["task"]), output(evidence=["deadline"]),
    output(evidence=["mode", "mode"]), output(evidence=[{}]),
    output(action="diagnose"), output(action="finish_step", interval=None),
    output(action="keep", interval=60), {**output(), "diagnosis": "bad"},
])
def test_model_cannot_invent_facts_diagnose_or_set_unbounded_interval(setup, raw):
    with pytest.raises(AdviceError):
        setup.service.validate(raw, setup.service.capture(), source="AI")


def test_discomfort_and_quiet_gates_cannot_be_overridden(setup):
    s = setup
    task = s.tasks.add_manual("selected")
    with pytest.raises(AdviceError):
        s.service.validate(output("finish_step", ["task"], None),
                           s.service.capture(task.id, "some_discomfort"), source="AI")
    s.coord.set_mode("meeting")
    with pytest.raises(AdviceError):
        s.service.validate(output("break_at_gap", ["mode"], None), s.service.capture(), source="AI")
    assert s.service.fallback(s.service.capture()).action == "do_not_interrupt"


def test_prepare_has_no_network_key_read_and_old_task_consent_does_not_authorize(setup):
    s = setup
    calls = []
    s.repo.set_consent("cloud_task_ai", True)
    advisor = ReminderAIAdvisor(s.service, cloud_ai=s.cloud, request_fn=transport(output(), calls))
    request = advisor.prepare(s.service.capture(), "cloud")
    assert "fake-key-never-print" not in request.preview()
    assert request.body == advisor._body("cloud", request.endpoint, request.model, request.context)
    assert json.loads(request.body)["thinking"] == {"type": "disabled"}
    with pytest.raises(AdviceError): advisor.analyze(request, confirmed=True)
    s.service.set_enabled(True)
    request = advisor.prepare(s.service.capture(), "cloud")
    with pytest.raises(AdviceError): advisor.analyze(request)
    assert not calls
    result = advisor.analyze(request, confirmed=True)
    assert result.interval_minutes == 60 and "联网 AI" in result.source
    assert calls[0].data == request.body
    assert s.coord.policy.config.break_candidate_minutes == 40


@pytest.mark.parametrize("during", ["revoke", "regrant", "pause", "taskedit", "clear"])
def test_changes_during_request_discard_the_response(setup, during):
    s = setup
    task = s.tasks.add_manual("selected")
    s.service.set_enabled(True)
    def change():
        if during in {"revoke", "regrant"}: s.service.set_enabled(False)
        if during == "regrant": s.service.set_enabled(True)
        if during == "pause": s.controller.set_paused(True)
        if during == "taskedit": s.tasks.update(task.id, title="edited")
        if during == "clear": s.repo.clear_all_data()
    advisor = ReminderAIAdvisor(s.service, cloud_ai=s.cloud, request_fn=transport(output(), [], change))
    request = advisor.prepare(s.service.capture(task.id), "cloud")
    with pytest.raises(AdviceError): advisor.analyze(request, confirmed=True)
    assert s.coord.policy.config.break_candidate_minutes == 40


def test_config_or_preview_tampering_is_not_sent(setup):
    s = setup
    s.service.set_enabled(True)
    calls = []
    advisor = ReminderAIAdvisor(s.service, cloud_ai=s.cloud, request_fn=transport(output(), calls))
    request = advisor.prepare(s.service.capture(), "cloud")
    with pytest.raises(AdviceError): advisor.analyze(replace(request, body=b"{}"), confirmed=True)
    s.cloud.model = "changed"
    with pytest.raises(AdviceError): advisor.analyze(request, confirmed=True)
    assert not calls


def test_local_exact_preview_and_safe_failure(setup):
    s = setup
    s.service.set_enabled(True)
    local = SimpleNamespace(endpoint="http://127.0.0.1:11434/api/chat", model="fake-local", enabled=True)
    calls = []
    advisor = ReminderAIAdvisor(s.service, local, request_fn=transport(output(), calls, local=True))
    request = advisor.prepare(s.service.capture(), "local")
    assert advisor.analyze(request, confirmed=True).interval_minutes == 60
    assert calls[0].data == request.body
    assert not calls[0].has_header("Authorization")
    def fail(*a, **kw): raise RuntimeError("secret provider body")
    advisor.request_fn = fail
    with pytest.raises(AdviceError) as error: advisor.analyze(request, confirmed=True)
    assert "secret provider body" not in str(error.value)
    assert s.coord.policy.config.break_candidate_minutes == 40


def test_handled_feedback_does_not_keep_suggesting_longer_interval(setup):
    s = setup
    add_feedback(s)
    context = s.service.capture()
    advice = s.service.fallback(context)
    s.service.apply(advice, context, confirmed=True)
    context = s.service.capture()
    assert s.service.fallback(context).interval_minutes is None
    with pytest.raises(AdviceError):
        s.service.validate(output(evidence=["feedback"], interval=65), context, source="AI")


@pytest.mark.parametrize("kind", ["oversize", "truncated", "invalid", "config_changed"])
def test_bounded_response_failure_and_late_configuration_change(setup, kind):
    s = setup
    s.service.set_enabled(True)
    def call(*args, **kwargs):
        if kind == "oversize": return io.BytesIO(b"x" * 65537)
        if kind == "invalid": return io.BytesIO(b"not JSON, secret")
        if kind == "config_changed": s.cloud.model = "changed"
        return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(output())},
            "finish_reason": "length" if kind == "truncated" else "stop"}]}).encode())
    advisor = ReminderAIAdvisor(s.service, cloud_ai=s.cloud, request_fn=call)
    request = advisor.prepare(s.service.capture(), "cloud")
    with pytest.raises(AdviceError): advisor.analyze(request, confirmed=True)
    assert s.coord.policy.config.break_candidate_minutes == 40
