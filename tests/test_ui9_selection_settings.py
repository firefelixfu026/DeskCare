from datetime import date, timedelta
import sqlite3

import pytest
from PySide6.QtCore import QItemSelectionModel, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu, QMessageBox

from deskcare.config import ConfigStore
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.pages import SettingsPage, TodayPage, UsagePage
from deskcare.ui.theme import apply_theme


@pytest.fixture
def page(tmp_path):
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    repo = UsageRepository(tmp_path / "selection.sqlite3")
    service = TaskService(repo)
    for i in range(20):
        service.add_manual(f"虚构任务 {i}")
    widget = TodayPage(MonitoringController(FakeActivityProvider()), service)
    widget.resize(1000, 700)
    widget.show()
    for _ in range(3):
        app.processEvents()
    yield app, widget, service
    widget.close()
    widget.deleteLater()
    app.processEvents()


def select_rows(page, rows):
    page.task_table.clearSelection()
    for row in rows:
        page.task_table.selectionModel().select(page.task_table.model().index(row, 1),
            QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows)


def test_ctrl_shift_mouse_selection_and_refresh(page):
    app, widget, service = page
    table = widget.task_table
    def click(row, modifier=Qt.KeyboardModifier.NoModifier):
        QTest.mouseClick(table.viewport(), Qt.MouseButton.LeftButton, modifier,
                        table.visualItemRect(table.item(row, 1)).center())
    click(0)
    click(2, Qt.KeyboardModifier.ControlModifier)
    ids = {task.id for task in widget._selected_tasks()}
    assert len(ids) == 2 and "2" in widget.delete_button.text()
    assert not widget.edit_button.isEnabled()
    service.add_manual("新增加的虚构任务")
    assert {task.id for task in widget._selected_tasks()} == ids
    click(0)
    click(2, Qt.KeyboardModifier.ShiftModifier)
    assert len(widget._selected_tasks()) == 3


def test_confirm_cancel_and_atomic_batch_delete_one_notification(page, monkeypatch):
    app, widget, service = page
    select_rows(widget, [0, 2])
    selected = {task.id for task in widget._selected_tasks()}
    notices = []
    service.subscribe(lambda: notices.append(True))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    widget._delete_selected()
    assert len(service.list_all()) == 20
    assert not notices
    prompts = []
    def approve(*args):
        prompts.append(args)
        return QMessageBox.StandardButton.Yes
    monkeypatch.setattr(QMessageBox, "question", approve)
    widget._delete_selected()
    assert len(service.list_all()) == 18 and notices == [True]
    assert not selected & {task.id for task in service.list_all()}
    assert "2 项" in prompts[0][2]
    assert prompts[0][-1] == QMessageBox.StandardButton.No


def test_select_page_cannot_delete_hidden_pages_and_empty_selection_is_safe(page, monkeypatch):
    app, widget, service = page
    widget.select_page_button.click()
    count = len(widget._tasks)
    assert len(widget._selected_tasks()) == count < 20
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    widget._delete_selected()
    assert len(service.list_all()) == 20 - count
    widget.task_pager.next.click()
    widget.task_table.clearSelection()
    widget._delete_selected()
    assert len(service.list_all()) == 20 - count
    assert not widget.delete_button.isEnabled()


def test_right_click_preserves_selected_group_and_retargets_unselected_row(page):
    app, widget, service = page
    select_rows(widget, [0, 1])
    menus = []
    def inspect_menu():
        for menu in widget.findChildren(QMenu):
            if menu.parent() is widget and menu.isVisible():
                menus.append(([task.id for task in widget._selected_tasks()], [action.text() for action in menu.actions()]))
                menu.close()
    QTimer.singleShot(0, inspect_menu)
    widget._task_menu(widget.task_table.visualItemRect(widget.task_table.item(1, 1)).center())
    assert len(menus[0][0]) == 2
    assert "删除选中（2）" in menus[0][1]
    assert "编辑任务与时间" not in menus[0][1]
    QTimer.singleShot(0, inspect_menu)
    widget._task_menu(widget.task_table.visualItemRect(widget.task_table.item(2, 1)).center())
    assert len(menus[1][0]) == 1


def test_repository_batch_failure_rolls_back_every_delete(tmp_path):
    repo = UsageRepository(tmp_path / "rollback.sqlite3")
    first, second = repo.add_task("虚构一"), repo.add_task("虚构二")
    with repo._connect() as conn:
        conn.execute(f"CREATE TRIGGER reject_delete BEFORE DELETE ON tasks WHEN OLD.id={second.id} BEGIN SELECT RAISE(ABORT, 'test'); END")
    with pytest.raises(sqlite3.IntegrityError):
        repo.delete_tasks([first.id, second.id])
    assert {task.id for task in repo.all_tasks()} == {first.id, second.id}
    with pytest.raises(ValueError):
        repo.delete_tasks([first.id, -1])
    assert len(repo.all_tasks()) == 2


