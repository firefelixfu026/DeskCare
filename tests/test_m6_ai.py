import json
import importlib.util
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Event, Thread
from time import perf_counter
from urllib.error import URLError

import pytest

from deskcare.ai.optional_local_llm import LocalAIService, LocalLLMClient, LocalModelError
from deskcare.ai.report_narrator import LocalReportNarrator
from deskcare.storage.database import UsageRepository


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload, ensure_ascii=False).encode("utf-8")

    def close(self) -> None:
        pass


def test_local_llm_requires_loopback_endpoint():
    with pytest.raises(ValueError):
        LocalLLMClient(endpoint="https://example.com/api/chat")


def test_local_llm_validates_structured_candidates_and_explicit_date_only():
    model_json = {
        "tasks": [
            {
                "title": "提交演示材料",
                "due_at": "2026-10-14T18:00:00",
                "estimated_minutes": 30,
            },
            {
                "title": "整理明天的想法",
                "due_at": "2026-10-15T10:00:00",
                "estimated_minutes": 99999,
            },
        ]
    }
    client = LocalLLMClient(
        request_fn=lambda _request, timeout: _FakeResponse(
            {"message": {"content": json.dumps(model_json, ensure_ascii=False)}}
        )
    )

    result = client.parse(
        "2026-10-14T18:00 提交演示材料\n明天整理想法\n".encode("utf-8"),
        "selected.txt",
    )

    # UI15 keeps matched source names stable so a model paraphrase cannot
    # defeat import duplicate checking. The model's estimates remain suggestions.
    assert [draft.title for draft in result.drafts] == ["提交演示材料", "明天整理想法"]
    assert result.drafts[0].due_at is not None
    assert result.drafts[1].due_at is None
    assert "model_due_needs_confirmation" in result.drafts[1].uncertainty
    assert "model_estimate_needs_confirmation" in result.drafts[1].uncertainty


def test_local_llm_lists_only_valid_unique_ollama_models():
    requests = []

    def request_fn(request, timeout):
        requests.append((request.full_url, request.get_method(), timeout))
        return _FakeResponse(
            {
                "models": [
                    {"name": "llama3.2:3b"},
                    {"model": "qwen2.5:7b"},
                    {"name": "llama3.2:3b"},
                    {"name": ""},
                    "invalid",
                ]
            }
        )

    client = LocalLLMClient(
        endpoint="http://localhost:11434/api/chat",
        request_fn=request_fn,
    )

    assert client.list_models() == ("llama3.2:3b", "qwen2.5:7b")
    assert requests == [("http://localhost:11434/api/tags", "GET", 4.0)]


