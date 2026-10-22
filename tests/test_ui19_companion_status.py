"""Fictional task rows exercise the same three-state menu as the main page."""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QPushButton

from deskcare.domain.types import TaskStatus
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.companion import CompanionWindow
from deskcare.ui.task_status import TaskStatusCombo


@pytest.fixture
def setup(tmp_path):
    app = QApplication.instance() or QApplication([])
    tasks = TaskService(UsageRepository(tmp_path / 'fictional.sqlite3'))
    task = tasks.add_manual('虚构任务，不读取个人资料')
    completed = Mock()
    window = CompanionWindow(tasks, repository=tasks.repository)
    window.reminder_coordinator = SimpleNamespace(mark_task_completed=completed)
    window.show()
    app.processEvents()
    yield app, window, tasks, task, completed
    window.hide()
    window._day_timer.stop()
    window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def control(window):
    return window.task_list.itemAt(0).widget().findChild(TaskStatusCombo)


@pytest.mark.parametrize('state', [TaskStatus.TODO, TaskStatus.DOING, TaskStatus.DONE])
def test_real_popup_mouse_click_persists_selected_state(setup, state):
    app, window, tasks, task, completed = setup
    combo = control(window)
    QTest.mouseClick(combo, Qt.MouseButton.LeftButton, pos=combo.badge_rect().center().toPoint())
    app.processEvents()
    assert combo.menu.isVisible()
    assert combo.menu.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert [action.text() for action in combo.menu.actions()] == ['待处理', '进行中', '已完成']
    index = combo.findData(state)
    QTest.mouseClick(combo.menu, Qt.MouseButton.LeftButton,
                     pos=combo.menu.actionGeometry(combo.menu.actions()[index]).center())
    app.processEvents()
    assert tasks.list_all()[0].status is state
    assert QApplication.activePopupWidget() is None
    if state is TaskStatus.DONE:
        assert not tasks.list_today() and tasks.list_completed()[0].completed_at
        completed.assert_called_once_with()
    else:
        assert control(window).currentData() == state
        completed.assert_not_called()


def test_open_cancel_and_reselect_current_do_not_write(setup):
    app, window, tasks, task, completed = setup
    notify = Mock()
    tasks.subscribe(notify)
    combo = control(window)
    combo.showPopup()
    QTest.keyClick(combo.menu, Qt.Key.Key_Down)
    assert tasks.list_today()[0] == task
    QTest.keyClick(combo.menu, Qt.Key.Key_Escape)
    assert not combo.menu.isVisible() and tasks.list_today()[0] == task
    combo.showPopup()
    combo.menu.actions()[0].trigger()
    notify.assert_not_called()
    completed.assert_not_called()


def test_keyboard_selection_does_not_save_until_enter(setup):
    app, window, tasks, task, completed = setup
    combo = control(window)
    QTest.keyClick(combo, Qt.Key.Key_Space)
    QTest.keyClick(combo.menu, Qt.Key.Key_Down)
    assert tasks.list_today()[0].status is TaskStatus.TODO
    QTest.keyClick(combo.menu, Qt.Key.Key_Return)
    assert tasks.list_today()[0].status is TaskStatus.DOING


def test_external_status_change_does_not_get_overwritten_by_old_row(setup):
    app, window, tasks, task, completed = setup
    combo = control(window)
    tasks.repository.set_task_status(task.id, TaskStatus.DOING)  # Simulate another entry point.
    combo.setCurrentIndex(combo.findData(TaskStatus.DONE))
    assert tasks.list_all()[0].status is TaskStatus.DOING
    assert control(window).currentData() == TaskStatus.DOING
    completed.assert_not_called()


def test_refresh_and_deleted_task_close_any_old_popup(setup):
    app, window, tasks, task, completed = setup
    combo = control(window)
    combo.showPopup()
    tasks.delete(task.id)
    assert not combo.menu.isVisible()
    window._set_task_status(task.id, TaskStatus.DONE, TaskStatus.TODO)
    assert not tasks.list_all()
    completed.assert_not_called()


def test_main_page_menu_does_not_become_always_on_top(setup):
    from PySide6.QtWidgets import QWidget, QVBoxLayout
    app, _, _, _, _ = setup
    main = QWidget()
    layout = QVBoxLayout(main)
    combo = TaskStatusCombo()
    combo.addItem('待处理', TaskStatus.TODO)
    layout.addWidget(combo)
    main.show()
    combo.showPopup()
    assert not combo.menu.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    combo.hidePopup()
    main.close()
    main.deleteLater()


def test_title_remains_separate_and_status_label_fits(setup):
    app, window, tasks, task, completed = setup
    row = window.task_list.itemAt(0).widget()
    assert row.findChild(QPushButton, 'companionTaskTitle')
    combo = control(window)
    text_width = combo.fontMetrics().horizontalAdvance('进行中')
    assert combo.badge_rect().width() - 43 >= text_width
    assert combo.isVisible()
    assert tasks.list_today()[0] == task
