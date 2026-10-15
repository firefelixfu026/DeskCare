import json

import pytest

from deskcare.ai.cloud_task_assistant import CloudAIError, CloudTaskAssistant
from deskcare.storage.database import UsageRepository


class MemoryCredentials:
    def __init__(self):
        self.value = None

    def save(self, secret):
        self.value = secret

    def load(self):
        return self.value

    def delete(self):
        self.value = None


class Response:
    def __init__(self, value):
        self.value = value

    def read(self):
        return json.dumps(self.value, ensure_ascii=False).encode()

    def close(self):
        pass


def make_service(tmp_path, request_fn=lambda *_args, **_kwargs: Response({})):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    credentials = MemoryCredentials()
    service = CloudTaskAssistant(repository, credentials, request_fn=request_fn)
    return repository, credentials, service


def test_cloud_is_off_by_default_and_never_calls_transport(tmp_path):
    called = []
    repository, _credentials, service = make_service(
        tmp_path, request_fn=lambda *args, **kwargs: called.append((args, kwargs))
    )
    assert service.enabled is False
    with pytest.raises(CloudAIError, match="未获授权"):
        service.prepare("- 草稿".encode(), "tasks.txt")
    assert called == []
    assert repository.get_consent("cloud_task_ai") is None


def test_cloud_ai_is_wired_into_settings_but_starts_disabled(tmp_path):
    from PySide6.QtWidgets import QApplication
    from deskcare.config import ConfigStore
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.consent_service import MonitoringController
    from deskcare.ui.main_window import MainWindow

    app = QApplication.instance() or QApplication([])
    repository, _credentials, service = make_service(tmp_path)
    controller = MonitoringController(FakeActivityProvider())
    window = MainWindow(ConfigStore(), controller, repository=repository, cloud_ai_service=service)
    assert window.settings_page.cloud_ai.isChecked() is False
    assert service.enabled is False
    assert window.settings_page.cloud_key_status.text() == "尚未保存 API Key。"
    window._allow_close = True
    window.close()
    app.processEvents()


def test_cloud_request_preview_is_exact_body_and_contains_only_selected_text(tmp_path):
    repository, _credentials, service = make_service(tmp_path)
    service.configure("https://api.example.test/v1/chat/completions", "test-model")
    service.set_enabled(True)
    request = service.prepare("- 完成演示\n".encode(), "today.txt")
    preview = json.loads(request.preview())
    assert preview == json.loads(request.body.decode())
    assert preview["model"] == "test-model"
    assert preview["messages"][-1]["content"] == "- 完成演示\n"
    assert "BodyLog" not in preview["messages"][-1]["content"]
    assert "Authorization" not in request.preview()
    assert request.endpoint == "https://api.example.test/v1/chat/completions"


def test_canceling_cloud_preview_never_starts_parser(monkeypatch, tmp_path):
    from PySide6.QtWidgets import QApplication, QDialog
    from deskcare.domain.types import TaskDraft
    from deskcare.importers.base import ImportResult
    from deskcare.ui.task_dialog import ImportPreviewDialog

    app = QApplication.instance() or QApplication([])
    _repository, _credentials, service = make_service(tmp_path)
    service.configure("https://api.example.test/chat", "test-model")
    service.set_enabled(True)
    request = service.prepare(b"- private test task", "tasks.txt")
    parsed = []
    result = ImportResult("tasks.txt", (TaskDraft("rule task", None, None, 1, ()),), ())
    dialog = ImportPreviewDialog(
        result, cloud_request_factory=lambda: request,
        cloud_parser=lambda item: (parsed.append(item) or result),
    )
    monkeypatch.setattr(QDialog, "exec", lambda _self: QDialog.DialogCode.Rejected)
    dialog._start_cloud()
    app.processEvents()
    assert parsed == []
    assert dialog.table.item(0, 0).text() == "rule task"
    dialog.close()


def test_cloud_posts_previewed_payload_and_returns_unpersisted_candidate(tmp_path):
    captured = []
    def send(request, timeout):
        captured.append((request, timeout))
        return Response({"choices": [{"message": {"content": json.dumps({
            "tasks": [{"title": "整理演示文稿", "due_at": None, "estimated_minutes": 25}]
        }, ensure_ascii=False)}}]})

    repository, credentials, service = make_service(tmp_path, request_fn=send)
    service.configure("https://api.example.test/v1/chat/completions", "test-model")
    service.set_enabled(True)
    service.save_key("test-secret")
    request = service.prepare("- 整理演示文稿".encode(), "tasks.md")
    result = service.parse(request)

    sent_request, timeout = captured[0]
    assert sent_request.data == request.body
    assert sent_request.get_header("Authorization") == "Bearer test-secret"
    assert timeout == 20
    assert result.drafts[0].title == "整理演示文稿"
    assert repository.tasks_for_day() == []
    assert repository.get_setting("cloud_task_api_key") is None


def test_cloud_key_requires_consent_and_revocation_deletes_it(tmp_path):
    _repository, credentials, service = make_service(tmp_path)
    with pytest.raises(CloudAIError):
        service.save_key("secret")
    service.set_enabled(True)
    service.save_key("secret")
    assert service.has_key
    service.set_enabled(False)
    assert credentials.value is None
    assert not service.enabled


@pytest.mark.parametrize("endpoint", [
    "http://api.example.test/v1/chat/completions",
    "https://user:pass@example.test/chat",
    "https://example.test/chat?key=secret",
])
def test_cloud_endpoint_requires_clean_https(endpoint, tmp_path):
    _repository, _credentials, service = make_service(tmp_path)
    with pytest.raises(ValueError):
        service.configure(endpoint, "model")


def test_cloud_transport_errors_are_sanitized_and_fallback_remains_separate(tmp_path):
    def fail(_request, timeout):
        raise RuntimeError("provider echoed secret-token and internal url")

    _repository, credentials, service = make_service(tmp_path, request_fn=fail)
    service.configure("https://api.example.test/chat", "test-model")
    service.set_enabled(True)
    credentials.save("secret-token")
    request = service.prepare("- user task".encode(), "tasks.txt")
    with pytest.raises(CloudAIError) as error:
        service.parse(request)
    assert "secret-token" not in str(error.value)
    assert "internal url" not in str(error.value)
