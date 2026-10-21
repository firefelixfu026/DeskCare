from datetime import datetime, timedelta, timezone

import pytest
from PySide6.QtCore import QEvent, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from deskcare.domain.break_policy import BreakPolicyConfig
from deskcare.services.personalization_service import ReminderPersonalizationService
from deskcare.storage.database import UsageRepository
from deskcare.ui.choices import SoftComboBox, SegmentedChoice
from deskcare.ui.reminder_popup import ReminderPopup
from deskcare.ui.theme import apply_theme
from test_m6_personalization import _add_feedback


@pytest.fixture(scope="module", autouse=True)
def app():
    instance = QApplication.instance() or QApplication([])
    apply_theme(instance)
    yield instance
    instance.processEvents()


@pytest.fixture
def choices(app):
    combo = SoftComboBox()
    for value in range(5):
        combo.addItem(f"选项 {value}", value)
    combo.resize(200, 40)
    combo.show()
    app.processEvents()
    yield combo
    combo.hidePopup()
    combo.close()
    combo.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


def test_popup_is_rounded_translucent_and_opening_is_not_selection(choices, app):
    changes = []
    choices.currentIndexChanged.connect(changes.append)
    choices.showPopup()
    app.processEvents()
    popup = choices._popup
    assert popup.isVisible()
    assert popup.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert popup.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert popup.grab().toImage().pixelColor(0, 0).alpha() == 0
    assert choices.currentData() == 0 and not changes


def test_clicking_popup_commits_once_and_closes(choices, app):
    changes = []
    choices.currentIndexChanged.connect(changes.append)
    choices.showPopup()
    app.processEvents()
    view = choices.view()
    target = view.model().index(3, 0)
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=view.visualRect(target).center())
    assert choices.currentData() == 3 and changes == [3]
    assert not choices._popup.isVisible()


def test_keyboard_highlight_cancel_and_confirm(choices, app):
    QTest.keyClick(choices, Qt.Key.Key_Space)
    app.processEvents()
    QTest.keyClick(choices.view(), Qt.Key.Key_Down)
    assert choices.currentIndex() == 0
    QTest.keyClick(choices.view(), Qt.Key.Key_Escape)
    assert not choices._popup.isVisible() and choices.currentIndex() == 0
    choices.showPopup()
    QTest.keyClick(choices.view(), Qt.Key.Key_Down)
    QTest.keyClick(choices.view(), Qt.Key.Key_Return)
    assert choices.currentIndex() == 1


def test_long_list_scrolls_and_stays_inside_screen(choices, app):
    choices.clear()
    choices.addItems([f"历史日期 {i}" for i in range(100)])
    choices.setCurrentIndex(99)
    choices.showPopup()
    app.processEvents()
    assert choices.view().verticalScrollBar().maximum() > 0
    assert choices.screen().availableGeometry().contains(choices._popup.geometry())
    assert choices.view().viewport().rect().intersects(choices.view().visualRect(choices.model().index(99, 0)))


def test_disabled_rows_cannot_be_committed_and_model_reset_closes(choices):
    choices.model().item(1).setEnabled(False)
    choices.showPopup()
    choices._popup.choose(choices.model().index(1, 0))
    assert choices.currentIndex() == 0
    choices.clear()
    assert not choices._popup.isVisible()


def test_disabling_or_hiding_owner_closes_popup(choices):
    choices.showPopup()
    choices.setEnabled(False)
    assert not choices._popup.isVisible()
    choices.setEnabled(True)
    choices.showPopup()
    choices.hide()
    assert not choices._popup.isVisible()


def test_segments_are_real_buttons_and_sync_while_signals_are_blocked(app):
    widget = SegmentedChoice()
    widget.addItem("普通工作", "normal")
    widget.addItem("专注模式", "focus")
    widget.addItem("会议中", "meeting")
    widget.resize(widget.sizeHint())
    widget.show()
    app.processEvents()
    changes = []
    widget.currentIndexChanged.connect(changes.append)
    QTest.mouseClick(widget.buttons[1], Qt.MouseButton.LeftButton)
    assert widget.currentData() == "focus" and changes == [1]
    widget.blockSignals(True)
    widget.setCurrentIndex(2)
    widget.blockSignals(False)
    assert [button.isChecked() for button in widget.buttons] == [False, False, True]
    assert changes == [1]
    QTest.keyClick(widget, Qt.Key.Key_Left)
    assert widget.currentData() == "focus"
    widget.close()
    widget.deleteLater()


def test_segments_interrupted_animation_starts_at_current_frame(app):
    widget = SegmentedChoice()
    widget.addItems(["普通", "专注", "会议"])
    widget.resize(widget.sizeHint())
    widget.show()
    app.processEvents()
    widget.setCurrentIndex(1)
    widget.animation.setCurrentTime(70)
    previous = widget._pill
    widget.setCurrentIndex(2)
    assert widget.animation.startValue() == previous
    widget.animation.stop()
    widget.close()
    widget.deleteLater()


