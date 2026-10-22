"""Synthetic-only report review transport, privacy, lifecycle and Qt contracts."""
from dataclasses import replace
from datetime import datetime, timedelta
import json
from types import SimpleNamespace

import pytest

from deskcare.services.reminder_advice import AdviceError
from deskcare.services.report_engine import LocalReportService, ReportPeriod
from deskcare.services.report_review import ReportReviewService
from deskcare.storage.database import UsageRepository


class Credentials:
    def __init__(self):
        self.loads = 0

    def load(self):
        self.loads += 1
        return 'synthetic-credential'


def facts(repo):
    today = datetime.now().date()
    data, _ = LocalReportService(repo).render(ReportPeriod('daily', today, today))
    data['tasks'] = {'confirmed_total': 4, 'completed_by_user': 1, 'open': 3}
    data['reminders'].update(shown=8, snoozed=3, skipped=1, bad_timing=2, break_intent_confirmed=1)
    data['applications'] = {'top_apps': [{'name': 'PRIVATE_APP'}]}
    data['wellness'] = {'entries': [{'comfort_level': 'PRIVATE_HEALTH'}]}
    data['usage']['by_category_minutes'] = {'PRIVATE_CATEGORY': 12}
    data['task_titles'] = ['PRIVATE_TASK_TITLE']
    data['notes'] = 'PRIVATE_NOTE'
    return data


@pytest.fixture
def context(tmp_path):
    repo = UsageRepository(tmp_path / 'synthetic.sqlite3')
    credentials = Credentials()
    cloud = SimpleNamespace(endpoint='https://api.deepseek.com/chat/completions', model='deepseek-flash', credentials=credentials)
    sent = []

    def transport(request, timeout):
        assert timeout == 15
        sent.append(request)
        raw = {'focus': ['open_tasks', 'bad_timing'], 'next_steps': ['tasks', 'reminders']}
        response = {'choices': [{'message': {'content': json.dumps(raw)}, 'finish_reason': 'stop'}]}
        return SimpleNamespace(read=lambda _limit: json.dumps(response).encode(), close=lambda: None)

    service = ReportReviewService(repo, cloud_ai=cloud, request_fn=transport)
    snapshot = service.snapshot(facts(repo))
    return repo, service, snapshot, sent, credentials


def test_preview_is_allowlisted_readable_and_never_loads_key_or_calls_model(context):
    repo, service, snapshot, sent, credentials = context
    repo.set_consent('cloud_task_ai', True)  # Task consent is not report consent.
    request = service.prepare(snapshot, 'cloud')
    assert not service.enabled and not sent and credentials.loads == 0
    data = json.loads(request.body)
    content = json.loads(data['messages'][1]['content'])
    assert set(content['aggregates']) == {'period', 'data_is_demo', 'coverage', 'usage', 'tasks', 'reminders'}
    assert 'PRIVATE_' not in request.body.decode()
    assert 'synthetic-credential' not in request.body.decode()
    assert '推迟 3 次' in snapshot.human_preview()
    assert '明确不合适 2 次' in snapshot.human_preview()
    assert 'json' not in snapshot.human_preview()
    assert data['thinking'] == {'type': 'disabled'}
    with pytest.raises(AdviceError):
        service.analyze(request, confirmed=True)
    assert not sent and credentials.loads == 0


def test_explicit_send_single_use_preserves_facts_and_counts(context):
    repo, service, snapshot, sent, credentials = context
    service.set_enabled(True)
    request = service.prepare(snapshot, 'cloud')
    with pytest.raises(AdviceError):
        service.analyze(request)
    cards, actions = service.analyze(request, confirmed=True)
    assert [card.key for card in cards] == ['open_tasks', 'bad_timing']
    assert actions == ('tasks', 'reminders')
    assert '3 项' in cards[0].title and '2 次' in cards[1].title
    assert len(sent) == credentials.loads == 1
    assert not repo.all_tasks()  # Never mutates any task or reminder.
    with pytest.raises(AdviceError):
        service.analyze(request, confirmed=True)
    assert len(sent) == 1


@pytest.mark.parametrize('change', ['revoke', 'renew', 'config', 'body', 'expire', 'invalidate'])
def test_changed_preview_or_consent_does_not_send(context, change):
    _, service, snapshot, sent, credentials = context
    service.set_enabled(True)
    request = service.prepare(snapshot, 'cloud')
    if change == 'revoke':
        service.set_enabled(False)
    elif change == 'renew':
        service.prepare(snapshot, 'cloud')
    elif change == 'config':
        service.cloud_ai.model = 'other-model'
    elif change == 'body':
        request = replace(request, body=b'{}')
    elif change == 'expire':
        service.clock = lambda: snapshot.captured_at + timedelta(minutes=6)
    else:
        service.invalidate()
    with pytest.raises(AdviceError):
        service.analyze(request, confirmed=True)
    assert not sent and credentials.loads == 0


def test_revocation_while_in_flight_discards_result(context):
    _, service, snapshot, sent, _ = context
    service.set_enabled(True)
    original = service.request_fn

    def transport(*args, **kwargs):
        result = original(*args, **kwargs)
        service.set_enabled(False)
        return result
    service.request_fn = transport
    with pytest.raises(AdviceError, match='丢弃'):
        service.analyze(service.prepare(snapshot, 'cloud'), confirmed=True)
    assert len(sent) == 1


@pytest.mark.parametrize('raw', [
    {}, {'focus': [], 'next_steps': []}, {'focus': ['invented'], 'next_steps': []},
    {'focus': ['usage', 'usage'], 'next_steps': []}, {'focus': [['usage']], 'next_steps': []},
    {'focus': ['usage'], 'next_steps': ['tasks']}, {'focus': ['usage'], 'next_steps': ['diagnose']},
    {'focus': ['usage'], 'next_steps': ['usage', 'usage']},
    {'focus': ['usage'], 'next_steps': [], 'advice': 'You are fatigued'},
])
def test_model_cannot_invent_facts_or_actions(context, raw):
    with pytest.raises(AdviceError):
        ReportReviewService.validate(raw, context[2])


