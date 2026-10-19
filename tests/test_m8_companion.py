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


def test_companion_quick_add_and_manual_transcript_confirmation(tmp_path):
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

    companion.transcript.setText("准备比赛演示")
    assert [task.title for task in tasks.list_today()] == ["整理实验数据"]
    companion._confirm_transcript()
    created = tasks.list_today()
    assert [task.title for task in created] == ["整理实验数据", "准备比赛演示"]
    assert all(task.status is TaskStatus.TODO for task in created)
    reloaded = TaskService(UsageRepository(database_path))
    assert [task.title for task in reloaded.list_today()] == ["整理实验数据", "准备比赛演示"]
    companion.close()


def test_transcription_result_is_a_draft_until_user_confirms(tmp_path):
    from deskcare.services.task_service import TaskService
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.companion import CompanionWindow

    _app()
    repo = UsageRepository(tmp_path / "voice-draft.sqlite3")
    tasks = TaskService(repo)
    companion = CompanionWindow(tasks, repository=repo)

    companion._on_transcribed("准备周会材料", "")
    assert companion.transcript.text() == "准备周会材料"
    assert tasks.list_today() == []
    assert "草稿" in companion.recording_hint.text()

    companion._confirm_transcript()
    assert [task.title for task in tasks.list_today()] == ["准备周会材料"]
    assert companion.transcript.text() == ""

    companion.transcript.setText("")
    companion._on_transcribed("", "麦克风暂不可用")
    assert tasks.list_today()[0].title == "准备周会材料"
    assert "没有识别成功" in companion.recording_hint.text()
    companion.close()


def test_companion_checking_task_updates_only_local_status(tmp_path):
    from deskcare.domain.types import TaskStatus
    from deskcare.services.task_service import TaskService
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.companion import CompanionWindow

    _app()
    repo = UsageRepository(tmp_path / "deskcare.sqlite3")
    tasks = TaskService(repo)
    tasks.add_manual("完成原型")
    companion = CompanionWindow(tasks, repository=repo)
    checkbox = companion.task_list.itemAt(0).widget()
    checkbox.setChecked(True)
    assert tasks.list_today()[0].status is TaskStatus.DONE
    checkbox.setChecked(False)
    assert tasks.list_today()[0].status is TaskStatus.TODO
    companion.close()


def test_voice_adapter_requires_a_local_model_and_never_falls_back_to_network(tmp_path):
    from deskcare.voice.vosk_adapter import transcribe_pcm

    try:
        transcribe_pcm(str(tmp_path / "missing-model"), b"\x00\x00")
    except ValueError as exc:
        assert "Vosk" in str(exc)
    else:
        raise AssertionError("missing local model must fail closed")


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
    assert "color:#24312E" in companion.styleSheet()
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


def test_companion_says_why_voice_input_is_not_ready_and_manual_add_still_works(tmp_path, monkeypatch):
    import deskcare.ui.companion as companion_module
    from deskcare.services.task_service import TaskService
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.companion import CompanionWindow

    _app()
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    tasks = TaskService(repository)
    companion = CompanionWindow(tasks, repository=repository)
    monkeypatch.setattr(companion_module.importlib.util, "find_spec", lambda _name: object())
    companion.voice_button.pressed.emit()
    assert "还没有设置语音包" in companion.recording_hint.text()
    companion.task_input.setText("我仍可手动添加")
    companion.add_task_button.click()
    assert [task.title for task in tasks.list_today()] == ["我仍可手动添加"]
    companion.close()


