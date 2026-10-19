from datetime import date, timedelta

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QImage, QMouseEvent, QRegion
from PySide6.QtWidgets import QApplication

from deskcare.config import ConfigStore
from deskcare.domain.types import TaskStatus, WellnessLevel
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.bodylog_service import BodyLogService
from deskcare.services.consent_service import MonitoringController
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.companion import CompanionWindow
from deskcare.ui.main_window import MainWindow
from deskcare.ui.mascot import MascotSurface, VARIANTS


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def companion(app, tmp_path):
    repo = UsageRepository(tmp_path / "mascot.sqlite3")
    bodylog = BodyLogService(repo)
    tasks = TaskService(repo)
    window = CompanionWindow(tasks, repository=repo, bodylog_service=bodylog)
    yield window, repo, bodylog, tasks
    window._day_timer.stop()
    window.hide()
    window.close()


def send_mouse(widget, kind, local, global_position, button, buttons):
    event = QMouseEvent(kind, QPointF(local), QPointF(global_position), button, buttons,
                        Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(widget, event)


def test_style_switch_is_persistent_and_does_not_enable_visibility_or_monitoring(app, tmp_path):
    repo = UsageRepository(tmp_path / "switch.sqlite3")
    controller = MonitoringController(FakeActivityProvider())
    window = MainWindow(ConfigStore(), controller, repository=repo)
    combo = window.settings_page.companion_style
    combo.setCurrentIndex(combo.findData("mascot"))
    assert window.companion.presentation == "mascot"
    assert repo.get_setting("companion_style") == "mascot"
    assert not window.companion.isVisible()
    assert not controller.enabled
    window.companion.set_presentation("panel")  # also used by the mascot context menu
    assert combo.currentData() == "panel"
    assert repo.get_setting("companion_style") == "panel"
    window.companion.set_presentation("mascot")
    reloaded = CompanionWindow(repository=UsageRepository(repo.path))
    assert reloaded.presentation == "mascot"
    reloaded.hide()
    reloaded.close()
    window._allow_close = True
    window.close()


@pytest.mark.parametrize("level, artwork", [
    (WellnessLevel.COMFORTABLE, "comfortable"),
    (WellnessLevel.SOME_DISCOMFORT, "uncomfortable"),
    (WellnessLevel.PREFER_NOT_TO_SAY, "skip"),
])
def test_three_images_follow_explicit_today_self_report(companion, level, artwork):
    window, repo, bodylog, _tasks = companion
    window.set_presentation("mascot")
    bodylog.set_enabled(True)
    bodylog.save_today(level)
    assert window.mascot.variant == artwork
    assert repo.wellness_for_day(date.today()).comfort_level is level
    assert "今天自报" in window.mascot.toolTip()
    bodylog.delete_today()
    assert window.mascot.variant == "skip"
    assert "未记录" in window.mascot.toolTip()
    assert repo.wellness_for_day(date.today()) is None


def test_unauthorized_history_and_yesterdays_state_are_not_reused(companion, monkeypatch):
    window, repo, bodylog, _tasks = companion
    repo.upsert_wellness_entry(date.today(), WellnessLevel.COMFORTABLE)

    def forbidden(*args):
        raise AssertionError("No wellness read without independent consent")

    original = repo.wellness_for_day
    monkeypatch.setattr(repo, "wellness_for_day", forbidden)
    window._sync_wellness(False)
    window.set_presentation("mascot")
    assert window.mascot.variant == "skip"
    assert "未记录" in window.mascot.toolTip()
    monkeypatch.setattr(repo, "wellness_for_day", original)
    bodylog.set_enabled(True)
    assert window.mascot.variant == "comfortable"
    bodylog.set_enabled(False)
    assert window.mascot.variant == "skip"
    repo.delete_wellness_entry(date.today())
    repo.upsert_wellness_entry(date.today() - timedelta(days=1), WellnessLevel.COMFORTABLE)
    bodylog.set_enabled(True)
    assert window.mascot.variant == "skip"
    assert repo.wellness_for_day(date.today()) is None


def test_mascot_click_opens_existing_task_controls_and_returns_to_art(companion, app):
    window, _repo, _bodylog, tasks = companion
    window.set_presentation("mascot")
    window.show()
    app.processEvents()
    # A click near the screen edge must not accidentally become a dock/drag.
    local = window.mascot.rect().center()
    global_position = window.mascot.mapToGlobal(local)
    send_mouse(window.mascot, QEvent.Type.MouseButtonPress, local, global_position,
               Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    send_mouse(window.mascot, QEvent.Type.MouseButtonRelease, local, global_position,
               Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert window.content.isVisible()
    assert window.back_to_mascot.isVisible()
    window.task_input.setText("虚构吉祥物任务")
    window.add_task_button.click()
    assert tasks.list_today()[0].title == "虚构吉祥物任务"
    window.task_list.itemAt(0).widget().setChecked(True)
    assert tasks.list_today()[0].status is TaskStatus.DONE
    window.back_to_mascot.click()
    assert window.mascot.isVisible()
    assert not window.content.isVisible()
    assert window.width() == 210


def test_drag_uses_dedicated_picture_then_restores_selected_state(companion, app):
    window, _repo, bodylog, _tasks = companion
    bodylog.set_enabled(True)
    bodylog.save_today(WellnessLevel.COMFORTABLE)
    window.set_presentation("mascot")
    area = QApplication.primaryScreen().availableGeometry()
    window.move(area.left() + (area.width() - window.width()) // 2 - 30,
                area.top() + (area.height() - window.height()) // 2 - 15)
    window.show()
    app.processEvents()
    local = window.mascot.rect().center()
    start = window.mascot.mapToGlobal(local)
    end = start + local.__class__(60, 30)
    send_mouse(window.mascot, QEvent.Type.MouseButtonPress, local, start,
               Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton)
    send_mouse(window.mascot, QEvent.Type.MouseMove, local, end,
               Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton)
    assert window.mascot.variant == "drag"
    bodylog.set_enabled(False)  # withdrawing consent during drag cannot restore stale state
    send_mouse(window.mascot, QEvent.Type.MouseButtonRelease, local, end,
               Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton)
    assert window.mascot.variant == "skip"
    assert not window._mascot_dragged
    assert window._drag_offset is None


@pytest.mark.parametrize("side", ["left", "right"])
def test_supplied_side_art_docks_inside_correct_edge_and_expands(companion, app, side):
    window, _repo, bodylog, _tasks = companion
    bodylog.set_enabled(True)
    bodylog.save_today(WellnessLevel.SOME_DISCOMFORT)
    window.set_presentation("mascot")
    window.show()
    app.processEvents()
    area = QApplication.primaryScreen().availableGeometry()
    window._dock_to_edge(side, area)
    app.processEvents()
    assert window.mascot.variant == "peek-" + side
    assert window._peek_side == side
    assert window.x() == (area.left() if side == "left" else area.right() - 139)
    assert not window.mask().isEmpty()
    window._expand_from_edge()
    app.processEvents()
    assert window._peek_side is None
    assert window.mascot.variant == "uncomfortable"
    assert window.width() == 210
    window.set_presentation("panel")
    assert window.mask().isEmpty()


def test_all_six_packaged_artworks_have_alpha_and_nonrectangular_hit_regions(app):
    surface = MascotSurface()
    surface.resize(210, 300)
    for variant in sorted(VARIANTS):
        surface.set_variant(variant)
        assert surface.asset_available, variant
        source = surface._load(variant)
        assert source.hasAlphaChannel(), variant
        image = source.toImage().convertToFormat(QImage.Format.Format_RGBA8888)
        alpha = bytes(image.constBits())[3::4]
        assert alpha.count(0) > len(alpha) * .05, variant
        assert alpha.count(255) > 100, variant
        assert surface._image_rect.height() >= 295, variant  # no square-canvas padding shrink
        assert surface.hit_region != QRegion(surface.rect()), variant
        assert not surface.hit_region.isEmpty(), variant
    surface.close()


def test_new_day_does_not_continue_displaying_yesterdays_state(companion, monkeypatch):
    import deskcare.ui.companion as module

    window, repo, bodylog, _tasks = companion
    bodylog.set_enabled(True)
    bodylog.save_today(WellnessLevel.COMFORTABLE)
    window.set_presentation("mascot")
    tomorrow = date.today() + timedelta(days=1)

    class NextDay(date):
        @classmethod
        def today(cls):
            return tomorrow

    # The bodylog service also obtains its local day through its own module.
    import deskcare.services.bodylog_service as service_module
    monkeypatch.setattr(module, "date", NextDay)
    monkeypatch.setattr(service_module, "date", NextDay)
    window._check_day()
    assert window.mascot.variant == "skip"
    assert "未记录" in window.mascot.toolTip()
    assert repo.wellness_for_day(tomorrow) is None


def test_hiding_during_drag_clears_temporary_pose(companion, app):
    window, _repo, _bodylog, _tasks = companion
    window.set_presentation("mascot")
    window.show()
    app.processEvents()
    window._mascot_dragged = True
    window._mascot_press = window.pos()
    window.mascot.set_variant("drag")
    window.hide()
    assert window.mascot.variant == "skip"
    assert window._mascot_press is None
    assert not window._mascot_dragged
