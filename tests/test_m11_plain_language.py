def test_main_surfaces_use_plain_chinese_and_hide_technical_ai_setup_by_default(tmp_path):
    from PySide6.QtWidgets import QApplication

    from deskcare.config import ConfigStore
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.consent_service import MonitoringController
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.main_window import MainWindow

    QApplication.instance() or QApplication([])
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    repository.set_setting("demo_mode", "true")
    repository.set_setting("demo_scenario", "true")
    window = MainWindow(
        ConfigStore(), MonitoringController(FakeActivityProvider()), repository=repository
    )
    assert not window.demo_banner.isHidden()
    assert "虚构示例" in window.demo_banner.text()
    assert "预先生成" in window.demo_banner.text()
    settings = window.settings_page
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSizePolicy

    assert settings.settings_scroll.alignment() & Qt.AlignmentFlag.AlignHCenter
    assert settings.settings_scroll.widget().maximumWidth() == 920
    assert (
        settings.cloud_advanced_button.sizePolicy().horizontalPolicy()
        == QSizePolicy.Policy.Fixed
    )
    assert (
        settings.clear_all_button.sizePolicy().horizontalPolicy()
        == QSizePolicy.Policy.Fixed
    )
    assert "电脑使用情况" in window.navigation.item(1).toolTip()
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


def test_reminder_does_not_show_internal_reason_codes_to_users(tmp_path):
    from PySide6.QtWidgets import QApplication

    from deskcare.domain.types import BreakAction, PolicyDecision
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.consent_service import MonitoringController
    from deskcare.services.reminder_service import ReminderSnapshot
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.pages import TodayPage

    QApplication.instance() or QApplication([])
    repository = UsageRepository(tmp_path / "plain-reminder.sqlite3")
    page = TodayPage(
        MonitoringController(FakeActivityProvider()),
        repository=repository,
    )
    page._sync_reminder(
        ReminderSnapshot(
            PolicyDecision(
                BreakAction.SOFT_NOTIFY,
                ("FUTURE_INTERNAL_RULE_CODE",),
                "可以考虑休息一下。",
                60,
            ),
            visible=True,
        )
    )
    text = page.reminder_reason.text()
    assert "FUTURE_INTERNAL_RULE_CODE" not in text
    assert "符合温和提醒条件" in text
    page.close()