def test_local_llm_uses_real_loopback_http_transport():
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802 - stdlib handler API
            requests.append(
                (self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            )
            body = json.dumps(
                {"message": {"content": json.dumps({"tasks": [{"title": "本地 HTTP 测试"}]})}},
                ensure_ascii=False,
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, _format, *_args):
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = LocalLLMClient(endpoint=f"http://127.0.0.1:{server.server_port}/api/chat")
        try:
            result = client.parse("- 本地 HTTP 测试\n".encode("utf-8"), "selected.txt")
        except Exception as exc:
            cause = exc.__cause__
            if isinstance(cause, URLError) and isinstance(cause.reason, PermissionError):
                pytest.skip("当前受限运行环境禁止本地 socket；用户 Windows 环境应执行此测试。")
            raise
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()

    assert [draft.title for draft in result.drafts] == ["本地 HTTP 测试"]
    assert requests and requests[0][0] == "/api/chat"
    assert requests[0][1]["stream"] is False
    assert requests[0][1]["format"] == "json"


def test_local_ai_falls_back_to_rules_without_persisting_source_text(tmp_path):
    class FailingClient:
        def parse(self, _content, _filename):
            raise RuntimeError("model offline")

    path = tmp_path / "today.txt"
    path.write_text("- 复习本周材料\n", encoding="utf-8")
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    service = LocalAIService(repository, initially_enabled=True, client=FailingClient())

    result = service.parse_path(path)

    assert [draft.title for draft in result.drafts] == ["复习本周材料"]
    assert result.issues[-1].code == "local_ai_fallback"
    assert result.issues[-1].fatal is False
    assert "复习本周材料" not in result.issues[-1].message
    assert repository.get_consent("local_ai") is None


def test_local_ai_disabled_never_calls_client(tmp_path):
    class ExplodingClient:
        def parse(self, _content, _filename):
            raise AssertionError("disabled local AI must not be called")

    path = tmp_path / "today.txt"
    path.write_text("- 只走规则解析\n", encoding="utf-8")
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    service = LocalAIService(repository, initially_enabled=False, client=ExplodingClient())

    result = service.parse_path(path)

    assert [draft.title for draft in result.drafts] == ["只走规则解析"]
    assert result.issues == ()


@pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is required for the task AI background-thread test",
)
def test_task_ai_preview_is_non_blocking_and_discards_late_result():
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    from deskcare.domain.types import TaskDraft
    from deskcare.importers.base import ImportResult
    from deskcare.ui.task_dialog import ImportPreviewDialog

    app = QApplication.instance() or QApplication([])
    rule_result = ImportResult(
        "selected.txt",
        (TaskDraft("规则草稿", None, None, 1, ()),),
        (),
    )
    model_result = ImportResult(
        "selected.txt",
        (TaskDraft("模型候选", None, 30, 1, ("model_suggestion",)),),
        (),
    )
    started = Event()
    release = Event()

    def slow_parser():
        started.set()
        release.wait(timeout=2)
        return model_result

    dialog = ImportPreviewDialog(rule_result, ai_parser=slow_parser)
    before = perf_counter()
    dialog.ai_button.click()
    elapsed = perf_counter() - before
    for _ in range(100):
        app.processEvents()
        if started.is_set():
            break
        QThread.msleep(5)

    assert elapsed < 0.25
    assert started.is_set()
    assert dialog.ai_button.isEnabled() is False
    assert dialog.table.item(0, 0).text() == "规则草稿"
    assert "窗口仍可操作" in dialog.issue_label.text()

    dialog.reject()
    release.set()
    for _ in range(200):
        app.processEvents()
        if dialog._ai_thread is None:
            break
        QThread.msleep(5)
    assert dialog._ai_thread is None
    assert dialog.table.item(0, 0).text() == "规则草稿"

    successful = ImportPreviewDialog(rule_result, ai_parser=lambda: model_result)
    successful.ai_button.click()
    for _ in range(200):
        app.processEvents()
        if successful._ai_thread is None:
            break
        QThread.msleep(5)
    assert successful._ai_thread is None
    assert successful.table.item(0, 0).text() == "模型候选"


@pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is required for the background-thread shutdown test",
)
def test_window_shutdown_waits_for_active_local_ai_worker(tmp_path):
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    from deskcare.config import ConfigStore
    from deskcare.domain.types import TaskDraft
    from deskcare.importers.base import ImportResult
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.consent_service import MonitoringController
    from deskcare.ui.main_window import MainWindow
    from deskcare.ui.task_dialog import ImportPreviewDialog

    app = QApplication.instance() or QApplication([])
    controller = MonitoringController(FakeActivityProvider())
    window = MainWindow(ConfigStore(), controller)
    result = ImportResult(
        "selected.txt",
        (TaskDraft("规则草稿", None, None, 1, ()),),
        (),
    )
    started = Event()

    def bounded_parser():
        started.set()
        QThread.msleep(75)
        return result

    dialog = ImportPreviewDialog(result, window, ai_parser=bounded_parser)
    dialog.ai_button.click()
    for _ in range(100):
        app.processEvents()
        if started.is_set():
            break
        QThread.msleep(5)
    running_thread = dialog._ai_thread
    assert running_thread is not None and running_thread.isRunning()

    window.shutdown_background_work()

    assert running_thread.isRunning() is False


def test_local_ai_model_probe_requires_independent_consent(tmp_path):
    class ProbeClient:
        endpoint = "http://127.0.0.1:11434/api/chat"
        model = "llama3.2:3b"

        def list_models(self):
            return ("llama3.2:3b",)

    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    service = LocalAIService(repository, initially_enabled=False, client=ProbeClient())

    with pytest.raises(LocalModelError, match="开启本地 AI"):
        service.probe_models()
    service.set_enabled(True)
    assert service.probe_models() == ("llama3.2:3b",)


