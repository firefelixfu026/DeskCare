"""Headless regression coverage for screenshot-driven UI2 changes."""

from datetime import date, timedelta

import pytest
from PySide6.QtCore import QAbstractAnimation
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QDialogButtonBox, QMessageBox

from deskcare.domain.types import WellnessLevel
from deskcare.services.bodylog_service import BodyLogService
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.consent_service import MonitoringController
from deskcare.services.report_engine import LocalReportService
from deskcare.storage.database import UsageRepository
from deskcare.ui.charts import UsageChart
from deskcare.ui.pages import ReportsPage
from deskcare.ui.task_dialog import TaskFormDialog
from deskcare.ui.theme import apply_theme


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def chart(app):
    widget = UsageChart("donut")
    widget.resize(480, 280)
    widget.show()
    app.processEvents()
    yield widget
    widget.animation.stop()
    widget.close()


def values(chart):
    return {entry.label: entry.seconds for entry in chart.displayed_entries}


def test_live_animation_starts_from_previous_frame_and_can_be_interrupted(chart):
    chart.set_values([("浏览器", 60), ("其他", 120)])
    assert values(chart) == {"浏览器": 60, "其他": 120}
    chart.set_values([("浏览器", 120), ("其他", 240)])
    assert values(chart) == {"浏览器": 60, "其他": 120}
    chart.animation.stop()
    chart._animate(.5)
    assert values(chart) == {"浏览器": 90, "其他": 180}
    chart.set_values([("浏览器", 180), ("其他", 300)])
    assert values(chart) == {"浏览器": 90, "其他": 180}
    chart.animation.stop()
    chart._animate(.5)
    assert values(chart) == {"浏览器": 135, "其他": 240}
    assert sum(values(chart).values()) == 375


def test_identical_notification_does_not_restart_an_inflight_animation(chart):
    chart.set_values([("浏览器", 60)])
    chart.set_values([("浏览器", 120)])
    chart.animation.setCurrentTime(180)
    before = values(chart)
    time_before = chart.animation.currentTime()
    chart.set_values([("浏览器", 120)])
    assert chart.animation.currentTime() == time_before
    assert values(chart) == before
    assert chart.animation.state() == QAbstractAnimation.State.Running


def test_segments_keep_colors_when_ranking_changes_and_clear_without_fade(chart):
    chart.set_values([("浏览器", 60), ("其他", 120)])
    old_colors = dict(chart._colors)
    chart.set_values([("其他", 180), ("浏览器", 120), ("办公", 30)])
    assert all(chart._colors[label] == color for label, color in old_colors.items())
    chart.set_values([], "未开启")
    assert chart.entries == chart.displayed_entries == ()
    assert chart.animation.state() == QAbstractAnimation.State.Stopped
    assert chart.empty_message == "未开启"


def test_column_axis_interpolates_and_missing_is_distinct_from_recorded_zero(chart):
    chart.kind = "columns"
    chart.set_values([("10/19", None), ("10/20", 60)])
    ceiling_before = chart._display_max
    chart.set_values([("10/19", None), ("10/20", 600)])
    assert chart._display_max == ceiling_before
    chart.animation.stop()
    chart._animate(.5)
    assert ceiling_before < chart._display_max < chart._target_max
    assert values(chart)["10/19"] is None
    chart.set_values([("10/19", None), ("10/20", 0)])
    chart.animation.stop()
    chart._finish_transition()
    assert values(chart) == {"10/19": None, "10/20": 0}
    assert "0 分钟" in chart.empty_message


def test_new_and_removed_categories_transition_without_restarting_remaining_values(chart):
    chart.set_values([("浏览器", 60), ("其他", 120)])
    chart.set_values([("浏览器", 120), ("办公", 60)])
    chart.animation.stop()
    chart._animate(.5)
    assert values(chart) == {"浏览器": 90, "办公": 30, "其他": 60}
    chart._finish_transition()
    assert values(chart) == {"浏览器": 120, "办公": 60}


