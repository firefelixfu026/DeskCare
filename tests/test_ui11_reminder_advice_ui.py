import time
from threading import Event

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

from test_ui11_reminder_advice import setup, add_feedback, output, transport
from deskcare.ai.reminder_advisor import ReminderAIAdvisor
from deskcare.config import ConfigStore
from deskcare.ui.main_window import MainWindow
from deskcare.ui.reminder_advice import ReminderAdviceDialog


@pytest.fixture
def dialog(setup):
    app = QApplication.instance() or QApplication([])
    calls = []
    advisor = ReminderAIAdvisor(setup.service, cloud_ai=setup.cloud, request_fn=transport(output(), calls))
    page = ReminderAdviceDialog(setup.service, advisor)
    page.begin()
    app.processEvents()
    yield app, page, setup, calls
    page.reject()
    if page._thread:
        page._thread.quit()
        page._thread.wait(20000)
    page.deleteLater()
    app.processEvents()


def pump(app, page):
    end = time.monotonic() + 5
    while page._thread is not None and time.monotonic() < end:
        app.processEvents()
        time.sleep(.005)
    app.processEvents()
    assert page._thread is None


def test_consent_preview_send_and_confirm_are_four_separate_steps(dialog, monkeypatch):
    app, page, s, calls = dialog
    assert page.comfort.currentData() is None
    assert page.task.currentData() is None
    assert not page.consent.isChecked()
    page.prepare_button.click()
    assert page.preview.toPlainText() and not calls and not page.send_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.No)
    page.consent.setChecked(True)
    assert not s.service.enabled and not page.consent.isChecked()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    page.consent.setChecked(True)
    # Consent changes invalidate an earlier prepared authorization epoch.
    page.prepare_button.click()
    page.send_button.click()
    pump(app, page)
    assert len(calls) == 1
    assert "联网 AI 策略建议" in page.result.toPlainText()
    assert s.coord.policy.config.break_candidate_minutes == 40
    page.apply_button.click()
    assert s.coord.policy.config.break_candidate_minutes == 60
    assert not page.send_button.isEnabled()


def test_reselect_clears_preview_and_manual_comfort_is_not_persisted(dialog):
    app, page, s, calls = dialog
    page.prepare_request()
    page.comfort.setCurrentIndex(2)
    assert not page.preview.toPlainText() and not page.send_button.isEnabled()
    assert "comfort" in page.result.toPlainText() or "主动提供" in page.result.toPlainText()
    page.reject()
    page.begin()
    assert page.comfort.currentData() is None
    assert s.repo.wellness_for_day(s.now[0].date()) is None
    assert not calls


@pytest.mark.parametrize("action", ["close", "revoke", "edit"])
def test_cancel_revoke_or_edit_while_running_never_applies_old_result(dialog, monkeypatch, action):
    app, page, s, calls = dialog
    gate = Event()
    def delayed(*args, **kwargs):
        gate.wait(3)
        return transport(output(), calls)(*args, **kwargs)
    page.advisor.request_fn = delayed
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    page.consent.setChecked(True)
    page.prepare_request()
    page.send_request()
    if action == "close": page.reject()
    if action == "revoke": page.consent.setChecked(False)
    if action == "edit": s.coord.set_mode("quiet")
    gate.set()
    pump(app, page)
    assert not page.apply_button.isEnabled()
    assert s.coord.policy.config.break_candidate_minutes == 40


def test_local_rule_interval_can_be_applied_without_ai_consent(dialog, monkeypatch):
    app, page, s, calls = dialog
    add_feedback(s)
    page.refresh_context()
    assert page.apply_button.isEnabled()
    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    page.apply_button.click()
    assert s.coord.policy.config.break_candidate_minutes == 50
    assert not s.service.enabled and not calls
    assert s.personal.snapshot.suggested_minutes is None


def test_preview_or_result_text_does_not_interpret_task_markup_and_controls_fit(dialog):
    app, page, s, calls = dialog
    task = s.tasks.add_manual('<img src="file:///private.png"> malicious title')
    page.begin()
    page.task.setCurrentIndex(page.task.findData(task.id))
    page.resize(690, 600)
    app.processEvents()
    assert task.title in page.context_summary.text()
    assert page.apply_button.geometry().bottom() < page.height()
    assert page.result.height() >= 100
    page.details.setCurrentIndex(1)
    app.processEvents()
    assert page.preview.height() >= 100


def test_main_window_entry_banner_and_interval_sync(setup):
    s = setup
    app = QApplication.instance() or QApplication([])
    window = MainWindow(ConfigStore(), s.controller, s.collector, s.tasks, s.coord, s.repo,
                        personalization_service=s.personal)
    window.show()
    add_feedback(s)
    app.processEvents()
    assert not window.today_page.feedback_review.isHidden()
    window.settings_page.analyze_reminder.click()
    page = window._reminder_advice_dialog
    assert page.isVisible()
    window._sync_advised_interval(55)
    assert window.settings_page.reminder_interval.value() == 55
    s.personal.dismiss_current_suggestion()
    assert window.today_page.feedback_review.isHidden()
    page.reject()
    window._allow_close = True
    window.close()
    window.deleteLater()
    app.processEvents()
