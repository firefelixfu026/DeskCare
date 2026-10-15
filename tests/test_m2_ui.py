import importlib.util

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is required for the M2 dialog smoke test",
)


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
