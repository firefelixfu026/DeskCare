def test_main_surfaces_use_plain_chinese_and_hide_technical_ai_setup_by_default(tmp_path):
    from PySide6.QtWidgets import QApplication

    from deskcare.config import ConfigStore
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.consent_service import MonitoringController
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.main_window import MainWindow

    QApplication.instance() or QApplication([])
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    window = MainWindow(
        ConfigStore(), MonitoringController(FakeActivityProvider()), repository=repository
    )
    settings = window.settings_page
    assert "电脑使用情况" in window.navigation.item(1).text()
    assert "BodyLog" not in settings.health.text()
    assert "Local LLM" not in settings.local_ai.text()
    assert settings.local_ai_config.isHidden()
    assert settings.cloud_advanced_frame.isHidden()

    settings.local_ai_advanced_button.setChecked(True)
    settings.cloud_advanced_button.setChecked(True)
    assert not settings.local_ai_config.isHidden()
    assert not settings.cloud_advanced_frame.isHidden()
    window._allow_close = True
    window.close()


def test_task_import_ai_actions_are_named_for_regular_users():
    from PySide6.QtWidgets import QApplication

    from deskcare.domain.types import TaskDraft
    from deskcare.importers.base import ImportResult
    from deskcare.ui.task_dialog import ImportPreviewDialog

    QApplication.instance() or QApplication([])
    result = ImportResult("tasks.txt", (TaskDraft("准备汇报", None, None, 1, ()),), ())
    dialog = ImportPreviewDialog(result, ai_parser=lambda: result, cloud_parser=lambda _request: result)
    assert dialog.ai_button.text() == "本机 AI 帮我整理"
    assert dialog.cloud_button.text() == "联网 AI 帮我整理"
    dialog.close()
