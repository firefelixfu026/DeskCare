import importlib.util

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is required for the M2 dialog smoke test",
)


@pytest.fixture(scope="module", autouse=True)
def _keep_qapplication_alive():
    """Keep the Qt application wrapper alive for the whole UI test module."""
    from PySide6.QtCore import QEvent
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app
    app.closeAllWindows()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(autouse=True)
def _dispose_test_windows(_keep_qapplication_alive):
    """Delete module-owned top-level widgets after each Qt test."""
    from PySide6.QtCore import QEvent

    app = _keep_qapplication_alive
    yield
    for widget in app.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_import_preview_blocks_duplicate_until_user_edits():
    # Keep this test usable without pytest-qt; the dialog has no event loop
    # dependency beyond QApplication.processEvents().
    from PySide6.QtWidgets import QApplication

    from deskcare.importers.text_importer import parse_text_bytes
    from deskcare.ui.task_dialog import ImportPreviewDialog

    app = QApplication.instance() or QApplication([])
    result = parse_text_bytes(b"- same\n- Same\n", "duplicate.md")
    dialog = ImportPreviewDialog(result)
    assert dialog.table.rowCount() == 2
    assert not dialog.confirm.isEnabled()

    dialog.table.item(1, 0).setText("A different task")
    app.processEvents()
    assert dialog.confirm.isEnabled()

    dialog._accept()
    assert [draft.title for draft in dialog.drafts] == ["same", "A different task"]
    dialog.table.insertRow(dialog.table.rowCount())
    drafts, errors = dialog._drafts_from_table()
    assert len(drafts) == 2
    assert errors  # transient/incomplete rows are validation errors, not crashes
    dialog.close()


def test_today_status_combo_is_a_user_action_that_persists(tmp_path):
    from PySide6.QtWidgets import QApplication

    from deskcare.domain.types import TaskStatus
    from deskcare.services.task_service import TaskService
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.pages import TodayPage
    from deskcare.services.consent_service import MonitoringController
    from deskcare.sensors.fake import FakeActivityProvider

    app = QApplication.instance() or QApplication([])
    repository = UsageRepository(tmp_path / "ui.sqlite3")
    service = TaskService(repository)
    task = service.add_manual("手工状态测试")
    controller = MonitoringController(FakeActivityProvider())
    page = TodayPage(controller, service)
    combo = page.task_table.cellWidget(0, 0)
    combo.setCurrentIndex(combo.findData(TaskStatus.DONE))
    app.processEvents()
    assert service.list_today()[0].status is TaskStatus.DONE
    page.close()


def test_today_page_add_edit_delete_handlers_persist_user_changes(tmp_path, monkeypatch):
    from collections import deque

    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    import deskcare.ui.pages as pages_module
    from deskcare.config import ConfigStore
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.consent_service import MonitoringController
    from deskcare.services.task_service import TaskService
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.pages import TodayPage

    QApplication.instance() or QApplication([])
    database_path = tmp_path / "task-ui.sqlite3"
    repository = UsageRepository(database_path)
    service = TaskService(repository)
    responses = deque(
        [
            ("第一次添加", None, 25),
            ("修改后的任务", None, 40),
        ]
    )

    class FormDialog:
        DialogCode = QDialog.DialogCode

        def __init__(self, *_args, **_kwargs):
            self._values = responses.popleft()

        @staticmethod
        def exec():
            return QDialog.DialogCode.Accepted

        def values(self):
            return self._values

    monkeypatch.setattr(pages_module, "TaskFormDialog", FormDialog)
    page = TodayPage(MonitoringController(FakeActivityProvider()), service)
    page._add_manual()
    task = service.list_today()[0]
    assert task.title == "第一次添加"
    assert task.estimated_minutes == 25

    page.task_table.setCurrentCell(0, 0)
    page._edit_selected()
    reloaded = TaskService(UsageRepository(database_path)).list_today()[0]
    assert reloaded.id == task.id
    assert reloaded.title == "修改后的任务"
    assert reloaded.estimated_minutes == 40

    answers = deque(
        [QMessageBox.StandardButton.No, QMessageBox.StandardButton.Yes]
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: answers.popleft(),
    )
    page.task_table.setCurrentCell(0, 0)
    page._delete_selected()
    assert len(service.list_today()) == 1
    page.task_table.setCurrentCell(0, 0)
    page._delete_selected()
    assert service.list_today() == []
    assert TaskService(UsageRepository(database_path)).list_today() == []
    page.hide()
    page.close()


