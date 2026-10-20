from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import ssl
from urllib.error import HTTPError, URLError

import pytest

from deskcare.ai.cloud_task_assistant import CloudAIError, CloudTaskAssistant
from deskcare.config import ConfigStore
from deskcare.domain.break_policy import BreakPolicy, BreakPolicyConfig
from deskcare.domain.types import ActivityKind, ActivitySample, BreakAction, PolicyContext
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.services.reminder_service import ReminderCoordinator
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository


def services(tmp_path):
    repo = UsageRepository(tmp_path / "test.sqlite3")
    controller = MonitoringController(FakeActivityProvider(), initially_enabled=True)
    collector = ActivityCollector(controller, repo)
    tasks = TaskService(repo)
    coordinator = ReminderCoordinator(controller, collector, tasks, repo)
    return repo, controller, collector, tasks, coordinator


def seed_ready(collector, minutes=45):
    now = datetime.now().astimezone()
    collector._previous = ActivitySample(100, now, 0, "CODE", ActivityKind.ACTIVE, True, True)
    collector.reminder_elapsed_seconds = minutes * 60
    return now


def test_interval_persists_and_invalid_stored_value_falls_back(tmp_path):
    repo, ctl, collector, tasks, coordinator = services(tmp_path)
    coordinator.set_interval(25)
    assert repo.get_setting("reminder_interval_minutes") == "25"
    again = ReminderCoordinator(ctl, collector, tasks, repo)
    assert again.policy.config.break_candidate_minutes == 25
    for invalid in (-1, 0, 181, True, 20.5, "20"):
        with pytest.raises(ValueError):
            coordinator.set_interval(invalid)
    repo.set_setting("reminder_interval_minutes", "broken")
    assert ReminderCoordinator.saved_interval(repo) == 40


def test_short_input_gap_preserves_budget_without_counting_idle(tmp_path):
    repo, ctl, collector, _tasks, _coordinator = services(tmp_path)
    now = datetime.now().astimezone()
    states = [(0, 0), (30, 0), (60, 90), (90, 120), (120, 0), (150, 0), (180, 301)]
    samples = iter(ActivitySample(t, now + timedelta(seconds=t), idle, "CODE",
                                 ActivityKind.IDLE if idle >= 60 else ActivityKind.ACTIVE, False, True)
                   for t, idle in states)
    ctl._provider.read_sample = lambda: next(samples)
    for _ in states[:6]:
        collector.poll_once()
    assert collector.continuous_active_seconds == 30
    assert collector.reminder_elapsed_seconds == 60
    collector.poll_once()
    assert collector.reminder_elapsed_seconds == 0
    ctl.set_paused(True)
    assert collector.reminder_elapsed_seconds == 0


def test_reminder_deduplicates_until_response_and_fresh_interval_after_break(tmp_path):
    repo, ctl, collector, tasks, coordinator = services(tmp_path)
    now = seed_ready(collector)
    first = coordinator.evaluate(now=now, is_recent_switch=True)
    assert first.visible
    again = coordinator.evaluate(now=now + timedelta(minutes=11), is_recent_switch=True)
    assert again.event_id == first.event_id
    assert len(repo.recent_reminder_events()) == 1
    coordinator.respond("BREAK_NOW", now=now + timedelta(minutes=12))
    assert collector.reminder_elapsed_seconds == 0
    assert not coordinator.evaluate(now=now + timedelta(minutes=23), is_recent_switch=True).visible


def test_snooze_retries_without_waiting_full_interval_and_pause_hides(tmp_path):
    repo, ctl, collector, tasks, coordinator = services(tmp_path)
    now = seed_ready(collector)
    coordinator.evaluate(now=now, is_recent_switch=True)
    coordinator.respond("SNOOZE_10_MIN", now=now)
    assert not coordinator.evaluate(now=now + timedelta(minutes=9)).visible
    assert coordinator.evaluate(now=now + timedelta(minutes=10), is_recent_switch=True).visible
    ctl.set_paused(True)
    assert not coordinator.snapshot.visible
    assert "已暂停" in coordinator.status_text()


def test_focus_delay_is_bounded_but_quiet_mode_stays_hard_gate():
    now = datetime.now(timezone.utc)
    base = dict(monitored=True, mode="focus", continuous_active_minutes=1, idle_seconds=0,
                is_recent_switch=False, next_confirmed_deadline=None, now=now,
                reminder_elapsed_minutes=26)
    policy = BreakPolicy(BreakPolicyConfig(break_candidate_minutes=20, max_soft_delay_minutes=5))
    assert policy.decide(PolicyContext(**base)).action is BreakAction.SOFT_NOTIFY
    base["mode"] = "quiet"
    assert policy.decide(PolicyContext(**base)).action is BreakAction.DEFER