def test_week_return_button_text_and_range(tmp_path):
    QApplication.instance() or QApplication([])
    repo = UsageRepository(tmp_path / "week.sqlite3")
    ctl = MonitoringController(FakeActivityProvider())
    widget = UsagePage(ctl, ActivityCollector(ctl, repo))
    assert widget.period_today.text() == "回到今天"
    widget.period_choice.setCurrentIndex(1)
    assert widget.period_today.text() == "回到本周"
    widget.period_previous.click()
    widget.period_today.click()
    start, end = widget.period_range()
    assert start <= date.today() <= end and start.weekday() == 0
    widget.period_choice.setCurrentIndex(0)
    assert widget.period_today.text() == "回到今天"
    widget.close()


def test_ai_cards_match_layout_and_expansion_does_not_grant_consent(tmp_path):
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    from deskcare.ai.optional_local_llm import LocalAIService
    repo = UsageRepository(tmp_path / "ai.sqlite3")
    ctl = MonitoringController(FakeActivityProvider())
    widget = SettingsPage(ConfigStore(), ctl, ActivityCollector(ctl, repo),
                          local_ai_service=LocalAIService(repo))
    widget.resize(1000, 700)
    widget.sections.setCurrentIndex(2)
    widget.show()
    app.processEvents()
    assert widget.local_ai_card.objectName() == widget.cloud_ai_card.objectName() == "aiServiceCard"
    assert widget.local_ai_card.width() == widget.cloud_ai_card.width()
    assert widget.local_ai_advanced_button.objectName() == widget.cloud_advanced_button.objectName() == "secondaryButton"
    assert not widget.local_ai.isChecked() and not widget.cloud_ai.isChecked()
    widget.local_ai_advanced_button.click()
    widget.cloud_advanced_button.click()
    app.processEvents()
    assert not widget.local_ai_config.isHidden() and not widget.cloud_advanced_frame.isHidden()
    assert not widget.local_ai_service.enabled
    assert repo.get_consent("cloud_ai") is not True
    assert not ctl.enabled
    assert widget.settings_scroll.horizontalScrollBar().maximum() == 0
    widget.close()


def test_reminder_minutes_visible_typing_commit_invalid_restore_and_reload(tmp_path):
    from deskcare.services.reminder_service import ReminderCoordinator
    from deskcare.ui.main_window import MainWindow
    from PySide6.QtWidgets import QStyle, QStyleOptionFrame
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    repo = UsageRepository(tmp_path / "minutes.sqlite3")
    ctl = MonitoringController(FakeActivityProvider())
    collector = ActivityCollector(ctl, repo)
    service = TaskService(repo)
    coordinator = ReminderCoordinator(ctl, collector, service, repo)
    window = MainWindow(ConfigStore(), ctl, collector, service, coordinator, repo)
    window.resize(1040, 680)
    window.show()
    window.navigation.setCurrentRow(4)
    window.settings_page.sections.setCurrentIndex(1)
    app.processEvents()
    edit = window.settings_page.reminder_interval
    assert edit.isVisible() and edit.text() == "40"
    option = QStyleOptionFrame()
    option.initFrom(edit)
    contents = edit.style().subElementRect(QStyle.SubElement.SE_LineEditContents, option, edit)
    assert contents.width() >= edit.fontMetrics().horizontalAdvance("180") + 4
    assert contents.height() >= edit.fontMetrics().height()
    edit.setFocus()
    edit.selectAll()
    QTest.keyClicks(edit, "13")
    assert repo.get_setting("reminder_interval_minutes") is None
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert edit.value() == 13 and repo.get_setting("reminder_interval_minutes") == "13"
    assert coordinator.policy.config.break_candidate_minutes == 13
    edit.selectAll()
    QTest.keyClicks(edit, "27")
    window.settings_page.activity_tips.setFocus()
    app.processEvents()
    assert edit.value() == 27 and coordinator.policy.config.break_candidate_minutes == 27
    edit.setFocus()
    edit.clear()
    window.settings_page.activity_tips.setFocus()
    app.processEvents()
    assert edit.text() == "27" and repo.get_setting("reminder_interval_minutes") == "27"
    edit.setText("0")
    QTest.keyClick(edit, Qt.Key.Key_Return)
    assert edit.text() == "27"
    assert ReminderCoordinator.saved_interval(UsageRepository(repo.path)) == 27
    assert not ctl.enabled and repo.latest_reminder_event() is None
    window._allow_close = True
    window.close()
