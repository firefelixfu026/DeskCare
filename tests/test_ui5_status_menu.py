"""Exercise the real popup, not just programmatic combo index changes."""

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from deskcare.domain.types import TaskStatus
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.consent_service import MonitoringController
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.pages import TodayPage
from deskcare.ui.task_status import TaskStatusCombo
from deskcare.ui.theme import apply_theme


@pytest.fixture
def status_control(tmp_path):
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    service = TaskService(UsageRepository(tmp_path / "menu.sqlite3"))
    service.add_manual("状态菜单演示")
    page = TodayPage(MonitoringController(FakeActivityProvider()), service)
    page.resize(840, 580)
    page.show()
    app.processEvents()
    combo = page.task_table.cellWidget(0, 0)
    yield app, page, service, combo
    page.close()
    page.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_popup_all_three_actions_fit_without_scroll_container(status_control):
    app, page, service, combo = status_control
    assert isinstance(combo, TaskStatusCombo)
    combo.showPopup()
    app.processEvents()
    menu = combo.menu
    assert menu.isVisible()
    assert menu.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert [action.text() for action in menu.actions()] == ["待处理", "进行中", "已完成"]
    for action in menu.actions():
        rect = menu.actionGeometry(action)
        assert rect.height() >= 30
        assert menu.rect().contains(rect)
    assert menu.actions()[0].isChecked()
    assert service.list_today()[0].status is TaskStatus.TODO


@pytest.mark.parametrize("index,state", [(1, TaskStatus.DOING), (2, TaskStatus.DONE)])
def test_mouse_selects_actual_popup_row(status_control, index, state):
    app, page, service, combo = status_control
    combo.showPopup()
    app.processEvents()
    QTest.mouseClick(combo.menu, Qt.MouseButton.LeftButton,
                     pos=combo.menu.actionGeometry(combo.menu.actions()[index]).center())
    app.processEvents()
    assert service.list_all()[0].status is state
    if state is TaskStatus.DONE:
        assert not service.list_today()
        page._show_task(service.list_completed()[0])
    assert page.task_table.cellWidget(0, 0).currentData() == state
    assert QApplication.activePopupWidget() is None


def test_keyboard_opens_navigates_and_confirms(status_control):
    app, page, service, combo = status_control
    combo.setFocus()
    QTest.keyClick(combo, Qt.Key.Key_Space)
    app.processEvents()
    assert combo.menu.isVisible()
    QTest.keyClick(combo.menu, Qt.Key.Key_Down)
    assert service.list_today()[0].status is TaskStatus.TODO
    QTest.keyClick(combo.menu, Qt.Key.Key_Return)
    app.processEvents()
    assert service.list_today()[0].status is TaskStatus.DOING


def test_escape_cancels_without_persisting(status_control):
    app, page, service, combo = status_control
    combo.showPopup()
    QTest.keyClick(combo.menu, Qt.Key.Key_Down)
    QTest.keyClick(combo.menu, Qt.Key.Key_Escape)
    assert not combo.menu.isVisible()
    assert service.list_today()[0].status is TaskStatus.TODO


def test_mouse_opens_and_wheel_does_not_change_status(status_control):
    app, page, service, combo = status_control
    point = combo.badge_rect().center()
    wheel = QWheelEvent(QPointF(point), QPointF(combo.mapToGlobal(point.toPoint())),
                        QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                        Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False)
    QApplication.sendEvent(combo, wheel)
    assert service.list_today()[0].status is TaskStatus.TODO
    QTest.mouseClick(combo, Qt.MouseButton.LeftButton, pos=point.toPoint())
    app.processEvents()
    assert combo.menu.isVisible()
    combo.hidePopup()


def test_menu_checks_current_state_when_reopened(status_control):
    app, page, service, combo = status_control
    combo.setCurrentIndex(2)
    page._show_task(service.list_completed()[0])
    combo = page.task_table.cellWidget(0, 0)
    combo.showPopup()
    assert [action.isChecked() for action in combo.menu.actions()] == [False, False, True]
    assert combo.menu.activeAction() is combo.menu.actions()[2]
    combo.hidePopup()


def test_completion_from_qt_string_emits_reminder_signal_once(status_control):
    from types import SimpleNamespace
    from unittest.mock import Mock

    app, page, service, combo = status_control
    completed = Mock()
    page.reminder_coordinator = SimpleNamespace(mark_task_completed=completed)
    combo.showPopup()
    QTest.mouseClick(combo.menu, Qt.MouseButton.LeftButton,
                     pos=combo.menu.actionGeometry(combo.menu.actions()[2]).center())
    assert not service.list_today() and service.list_completed()[0].status is TaskStatus.DONE
    completed.assert_called_once_with()