def test_local_ai_configuration_is_persisted_and_loopback_only(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    service = LocalAIService(repository)

    service.configure("http://localhost:11434/api/chat", "qwen2.5:7b")

    assert service.endpoint == "http://localhost:11434/api/chat"
    assert service.model == "qwen2.5:7b"
    assert repository.get_setting("local_ai_endpoint") == "http://localhost:11434/api/chat"
    assert repository.get_setting("local_ai_model") == "qwen2.5:7b"
    with pytest.raises(ValueError):
        service.configure("https://example.com/api/chat", "qwen2.5:7b")
    assert repository.get_setting("local_ai_endpoint") == "http://localhost:11434/api/chat"

    reopened = UsageRepository(tmp_path / "deskcare.sqlite3")
    restored = LocalAIService(reopened)
    assert restored.endpoint == "http://localhost:11434/api/chat"
    assert restored.model == "qwen2.5:7b"
    restored.reset_configuration()
    assert reopened.get_setting("local_ai_endpoint") is None
    assert reopened.get_setting("local_ai_model") is None


def _facts():
    return {
        "period": {"type": "daily", "start": "2026-10-14", "end": "2026-10-14"},
        "data_quality": {
            "covered_minutes_estimate": 66.0,
            "days_with_activity": 1,
            "period_days": 1,
        },
        "usage": {"active_minutes_estimate": 60.0},
        "tasks": {"confirmed_total": 2, "completed_by_user": 1, "open": 1},
        "reminders": {
            "shown": 3,
            "break_intent_confirmed": 1,
            "snoozed": 1,
            "skipped": 1,
            "bad_timing": 0,
        },
        "wellness": None,
    }


def test_local_report_narrator_substitutes_host_owned_facts():
    payload = {
        "message": {
            "content": json.dumps(
                {
                    "summary_template": "本期记录覆盖 {covered_minutes_estimate} 分钟，确认任务 {confirmed_total} 项。",
                    "suggestions": ["如果你愿意，可以回看 {bad_timing} 次时机反馈。"],
                },
                ensure_ascii=False,
            )
        }
    }
    client = LocalLLMClient(request_fn=lambda _request, timeout: _FakeResponse(payload))

    report = LocalReportNarrator(client).narrate(_facts())

    assert "覆盖 66.0 分钟" in report
    assert "确认任务 2 项" in report
    assert "{covered_minutes_estimate}" not in report
    assert "医学判断" in report


def test_local_report_narrator_rejects_unchecked_numbers_and_forbidden_claims():
    def response_for(model_text):
        return _FakeResponse({"message": {"content": json.dumps(model_text, ensure_ascii=False)}})

    numeric_client = LocalLLMClient(
        request_fn=lambda _request, timeout: response_for(
            {"summary_template": "本期有 99 分钟记录。", "suggestions": []}
        )
    )
    with pytest.raises(LocalModelError):
        LocalReportNarrator(numeric_client).narrate(_facts())

    forbidden_client = LocalLLMClient(
        request_fn=lambda _request, timeout: response_for(
            {"summary_template": "这说明你的效率提升了。", "suggestions": []}
        )
    )
    with pytest.raises(LocalModelError):
        LocalReportNarrator(forbidden_client).narrate(_facts())


def test_local_ai_report_falls_back_to_template_on_invalid_model_output(tmp_path):
    class InvalidClient:
        def request_json(self, _system_prompt, _user_text):
            return {"summary_template": "未经校验的 12 分钟", "suggestions": []}

        @staticmethod
        def json_text(value):
            return json.dumps(value, ensure_ascii=False)

    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    service = LocalAIService(repository, initially_enabled=True, client=InvalidClient())

    markdown, used_model = service.narrate_facts(_facts(), "模板报告")

    assert markdown == "模板报告"
    assert used_model is False


def test_local_ai_report_does_not_send_wellness_or_app_names_to_model(tmp_path):
    seen = {}

    class CapturingClient:
        def request_json(self, _system_prompt, user_text):
            seen["facts"] = json.loads(user_text)
            return {
                "summary_template": "本期覆盖 {covered_minutes_estimate} 分钟。",
                "suggestions": [],
            }

        @staticmethod
        def json_text(value):
            return json.dumps(value, ensure_ascii=False)

    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    service = LocalAIService(repository, initially_enabled=True, client=CapturingClient())
    facts = _facts()
    facts["wellness"] = {"recorded_days": 1, "entries": [{"comfort_level": "uncomfortable"}]}
    facts["applications"] = {"top_apps": [{"name": "私人应用名", "minutes": 60}]}

    markdown, used_model = service.narrate_facts(facts, "模板报告")

    assert used_model is True
    assert seen["facts"]["wellness"] is None
    assert seen["facts"]["applications"] is None
    assert "私人应用名" not in json.dumps(seen["facts"], ensure_ascii=False)
    assert "AI 辅助摘要" in markdown


@pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is required for the M6 UI consent smoke test",
)
def test_local_ai_consent_updates_report_button(tmp_path):
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QApplication

    from deskcare.config import ConfigStore
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.activity_service import ActivityCollector
    from deskcare.services.bodylog_service import BodyLogService
    from deskcare.services.consent_service import MonitoringController
    from deskcare.services.reminder_service import ReminderCoordinator
    from deskcare.services.report_engine import LocalReportService
    from deskcare.services.task_service import TaskService
    from deskcare.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    controller = MonitoringController(FakeActivityProvider())
    collector = ActivityCollector(controller, repository)
    task_service = TaskService(repository)
    reminder = ReminderCoordinator(controller, collector, task_service, repository)
    bodylog = BodyLogService(repository)
    class UIClient:
        endpoint = "http://127.0.0.1:11434/api/chat"
        model = "llama3.2:3b"

        def list_models(self):
            return ("llama3.2:3b", "qwen2.5:7b")

        def request_json(self, _system_prompt, _user_text):
            raise RuntimeError("model response is not part of this UI probe")

        @staticmethod
        def json_text(value):
            return json.dumps(value, ensure_ascii=False)

    local_ai = LocalAIService(repository, initially_enabled=False, client=UIClient())
    window = MainWindow(
        ConfigStore(),
        controller,
        collector,
        task_service,
        reminder,
        repository,
        bodylog,
        LocalReportService(repository),
        local_ai,
    )
    report = window.pages.widget(2)
    settings = window.pages.widget(3)
    assert report.ai_report_button.isEnabled() is False
    assert settings.local_ai_config.isHidden()
    settings.local_ai_advanced_button.setChecked(True)
    assert not settings.local_ai_config.isHidden()

    settings.local_ai.setChecked(True)
    app.processEvents()
    assert local_ai.enabled is True
    assert report.ai_report_button.isEnabled() is True
    assert repository.get_consent("local_ai") is True
    settings.local_ai_advanced_button.setChecked(True)

    settings.probe_local_ai.click()
    for _ in range(100):
        app.processEvents()
        if settings._local_ai_probe_thread is None:
            break
        QThread.msleep(5)
    assert settings._local_ai_probe_thread is None
    assert "配置模型 llama3.2:3b 可用" in settings.local_ai_config_feedback.text()

    report.ai_report_button.click()
    for _ in range(100):
        app.processEvents()
        if report._report_ai_thread is None:
            break
        QThread.msleep(5)
    assert report._report_ai_thread is None
    assert "本机 AI 暂时不可用" in report.report_sources.text()

    settings.local_ai.setChecked(False)
    app.processEvents()
    assert local_ai.enabled is False
    assert report.ai_report_button.isEnabled() is False
    assert repository.get_consent("local_ai") is False

    settings.local_ai_endpoint.setText("http://localhost:11434/api/chat")
    settings.local_ai_model.setText("qwen2.5:7b")
    settings.save_local_ai_config.click()
    app.processEvents()
    assert local_ai.endpoint == "http://localhost:11434/api/chat"
    assert local_ai.model == "qwen2.5:7b"
    assert repository.get_setting("local_ai_model") == "qwen2.5:7b"
    window._allow_close = True
    window.close()
