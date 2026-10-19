"""Compact task rows remain usable at normal and scaled logical sizes."""

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import QApplication

from deskcare.domain.types import TaskStatus
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.consent_service import MonitoringController
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.pages import TodayPage
from deskcare.ui.theme import apply_theme


@pytest.fixture
def task_page(tmp_path):
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    repository = UsageRepository(tmp_path / "tasks.sqlite3")
    service = TaskService(repository)
    first = service.add_manual("学习 ads")
    second = service.add_manual("整理资料" * 35, estimated_minutes=30)
    page = TodayPage(MonitoringController(FakeActivityProvider()), service)
    page.resize(840, 580)
    page.show()
    app.processEvents()
    yield app, page, service, first, second
    page.close()
    page.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_compact_rows_and_readable_units(task_page):
    app, page, service, first, second = task_page
    table = page.task_table
    assert table.verticalHeader().isHidden()
    assert not table.showGrid()
    for row in range(table.rowCount()):
        combo = table.cellWidget(row, 0)
        assert combo.objectName() == "taskStatus"
        assert table.rowHeight(row) == 56
        assert combo.height() <= table.rowHeight(row)
        assert combo.width() <= table.columnWidth(0)
    assert table.item(0, 2).text() == "—"
    assert table.item(1, 3).text() == "30 分钟"
    assert table.item(1, 1).toolTip() == second.title


@pytest.mark.parametrize("state,tone", [(TaskStatus.TODO, "todo"), (TaskStatus.DOING, "doing"), (TaskStatus.DONE, "done")])
def test_status_pill_persists_and_keeps_target(task_page, state, tone):
    app, page, service, first, second = task_page
    page.task_table.setCurrentCell(1, 1)
    combo = page.task_table.cellWidget(0, 0)
    combo.setCurrentIndex(combo.findData(state))
    app.processEvents()
    if state is TaskStatus.TODO:  # no change signal for the already-selected value
        service.set_status(first.id, state)
        expected = second.id
    else:
        expected = first.id
    assert service.list_today()[0].status is state
    assert page.task_table.cellWidget(0, 0).property("tone") == tone
    item = page.task_table.item(page.task_table.currentRow(), 1)
    assert item.data(Qt.ItemDataRole.UserRole) == expected


def test_refresh_preserves_selected_identity(task_page):
    app, page, service, first, second = task_page
    page.task_table.setCurrentCell(1, 1)
    service.add_manual("新任务")
    assert page.task_table.item(page.task_table.currentRow(), 1).data(Qt.ItemDataRole.UserRole) == second.id


def test_double_click_reuses_edit_flow(task_page, monkeypatch):
    app, page, service, first, second = task_page
    calls = []
    monkeypatch.setattr(page, "_edit_selected", lambda: calls.append(True))
    page.task_table.itemDoubleClicked.emit(page.task_table.item(0, 1))
    assert calls == [True]
