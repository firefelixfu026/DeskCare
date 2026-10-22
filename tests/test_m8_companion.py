def _app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_companion_is_hidden_by_default_and_setting_is_opt_in(tmp_path):
    from deskcare.config import ConfigStore
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.consent_service import MonitoringController
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.pages import SettingsPage

    _app()
    repo = UsageRepository(tmp_path / "deskcare.sqlite3")
    page = SettingsPage(ConfigStore(), MonitoringController(FakeActivityProvider()), repository=repo)

    assert page.companion_enabled.isChecked() is False
    assert repo.get_setting("companion_enabled", "false") == "false"
    page.companion_enabled.setChecked(True)
    assert repo.get_setting("companion_enabled") == "true"
    page.companion_enabled.setChecked(False)
    assert repo.get_setting("companion_enabled") == "false"
    page.close()


def test_main_window_integrates_default_hidden_companion(tmp_path):
    from deskcare.config import ConfigStore
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.services.consent_service import MonitoringController
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.main_window import MainWindow

    _app()
    repo = UsageRepository(tmp_path / "deskcare.sqlite3")
    controller = MonitoringController(FakeActivityProvider())
    window = MainWindow(ConfigStore(), controller, repository=repo)
    assert controller.enabled is False
    assert not window.companion.isVisible()
    window.settings_page.companion_enabled.setChecked(True)
    assert window.companion.isVisible()
    window.companion.hide_requested.emit()
    assert not window.companion.isVisible()
    assert repo.get_setting("companion_enabled") == "false"
    window.close()


def test_companion_quick_add_and_persistence(tmp_path):
    from deskcare.domain.types import TaskStatus
    from deskcare.services.task_service import TaskService
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.companion import CompanionWindow

    _app()
    database_path = tmp_path / "deskcare.sqlite3"
    repo = UsageRepository(database_path)
    tasks = TaskService(repo)
    companion = CompanionWindow(tasks, repository=repo)
    companion.task_input.setText("整理实验数据")
    companion.add_task_button.click()
    assert [task.title for task in tasks.list_today()] == ["整理实验数据"]

    assert tasks.list_today()[0].status is TaskStatus.TODO
    reloaded = TaskService(UsageRepository(database_path))
    assert [task.title for task in reloaded.list_today()] == ["整理实验数据"]
    companion.close()


def test_companion_completing_task_requires_explicit_confirmation(tmp_path, monkeypatch):
    from deskcare.domain.types import TaskStatus
    from deskcare.services.task_service import TaskService
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.companion import CompanionWindow

    _app()
    repo = UsageRepository(tmp_path / "deskcare.sqlite3")
    tasks = TaskService(repo)
    tasks.add_manual("完成原型")
    companion = CompanionWindow(tasks, repository=repo)
    from PySide6.QtWidgets import QMessageBox, QPushButton
    row = companion.task_list.itemAt(0).widget()
    finish = [button for button in row.findChildren(QPushButton) if button.text() == '完成…'][0]
    monkeypatch.setattr(QMessageBox, 'exec', lambda box: None)
    finish.click()
    assert tasks.list_today()[0].status is TaskStatus.TODO

    def confirm(box):
        assert box.defaultButton().text() == '先不完成'
        for button in box.buttons():
            if button.text() == '确认完成':
                button.click()
    monkeypatch.setattr(QMessageBox, 'exec', confirm)
    finish.click()
    assert not tasks.list_today() and tasks.list_completed()[0].status is TaskStatus.DONE
    tasks.set_status(tasks.list_completed()[0].id, TaskStatus.TODO)
    assert tasks.list_today()[0].status is TaskStatus.TODO
    companion.close()


def test_companion_mode_selection_is_explicit_and_does_not_touch_monitoring(tmp_path):
    from deskcare.services.consent_service import MonitoringController
    from deskcare.sensors.fake import FakeActivityProvider
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.companion import CompanionWindow

    class Reminder:
        def __init__(self):
            self.mode = None

        def set_mode(self, mode):
            self.mode = mode

        def evaluate(self):
            pass

    _app()
    repo = UsageRepository(tmp_path / "deskcare.sqlite3")
    reminder = Reminder()
    controller = MonitoringController(FakeActivityProvider())
    companion = CompanionWindow(reminder_coordinator=reminder, repository=repo)
    assert companion.mode.count() == 5
    assert companion.mode.view().model().rowCount() == 5
    assert companion.mode.currentData() == "normal"
    assert "QComboBox QAbstractItemView" in companion.styleSheet()
    assert "QComboBox::drop-down" in companion.styleSheet()
    companion.mode.setCurrentIndex(companion.mode.findData("meeting"))
    assert reminder.mode == "meeting"
    assert controller.enabled is False
    companion.close()


def test_companion_docks_as_half_peeking_mascot_and_restores_on_click(tmp_path):
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication, QLabel

    from deskcare.ui.companion import CompanionWindow

    _app()
    companion = CompanionWindow()
    companion.show()
    area = QApplication.primaryScreen().availableGeometry()
    drag_handle = companion.findChild(QLabel, "companionDragHandle")
    assert drag_handle is not None
    assert drag_handle.cursor().shape() == Qt.CursorShape.SizeAllCursor
    companion._begin_drag(QPoint(companion.x() + 20, companion.y() + 20))
    companion._move_drag(QPoint(area.left() + 25, area.top() + 70))
    companion._finish_drag()

    assert companion._peek_side == "left"
    assert companion.content.isHidden()
    assert companion.peek_button.isVisible()
    assert companion.width() == companion.height() == 88
    assert companion.x() == area.left() - 44
    assert not companion.mask().isEmpty()
    assert companion.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    QTest.mouseClick(companion.peek_button, Qt.MouseButton.LeftButton)

    assert companion._peek_side is None
    assert companion.content.isVisible()
    assert companion.width() == 300
    assert companion.mask().isEmpty()
    assert companion.x() == area.left()

    companion._begin_drag(QPoint(companion.x() + 20, companion.y() + 20))
    companion._move_drag(QPoint(area.right() - companion.width() + 25, area.top() + 70))
    companion._finish_drag()
    assert companion._peek_side == "right"
    assert companion.x() == area.right() - 43
    companion.hide()
    companion.close()



def test_companion_has_no_voice_controls_and_removes_only_obsolete_config(tmp_path):
    from PySide6.QtWidgets import QPushButton, QLineEdit
    from deskcare.services.task_service import TaskService
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.companion import CompanionWindow

    _app()
    repo = UsageRepository(tmp_path / "no-voice.sqlite3")
    repo.set_setting("voice_model_path", "old-selected-model")
    tasks = TaskService(repo)
    tasks.add_manual("保留的任务")
    companion = CompanionWindow(tasks, repository=repo)
    assert repo.get_setting("voice_model_path") is None
    assert len(companion.findChildren(QLineEdit)) == 1
    assert not any("语音" in button.text() or "说话" in button.text()
                   for button in companion.findChildren(QPushButton))
    assert not hasattr(companion, "_audio_source")
    assert [task.title for task in tasks.list_today()] == ["保留的任务"]
    companion.close()