def test_settings_preview_background_delivery_feedback_and_clear(tmp_path):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    from deskcare.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    repo, ctl, collector, tasks, coordinator = services(tmp_path)
    window = MainWindow(ConfigStore(), ctl, collector, tasks, coordinator, repo)
    window.show()
    page = window.settings_page
    page.reminder_interval.setValue(20)
    assert coordinator.policy.config.break_candidate_minutes == 20
    page.test_reminder.click()
    app.processEvents()
    assert window.reminder_popup.isVisible()
    assert window.reminder_popup.preview
    window.reminder_popup.buttons["SKIP"].click()
    assert repo.latest_reminder_event() is None
    assert window.reminder_popup.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert window.reminder_popup.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    now = seed_ready(collector, 25)
    window.hide()
    coordinator.evaluate(now=now, is_recent_switch=True)
    app.processEvents()
    assert not window.isVisible() and window.reminder_popup.isVisible()
    assert not window.reminder_popup.preview
    window.reminder_popup.buttons["SNOOZE_10_MIN"].click()
    assert repo.latest_reminder_event().response == "SNOOZE_10_MIN"
    assert not window.reminder_popup.isVisible()
    coordinator.set_mode("meeting")
    assert "会议" in page.reminder_status.text()
    repo.clear_all_data()
    window._refresh_after_data_clear()
    assert page.reminder_interval.value() == 40
    assert coordinator.policy.config.break_candidate_minutes == 40
    window._allow_close = True
    window.close()
    app.processEvents()


class Credentials:
    def load(self):
        return "synthetic-test-key"


def cloud(tmp_path, sender):
    repo = UsageRepository(tmp_path / "cloud.sqlite3")
    repo.set_consent("cloud_task_ai", True)
    repo.set_setting("cloud_task_endpoint", "https://api.deepseek.com")
    repo.set_setting("cloud_task_model", "deepseek-flash")
    return repo, CloudTaskAssistant(repo, Credentials(), request_fn=sender)


@pytest.mark.parametrize("base", ["https://api.deepseek.com", "https://api.deepseek.com/", "https://api.deepseek.com/v1"])
def test_deepseek_base_url_preview_and_transport_match(tmp_path, base):
    sent = []
    def sender(request, timeout):
        sent.append((request, timeout))
        return BytesIO(json.dumps({"choices": [{"finish_reason": "stop", "message": {"content":
            '{"tasks":[{"title":"演示任务","due_at":null,"estimated_minutes":null}]}'}}]}).encode())
    repo, service = cloud(tmp_path, sender)
    assert service.endpoint == "https://api.deepseek.com/chat/completions"
    service.configure(base, "deepseek-flash")
    request = service.prepare("- 演示任务".encode(), "demo.md")
    assert request.endpoint.endswith("/chat/completions")
    body = json.loads(request.preview())
    assert body["thinking"] == {"type": "disabled"}
    assert body["max_tokens"] == 4096
    result = service.parse(request)
    assert sent[0][0].data == request.body
    assert sent[0][1] == 60
    assert result.drafts[0].title == "演示任务"
    assert repo.tasks_for_day() == []


@pytest.mark.parametrize("code,expected", [(400,"格式"), (401,"密钥"), (402,"余额"), (404,"路径"), (429,"频繁"), (503,"暂时")])
def test_cloud_http_errors_are_useful_without_echoing_private_body(tmp_path, code, expected):
    def sender(request, timeout):
        raise HTTPError(request.full_url, code, "secret provider text", {}, BytesIO(b"synthetic-test-key private task"))
    _, service = cloud(tmp_path, sender)
    with pytest.raises(CloudAIError) as error:
        service.parse(service.prepare(b"- private task", "tasks.md"))
    assert expected in str(error.value) and f"HTTP {code}" in str(error.value)
    assert "synthetic-test-key" not in str(error.value)
    assert "private task" not in str(error.value)


@pytest.mark.parametrize("exception,expected", [(TimeoutError(),"超时"), (URLError("private diagnostic"),"网络"), (URLError(ssl.SSLError("secret")),"加密")])
def test_cloud_network_errors_are_classified_and_safe(tmp_path, exception, expected):
    def sender(request, timeout):
        raise exception
    _, service = cloud(tmp_path, sender)
    with pytest.raises(CloudAIError, match=expected) as error:
        service.parse(service.prepare(b"- private task", "tasks.md"))
    assert "private" not in str(error.value) and "secret" not in str(error.value)
