import time
from threading import Event

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from test_ui11_reminder_advice import setup, transport
from deskcare.config import ConfigStore
from deskcare.services.assistant_service import AssistantService
from deskcare.ui.assistant import AssistantDialog
from deskcare.ui.main_window import MainWindow


@pytest.fixture
def shell(setup):
    s = setup
    from deskcare.ai.cloud_task_assistant import CloudTaskAssistant
    cloud = CloudTaskAssistant(s.repo, credential_store=s.cloud.credentials)
    cloud.configure(s.cloud.endpoint, s.cloud.model)
    s.cloud = cloud
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ConfigStore(), s.controller, s.collector, s.tasks, s.coord, s.repo,
                        personalization_service=s.personal, cloud_ai_service=s.cloud)
    window.resize(1040, 680)
    window.show()
    app.processEvents()
    yield app, window, s
    for page in (window._assistant_dialog, window._reminder_advice_dialog):
        if page:
            page.reject()
    window._allow_close = True
    window.close()
    window.deleteLater()
    app.processEvents()


def pump(app, page):
    end = time.monotonic()+5
    while page._thread is not None and time.monotonic() < end:
        app.processEvents()
        time.sleep(.005)
    app.processEvents()
    assert page._thread is None


def test_any_interval_writer_syncs_view_without_clobbering_a_typing_draft(shell):
    app, window, s = shell
    edit = window.settings_page.reminder_interval
    s.coord.set_interval(1)
    assert edit.value() == 1 and edit.text() == "1"
    # Same authoritative setting must not overwrite a partially typed value.
    edit.setText("13")
    s.coord._notify()
    assert edit.text() == "13" and edit.value() == 1
    # External AI/tool changes update value, text, config, and stored setting.
    s.coord.set_interval(5)
    assert edit.text() == "5" and edit.value() == 5
    assert s.repo.get_setting("reminder_interval_minutes") == "5"
    assert window.config_store.config.break_candidate_minutes == 5
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert s.coord.policy.config.break_candidate_minutes == 5
    s.coord.set_mode("focus")
    assert window.today_page.context_mode.currentData() == "focus"


def test_advice_real_confirmation_updates_all_three_and_survives_reload(shell, monkeypatch):
    app, window, s = shell
    s.coord.set_interval(1)
    window._open_reminder_advice()
    page = window._reminder_advice_dialog
    assert page.advice.interval_minutes == 40
    # Non-essential feedback bookmark failure cannot hide a successful setting.
    monkeypatch.setattr(s.personal, "dismiss_current_suggestion", lambda: (_ for _ in ()).throw(OSError("fake")))
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    page.apply_button.click()
    assert window.settings_page.reminder_interval.text() == "40"
    assert s.coord.policy.config.break_candidate_minutes == 40
    assert s.coord.saved_interval(s.repo) == 40
    assert "已保存" in page.status.text() and "40" in page.status.text()


def test_header_assistant_entry_human_send_confirm_and_cancel_are_real(shell, monkeypatch):
    app, window, s = shell
    window.assistant_button.click()
    page = window._assistant_dialog
    assert page.isVisible() and "我可以帮你" in page.transcript.toPlainText()
    assert page.consent.objectName() == "aiConsent"
    calls = []
    page.service.request_fn = transport({"tool": "set_interval", "arguments": {"minutes": 45}}, calls)
    page.input.setPlainText("把提醒改成45分钟")
    page.send.click()
    assert not calls and "授权" in page.status.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    page.consent.setChecked(True)
    monkeypatch.setattr(page, "confirm_send", lambda request: False)
    page.send.click()
    assert not calls
    previews = []
    def confirm(request):
        previews.append(request.human_preview())
        return True
    monkeypatch.setattr(page, "confirm_send", confirm)
    page.send.click()
    pump(app, page)
    assert "把提醒改成45分钟" in previews[0] and "response_format" not in previews[0]
    assert len(calls) == 1 and s.coord.policy.config.break_candidate_minutes == 40
    assert page.confirm.isEnabled() and "尚未修改" in page.proposal.text()
    page.confirm.click()
    assert s.coord.policy.config.break_candidate_minutes == 45
    assert window.settings_page.reminder_interval.text() == "45"
    assert not page.confirm.isEnabled()


@pytest.mark.parametrize("action", ["close", "revoke", "edit_input", "cancel"])
def test_assistant_cannot_apply_cancelled_or_replaced_plan(shell, monkeypatch, action):
    app, window, s = shell
    window._open_assistant()
    page = window._assistant_dialog
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(page, "confirm_send", lambda request: True)
    page.consent.setChecked(True)
    page.service.request_fn = transport({"tool": "set_interval", "arguments": {"minutes": 30}}, [])
    page.input.setPlainText("把提醒改成30分钟")
    page.send_message()
    pump(app, page)
    assert page.confirm.isEnabled()
    if action == "close": page.reject()
    if action == "revoke": page.consent.setChecked(False)
    if action == "edit_input": page.input.setPlainText("我改主意了")
    if action == "cancel": page.cancel_action.click()
    page.confirm.click()
    assert s.coord.policy.config.break_candidate_minutes == 40
    assert not page.confirm.isEnabled()


def test_assistant_closing_during_network_discards_and_tools_do_not_show_json(shell, monkeypatch):
    app, window, s = shell
    window._open_assistant()
    page = window._assistant_dialog
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(page, "confirm_send", lambda request: True)
    page.consent.setChecked(True)
    gate = Event()
    def delayed(*args, **kwargs):
        gate.wait(3)
        return transport({"tool": "set_interval", "arguments": {"minutes": 30}}, [])(*args, **kwargs)
    page.service.request_fn = delayed
    page.input.setPlainText("把提醒改成30分钟")
    page.send_message()
    page.reject()
    gate.set()
    pump(app, page)
    assert not page.confirm.isEnabled() and s.coord.policy.config.break_candidate_minutes == 40
    assert "response_format" not in page.transcript.toPlainText()


def test_assistant_resize_plain_text_and_read_only_tools_open_existing_pages(shell, monkeypatch):
    app, window, s = shell
    window._open_assistant()
    page = window._assistant_dialog
    page.resize(640, 560)
    app.processEvents()
    assert page.send.geometry().bottom() < page.height()
    assert page.input.height() == 76 and page.transcript.height() > 100
    window._assistant_open_view("usage")
    assert window.navigation.currentRow() == 1
    window._assistant_open_view("advice")
    assert window._reminder_advice_dialog.isVisible()