def test_cleared_observations_remove_stale_chart_data_immediately(chart):
    chart.kind = "columns"
    chart.set_values([("10/19", 60), ("10/20", 120)])
    chart.set_values([("10/19", None), ("10/20", None)])
    assert values(chart) == {"10/19": None, "10/20": None}
    assert chart.animation.state() == QAbstractAnimation.State.Stopped


def test_duplicate_friendly_names_preserve_total_time_and_missing_observations(chart):
    chart.set_values([("微信", 60), ("微信", 120), ("缺失", None), ("缺失", None),
                      ("零", None), ("零", 0)])
    assert values(chart) == {"微信": 180, "缺失": None, "零": 0}
    assert len(chart.entries) == 3
    chart.set_values([("微信", 90), ("微信", 150)])
    assert values(chart)["微信"] == 180
    chart.animation.stop()
    chart._animate(.5)
    assert values(chart)["微信"] == 210


def test_light_dialog_palette_overrides_dark_system_palette(app):
    old_palette, old_property = app.palette(), app.property("deskcareTheme")
    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor("#202020"))
    app.setPalette(dark)
    app.setProperty("deskcareTheme", None)
    try:
        apply_theme(app)
        dialog = TaskFormDialog()
        dialog.show()
        app.processEvents()
        background = dialog.grab().toImage().pixelColor(8, 8)
        assert min(background.red(), background.green(), background.blue()) > 230
        label = dialog.layout().itemAt(0).layout().labelForField(dialog.title_edit)
        foreground = label.palette().color(QPalette.ColorRole.WindowText)
        assert max(foreground.red(), foreground.green(), foreground.blue()) < 100
        buttons = dialog.findChild(QDialogButtonBox)
        assert buttons.button(QDialogButtonBox.StandardButton.Ok).text() == "添加"
        assert buttons.button(QDialogButtonBox.StandardButton.Cancel).text() == "取消"
        dialog.title_edit.setText("虚构任务")
        dialog._accept()
        assert dialog.values() == ("虚构任务", None, None)
        dialog.close()
    finally:
        app.setPalette(old_palette)
        app.setProperty("deskcareTheme", old_property)


def test_status_history_uses_only_authorized_self_reports(app, tmp_path, monkeypatch):
    repository = UsageRepository(tmp_path / "status.sqlite3")
    bodylog = BodyLogService(repository)
    repository.upsert_wellness_entry(date.today() - timedelta(days=2), WellnessLevel.COMFORTABLE)
    original_query = repository.wellness_entries_for_period
    queries = []

    def counted_query(*args):
        queries.append(args)
        return original_query(*args)

    monkeypatch.setattr(repository, "wellness_entries_for_period", counted_query)
    page = ReportsPage(MonitoringController(FakeActivityProvider()), repository, bodylog,
                       LocalReportService(repository))
    assert queries == []
    assert page.wellness_history.rowCount() == 0
    bodylog.set_enabled(True)
    assert page.wellness_history.rowCount() == 7
    assert page.wellness_history.item(0, 1).text() == "—"
    assert page.wellness_history.item(2, 1).text() == "无明显不适"
    assert "已记录 1 天" in page.history_title.text()
    page.wellness_level.setCurrentIndex(page.wellness_level.findData(WellnessLevel.COMFORTABLE))
    page.save_wellness.click()
    assert page.today_state_value.text() == "无明显不适"
    assert "已记录 2 天" in page.history_title.text()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    page.delete_wellness.click()
    assert page.wellness_history.item(0, 1).text() == "—"
    assert "已记录 1 天" in page.history_title.text()
    assert repository.wellness_for_day(date.today()) is None
    assert "无明显不适" not in page.report_text.toPlainText()
    queries_before = len(queries)
    bodylog.set_enabled(False)
    assert len(queries) == queries_before
    assert page.wellness_history.rowCount() == 0
    assert page.today_state_value.text() == "未开启"
    page.close()