@pytest.mark.parametrize("code", ["BREAK_NOW", "SNOOZE_10_MIN", "SKIP", "BAD_TIMING"])
def test_desktop_popup_exposes_all_feedback_and_preview_never_records(code, app):
    popup = ReminderPopup()
    events = []
    popup.response_requested.connect(events.append)
    assert set(popup.buttons) == {"BREAK_NOW", "SNOOZE_10_MIN", "SKIP", "BAD_TIMING"}
    popup.present(preview=True)
    popup.buttons[code].click()
    assert not events
    popup.present(preview=False)
    popup.buttons[code].click()
    assert events == [code]
    assert popup.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    popup.close()
    popup.deleteLater()


def test_three_snoozes_suggest_review_without_becoming_bad_timing(tmp_path):
    repo = UsageRepository(tmp_path / "fictional.sqlite3")
    for i in range(3):
        _add_feedback(repo, i, "SNOOZE_10_MIN")
    service = ReminderPersonalizationService(repo, initially_enabled=True)
    result = service.snapshot
    assert result.snooze_count == 3 and result.consecutive_snoozes == 3
    assert result.bad_timing_count == 0 and result.suggested_minutes == 50
    assert "连续 3 次" in result.explanation
    assert not result.applied and service.effective_config(BreakPolicyConfig(), "normal").break_candidate_minutes == 40


def test_one_snooze_or_interrupted_streak_never_triggers_review(tmp_path):
    repo = UsageRepository(tmp_path / "fictional.sqlite3")
    for i, response in enumerate(["SNOOZE_10_MIN", "SNOOZE_10_MIN", "SKIP", "SNOOZE_10_MIN"]):
        _add_feedback(repo, i, response)
    result = ReminderPersonalizationService(repo, initially_enabled=True).snapshot
    assert result.snooze_count == 3 and result.skipped_count == 1
    assert result.consecutive_snoozes == 1 and result.bad_timing_count == 0
    assert result.suggested_minutes is None


def test_snooze_review_is_context_specific_opt_in_and_acknowledged(tmp_path):
    repo = UsageRepository(tmp_path / "fictional.sqlite3")
    for i in range(3):
        _add_feedback(repo, i, "SNOOZE_10_MIN")
    service = ReminderPersonalizationService(repo)
    assert service.snapshot.snooze_count == 3 and service.snapshot.suggested_minutes is None
    service.set_enabled(True)
    assert service.snapshot.suggested_minutes == 50
    assert service.refresh("focus").suggested_minutes is None
    service.refresh("normal")
    service.dismiss_current_suggestion()
    assert service.snapshot.suggested_minutes is None
    for i in range(3, 7):
        _add_feedback(repo, i, "SNOOZE_10_MIN")
    assert service.refresh().suggested_minutes is None
    _add_feedback(repo, 7, "SNOOZE_10_MIN")
    assert service.refresh().suggested_minutes == 50
    demo = ReminderPersonalizationService(repo, initially_enabled=True, data_is_demo=True)
    assert not demo.snapshot.eligible and demo.snapshot.snooze_count == 0


def test_snooze_short_interval_and_cap_are_bounded(tmp_path):
    repo = UsageRepository(tmp_path / "fictional.sqlite3")
    for i in range(3):
        _add_feedback(repo, i, "SNOOZE_10_MIN")
    small = ReminderPersonalizationService(repo, initially_enabled=True, base_candidate_minutes=1)
    assert small.snapshot.suggested_minutes == 40
    capped = ReminderPersonalizationService(repo, initially_enabled=True, base_candidate_minutes=180)
    assert capped.snapshot.suggested_minutes is None


@pytest.mark.parametrize("code,bad,snoozed", [("BAD_TIMING", 1, 0), ("SNOOZE_10_MIN", 0, 1)])
def test_desktop_click_reaches_database_and_separate_feedback_counters(tmp_path, app, code, bad, snoozed):
    from test_ui7_reminders_cloud import services, seed_ready
    repo, controller, collector, tasks, coordinator = services(tmp_path)
    personalization = ReminderPersonalizationService(repo, initially_enabled=True)
    coordinator.personalization_service = personalization
    now = seed_ready(collector)
    assert coordinator.evaluate(now=now, is_recent_switch=True).visible
    popup = ReminderPopup()
    popup.response_requested.connect(coordinator.respond)
    popup.present(preview=False)
    app.processEvents()
    QTest.mouseClick(popup.buttons[code], Qt.MouseButton.LeftButton)
    assert repo.recent_reminder_events(responded_only=True)[0].response == code
    assert personalization.snapshot.bad_timing_count == bad
    assert personalization.snapshot.snooze_count == snoozed
    assert not coordinator.snapshot.visible
    popup.close()
    popup.deleteLater()
