from datetime import datetime, timedelta
import sqlite3

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QMessageBox

from deskcare.config import ConfigStore
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.services.report_engine import LocalReportService
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui import health_journal as journal_ui
from deskcare.ui.main_window import MainWindow
from deskcare.ui.task_dialog import TaskFormDialog


@pytest.fixture
def shell(tmp_path):
    app = QApplication.instance() or QApplication([])
    repo = UsageRepository(tmp_path / "ui-private-fake.sqlite3")
    ctl = MonitoringController(FakeActivityProvider())
    tasks = TaskService(repo)
    window = MainWindow(ConfigStore(), ctl, ActivityCollector(ctl, repo), tasks,
                        repository=repo, report_service=LocalReportService(repo))
    window.resize(1040, 680)
    window.show()
    window._open_health_journal()
    for _ in range(3):
        app.processEvents()
    yield app, window, repo, window.health_journal_service, window.reports_page.journal_page
    window._allow_close = True
    window.close()
    window.deleteLater()
    app.processEvents()


def save_event(service, index=0):
    return service.save(occurred_at=datetime.now()-timedelta(minutes=index), description=f"虚构事件 {index}")


def test_permission_denial_then_grant_and_clear_page_after_revoke(shell, monkeypatch):
    app, window, repo, service, page = shell
    assert not page.add_button.isEnabled() and not page.consent.isChecked()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    page.consent.setChecked(True)
    assert not service.enabled and not page.consent.isChecked()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page.consent.setChecked(True)
    assert service.enabled and repo.get_consent("wellness_checkin") is None
    entry = save_event(service)
    assert page.table.rowCount() == 1
    page.consent.setChecked(False)
    assert not service.enabled and page.table.rowCount() == 0
    assert not window.monitoring_controller.enabled


def test_cancel_and_save_form_do_not_guess_symptoms_or_create_tasks(shell, monkeypatch):
    app, window, repo, service, page = shell
    service.set_enabled(True)
    class Cancelled:
        def exec(self): return QDialog.DialogCode.Rejected
        def deleteLater(self): pass
    monkeypatch.setattr(journal_ui, "JournalEntryDialog", lambda *args, **kwargs: Cancelled())
    page.add_button.click()
    assert not service.events() and not window.task_service.list_all()
    form = journal_ui.JournalFollowupDialog(datetime.now())
    with pytest.raises(ValueError):
        form.values()  # no default improvement selected
    form.reject()
    form.deleteLater()


def test_explicit_action_opens_confirmed_task_and_does_not_copy_health_text(shell, monkeypatch):
    app, window, repo, service, page = shell
    service.set_enabled(True)
    entry = save_event(service)
    class Confirmed(TaskFormDialog):
        def exec(self):
            return QDialog.DialogCode.Accepted
    monkeypatch.setattr(journal_ui, "TaskFormDialog", Confirmed)
    page.action_button.click()
    assert window.navigation.currentRow() == 0
    task = window.today_page._selected_task()
    assert task.title == "给自己留一点调整时间" and task.notes == ""
    assert entry.description not in task.title
    assert service.repository.actions(entry.id)[0].task_id == task.id


def test_pagination_small_window_export_and_followup_counts(shell, monkeypatch, tmp_path):
    app, window, repo, service, page = shell
    service.set_enabled(True)
    for index in range(14):
        save_event(service, index)
    for _ in range(3):
        app.processEvents()
    assert page.pager.pages > 1
    assert page.table.verticalScrollBar().maximum() == 0
    assert page.table.rowCount() <= page._page_size
    first = page._selected().id
    page.pager.next.click()
    assert page._selected().id != first
    entry = page._selected()
    service.followup(entry.id, recorded_at=datetime.now(), change="unsure", note="虚构补记")
    assert "1 次" in page.table.item(page.table.currentRow(), 3).text()
    path = tmp_path / "explicit-export.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(path), ""))
    page.export_button.click()
    content = path.read_text(encoding="utf-8")
    assert "说不准" in content and "虚构补记" in content
    service.delete_followup(entry.id, service.repository.followups(entry.id)[0].id)
    assert "虚构补记" not in service.review(entry.id)


def test_clear_all_updates_journal_and_open_review_clears_on_revocation(shell):
    app, window, repo, service, page = shell
    service.set_enabled(True)
    entry = save_event(service)
    dialog = journal_ui.JournalReviewDialog(service, entry.id)
    service.subscribe(dialog.refresh)
    assert entry.description in dialog.review_text.toPlainText()
    repo.clear_all_data()
    window._refresh_after_data_clear()
    assert not page.consent.isChecked() and page.table.rowCount() == 0
    assert not dialog.review_text.toPlainText()
    service.unsubscribe(dialog.refresh)
    dialog.deleteLater()


def test_entry_form_explicit_fields_and_backdate_selects_correct_page(shell):
    app, window, repo, service, page = shell
    service.set_enabled(True)
    dialog = journal_ui.JournalEntryDialog(datetime.now())
    assert dialog.severity_edit.currentData() is None
    assert not dialog.description_edit.text()
    dialog.description_edit.setText("虚构手填，不自动补其他字段")
    values = dialog.values()
    assert values["severity"] is None and values["duration_minutes"] is None
    dialog.reject()
    dialog.deleteLater()
    old = service.save(occurred_at=datetime.now()-timedelta(days=40), description="虚构旧记录")
    assert page.table.rowCount() == 0
    page._show_event(old)
    assert page.period.currentIndex() == 2 and page._selected().id == old.id


def test_review_treats_notes_as_plain_text_without_external_resources(shell):
    app, window, repo, service, page = shell
    service.set_enabled(True)
    text = '<img src="file:///private-health.png"><script>not code</script>'
    entry = service.save(occurred_at=datetime.now(), description=text)
    dialog = journal_ui.JournalReviewDialog(service, entry.id)
    assert text in dialog.review_text.toPlainText()
    assert dialog.review_text.loadResource(2, "file:///private-health.png") is None
    assert not dialog.review_text.openExternalLinks()
    dialog.deleteLater()


def test_failed_health_write_keeps_form_and_does_not_expose_error_body(shell, monkeypatch):
    app, window, repo, service, page = shell
    service.set_enabled(True)
    class Attempt(journal_ui.JournalEntryDialog):
        calls = 0
        def exec(self):
            self.calls += 1
            return QDialog.DialogCode.Accepted if self.calls == 1 else QDialog.DialogCode.Rejected
    dialog = Attempt(datetime.now())
    dialog.description_edit.setText("虚构待保存内容")
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append((args, dialog.description_edit.text())))
    def fail(values):
        raise sqlite3.OperationalError("PRIVATE_ERROR_BODY")
    page._run_form(dialog, fail)
    assert not service.events()
    assert warnings[0][1] == "虚构待保存内容"
    assert "PRIVATE_ERROR_BODY" not in str(warnings)


def test_failed_revocation_does_not_claim_data_deleted(shell, monkeypatch):
    app, window, repo, service, page = shell
    service.set_enabled(True)
    save_event(service)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    def fail(enabled):
        raise sqlite3.OperationalError("locked")
    monkeypatch.setattr(service, "set_enabled", fail)
    page.consent.setChecked(False)
    assert service.enabled and page.consent.isChecked() and len(service.events()) == 1
    assert warnings