def test_press_record_release_transcribes_to_draft_before_task_confirmation(tmp_path, monkeypatch):
    import deskcare.ui.companion as companion_module
    from PySide6.QtCore import QThread
    from PySide6.QtMultimedia import QAudioFormat
    from deskcare.services.task_service import TaskService
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.companion import CompanionWindow

    app = _app()

    class FakeSignal:
        def connect(self, _callback):
            pass

    class FakeFormat:
        def sampleRate(self):
            return 16000

        def channelCount(self):
            return 1

        def sampleFormat(self):
            return QAudioFormat.SampleFormat.Int16

        def bytesPerFrame(self):
            return 2

    class FakeInputDevice:
        def isNull(self):
            return False

        def preferredFormat(self):
            return FakeFormat()

    class FakeIODevice:
        def __init__(self):
            self.buffer = b"\x01\x00" * 64

        def bytesAvailable(self):
            return len(self.buffer)

        def read(self, size):
            chunk, self.buffer = self.buffer[:size], self.buffer[size:]
            return chunk

    class FakeAudioSource:
        def __init__(self, _device, _audio_format, _parent):
            self.stateChanged = FakeSignal()
            self.device = FakeIODevice()
            self.stopped = False
            self.deleted = False

        def start(self):
            return self.device

        def stop(self):
            self.stopped = True

        def deleteLater(self):
            self.deleted = True

    monkeypatch.setattr(
        companion_module.QMediaDevices,
        "defaultAudioInput",
        staticmethod(lambda: FakeInputDevice()),
    )
    monkeypatch.setattr(companion_module.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(companion_module, "QAudioSource", FakeAudioSource)
    transcription_calls = []

    def transcribe(_model, pcm, sample_rate=16000):
        transcription_calls.append((len(pcm), sample_rate))
        return "语音生成的任务草稿" if pcm and sample_rate == 16000 else ""

    monkeypatch.setattr(companion_module, "transcribe_pcm", transcribe)

    repository = UsageRepository(tmp_path / "voice-lifecycle.sqlite3")
    tasks = TaskService(repository)
    companion = CompanionWindow(tasks, repository=repository)
    companion.model_path = str(tmp_path)

    companion._start_recording()
    source = companion._audio_source
    assert source is not None
    assert companion._audio_timer.isActive()
    assert "正在录音" in companion.recording_hint.text()

    companion._read_audio()
    assert companion._audio_buffer
    companion._stop_recording()

    worker_thread = companion._voice_thread
    assert companion._voice_worker is not None
    assert worker_thread is not None
    for _ in range(600):
        app.processEvents()
        if companion._voice_thread is None and companion.transcript.text():
            break
        QThread.msleep(5)
    app.processEvents()
    assert companion._voice_thread is None, f"voice thread did not finish: {companion.recording_hint.text()}"
    assert companion._voice_worker is None

    assert source.stopped and source.deleted
    assert not companion._audio_buffer
    assert companion._audio_source is None
    assert companion._audio_device is None
    assert transcription_calls == [(128, 16000)], companion.recording_hint.text()
    assert companion.transcript.text() == "语音生成的任务草稿"
    assert tasks.list_today() == []

    companion._confirm_transcript()
    assert [task.title for task in tasks.list_today()] == ["语音生成的任务草稿"]
    companion.close()


def test_microphone_error_discards_buffer_and_does_not_create_task(tmp_path, monkeypatch):
    import deskcare.ui.companion as companion_module
    from PySide6.QtMultimedia import QAudioFormat
    from deskcare.services.task_service import TaskService
    from deskcare.storage.database import UsageRepository
    from deskcare.ui.companion import CompanionWindow

    _app()

    class FakeFormat:
        def sampleRate(self):
            return 16000

        def channelCount(self):
            return 1

        def sampleFormat(self):
            return QAudioFormat.SampleFormat.Int16

        def bytesPerFrame(self):
            return 2

    class FakeInputDevice:
        def isNull(self):
            return False

        def preferredFormat(self):
            return FakeFormat()

    class FakeIODevice:
        def bytesAvailable(self):
            return 0

        def read(self, _size):
            return b""

    class FakeSignal:
        def connect(self, _callback):
            pass

    class FakeAudioSource:
        class Error:
            NoError = 0
            OpenError = 1

        def __init__(self, _device, _audio_format, _parent):
            self.stateChanged = FakeSignal()
            self.device = FakeIODevice()
            self.stopped = False
            self.deleted = False

        def start(self):
            return self.device

        def error(self):
            return self.Error.OpenError

        def stop(self):
            self.stopped = True

        def deleteLater(self):
            self.deleted = True

    monkeypatch.setattr(
        companion_module.QMediaDevices,
        "defaultAudioInput",
        staticmethod(lambda: FakeInputDevice()),
    )
    monkeypatch.setattr(companion_module.importlib.util, "find_spec", lambda _name: object())
    monkeypatch.setattr(companion_module, "QAudioSource", FakeAudioSource)

    repository = UsageRepository(tmp_path / "voice-device-error.sqlite3")
    tasks = TaskService(repository)
    companion = CompanionWindow(tasks, repository=repository)
    companion.model_path = str(tmp_path)
    companion._start_recording()
    source = companion._audio_source
    assert source is not None
    assert companion._audio_timer.isActive()

    companion._audio_buffer.extend(b"private audio bytes")
    companion._audio_state_changed(None)

    assert source.stopped and source.deleted
    assert companion._audio_source is None
    assert companion._audio_device is None
    assert companion._audio_format is None
    assert not companion._audio_buffer
    assert not companion._audio_timer.isActive()
    assert companion.voice_button.isEnabled()
    assert "没有任务被修改" in companion.recording_hint.text()
    assert tasks.list_today() == []
    companion.close()