def test_insufficient_coverage_and_snoozes_are_not_health_judgments(context):
    repo, service, _, _, _ = context
    data = facts(repo)
    data['reminders'].update(snoozed=1, bad_timing=0)
    snapshot = service.snapshot(data)
    keys = [card.key for card in snapshot.cards]
    assert 'coverage' in keys and 'bad_timing' not in keys and 'repeated_snooze' not in keys
    data['data_quality']['demo_data'] = True
    assert '虚构演示' in service.snapshot(data).human_preview()


def test_dialog_works_offline_preview_send_revoke_and_navigation(context, monkeypatch):
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QThread
    from deskcare.ui.report_review import ReportReviewDialog
    app = QApplication.instance() or QApplication([])
    repo, service, _, sent, _ = context
    dialog = ReportReviewDialog(service)
    original_render = dialog._render
    renders = []
    def render(*args):
        assert QThread.currentThread() == app.thread()  # Never touch widgets on model thread.
        renders.append(True)
        original_render(*args)
    monkeypatch.setattr(dialog, '_render', render)
    dialog.begin(facts(repo))
    assert '本机回顾' in dialog.status.text()
    assert not dialog.send_button.isEnabled()
    dialog.consent.setChecked(True)
    dialog.prepare_request()
    assert dialog.send_button.isEnabled()
    assert 'PRIVATE_' not in dialog.preview.toPlainText()
    dialog.send_request()
    for _ in range(500):
        app.processEvents()
        if dialog._thread is None:
            break
        QThread.msleep(5)
    assert dialog._thread is None and len(sent) == 1
    assert len(renders) >= 3
    assert '联网 AI 已挑选' in dialog.status.text()
    dialog.consent.setChecked(False)
    assert not service.enabled and not dialog.preview.toPlainText()
    assert '关闭' in dialog.status.text()
    navigated = []
    dialog.open_view_requested.connect(navigated.append)
    dialog._open_view('tasks')
    assert navigated == ['tasks']
    assert not dialog.isVisible()


def test_report_entry_uses_cloud_review_without_local_ai_and_keeps_original(tmp_path):
    from PySide6.QtWidgets import QApplication
    from deskcare.config import ConfigStore
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.consent_service import MonitoringController
    from deskcare.ui.main_window import MainWindow
    app = QApplication.instance() or QApplication([])
    repo = UsageRepository(tmp_path / 'synthetic.sqlite3')
    window = MainWindow(ConfigStore(), MonitoringController(FakeActivityProvider()),
                        repository=repo, report_service=LocalReportService(repo))
    report = window.reports_page
    original = report.report_text.toPlainText()
    report.ai_report_button.click()
    app.processEvents()
    dialog = window._report_review_dialog
    assert dialog.isVisible() and dialog.provider.currentData() == 'cloud'
    assert report.report_text.toPlainText() == original
    report.report_period.setCurrentIndex(1)
    assert not dialog.isVisible()
    window._open_report_review()
    window._refresh_after_data_clear()
    assert dialog.snapshot is None and not dialog.isVisible()
    window._allow_close = True
    window.close()


def test_closed_dialog_discards_in_flight_answer(context):
    import threading
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QThread
    from deskcare.ui.report_review import ReportReviewDialog
    app = QApplication.instance() or QApplication([])
    repo, service, _, _, _ = context
    release = threading.Event()
    original = service.request_fn
    def slow(*args, **kwargs):
        assert release.wait(3)
        return original(*args, **kwargs)
    service.request_fn = slow
    service.set_enabled(True)
    dialog = ReportReviewDialog(service)
    dialog.begin(facts(repo))
    dialog.prepare_request()
    dialog.send_request()
    dialog.reject()
    release.set()
    for _ in range(500):
        app.processEvents()
        if dialog._thread is None:
            break
        QThread.msleep(5)
    assert dialog._thread is None and not dialog.isVisible()
    assert '已挑选' not in dialog.status.text()


def test_network_failure_retains_offline_review_and_does_not_leak_errors(context):
    _, service, snapshot, _, _ = context
    service.set_enabled(True)
    def fail(*_args, **_kwargs):
        raise RuntimeError('secret internal provider details')
    service.request_fn = fail
    with pytest.raises(AdviceError) as error:
        service.analyze(service.prepare(snapshot, 'cloud'), confirmed=True)
    assert 'secret' not in str(error.value)
    assert snapshot.cards[0].key == 'open_tasks'


def test_companion_title_only_opens_read_only_details(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog, QPlainTextEdit, QPushButton
    from deskcare.domain.types import TaskStatus
    from deskcare.services.task_service import TaskService
    from deskcare.ui.companion import CompanionWindow
    QApplication.instance() or QApplication([])
    repo = UsageRepository(tmp_path / 'synthetic.sqlite3')
    service = TaskService(repo)
    task = service.add_manual('长任务 <b>仍是文字</b>')
    window = CompanionWindow(service, repository=repo)
    viewed = []

    def show(dialog):
        editor = dialog.findChild(QPlainTextEdit)
        assert editor.isReadOnly()
        viewed.append(editor.toPlainText())
    monkeypatch.setattr(QDialog, 'exec', show)
    window.task_list.itemAt(0).widget().findChild(QPushButton, 'companionTaskTitle').click()
    assert viewed and task.title in viewed[0]
    assert service.list_today()[0].status is TaskStatus.TODO
    window.close()