def test_today_import_cancel_does_not_write_but_confirm_persists(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QDialog

    import deskcare.ui.pages as pages_module
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.consent_service import MonitoringController
    from deskcare.services.task_service import TaskService
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.pages import TodayPage

    QApplication.instance() or QApplication([])
    selected_file = tmp_path / "today.md"
    selected_file.write_text("- [ ] 复习数据库\n", encoding="utf-8")
    database_path = tmp_path / "import-ui.sqlite3"
    service = TaskService(UsageRepository(database_path))
    page = TodayPage(MonitoringController(FakeActivityProvider()), service)
    monkeypatch.setattr(
        pages_module.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(selected_file), ""),
    )
    decisions = [QDialog.DialogCode.Rejected, QDialog.DialogCode.Accepted]

    class PreviewDialog:
        DialogCode = QDialog.DialogCode

        def __init__(self, result, *_args, **_kwargs):
            self._result = result

        def exec(self):
            return decisions.pop(0)

        @property
        def drafts(self):
            return self._result.drafts

    monkeypatch.setattr(pages_module, "ImportPreviewDialog", PreviewDialog)
    page._import_file()
    assert service.list_today() == []
    assert page.task_table.rowCount() == 0

    page._import_file()
    imported = TaskService(UsageRepository(database_path)).list_today()
    assert [task.title for task in imported] == ["复习数据库"]
    assert imported[0].source == "today.md"
    assert page.task_table.rowCount() == 1
    page.hide()
    page.close()


def test_import_read_error_is_explained_without_changing_tasks(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    import deskcare.ui.pages as pages_module
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.consent_service import MonitoringController
    from deskcare.services.task_service import TaskService
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.pages import TodayPage

    QApplication.instance() or QApplication([])
    service = TaskService(UsageRepository(tmp_path / "read-error.sqlite3"))
    before = service.add_manual("原有任务")
    page = TodayPage(MonitoringController(FakeActivityProvider()), service)
    monkeypatch.setattr(
        pages_module.QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: ("missing.csv", ""),
    )
    monkeypatch.setattr(
        pages_module,
        "parse_selected_file",
        lambda _path: (_ for _ in ()).throw(OSError("file disappeared")),
    )
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_args: warnings.append(_args[2]),
    )

    page._import_file()
    assert [task.id for task in service.list_today()] == [before.id]
    assert "原有任务没有改动" in warnings[0]
    page.close()


def test_report_export_failure_shows_plain_language_message(tmp_path, monkeypatch):
    from PySide6.QtWidgets import QApplication, QMessageBox

    import deskcare.ui.pages as pages_module
    from deskcare.ui.pages import ReportsPage

    QApplication.instance() or QApplication([])

    class Controller:
        @staticmethod
        def subscribe(_listener):
            return None

    class ReportService:
        @staticmethod
        def render(_period):
            return {
                "data_quality": {
                    "activity_monitoring_enabled": False,
                    "wellness_opt_in": False,
                }
            }, "小结"

        @staticmethod
        def export_markdown(*_args):
            raise OSError("access denied")

    page = ReportsPage(Controller(), report_service=ReportService())
    monkeypatch.setattr(
        pages_module.QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: ("locked/report.md", ""),
    )
    warnings = []
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_args: warnings.append(_args[2]),
    )

    page._export_report()
    assert warnings and "无法写入" in warnings[0]
    page.close()
