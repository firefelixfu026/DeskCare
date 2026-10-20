from datetime import date, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from deskcare.config import ConfigStore
from deskcare.sensors.fake import FakeActivityProvider
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.services.report_engine import LocalReportService
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository
from deskcare.ui.main_window import MainWindow


@pytest.fixture
def shell(tmp_path):
    app = QApplication.instance() or QApplication([])
    repository = UsageRepository(tmp_path / "ui.sqlite3")
    controller = MonitoringController(FakeActivityProvider(), initially_enabled=True)
    collector = ActivityCollector(controller, repository)
    tasks = TaskService(repository)
    window = MainWindow(ConfigStore(), controller, collector, tasks,
                        repository=repository, report_service=LocalReportService(repository))
    yield window, repository, collector, tasks
    window._allow_close = True
    window.close()
    window.deleteLater()
    app.processEvents()


def test_charts_follow_live_aggregates_and_revoked_app_consent(shell):
    window, repository, collector, _tasks = shell
    repository.add_usage(date.today(), "BROWSER", active_seconds=120)
    repository.set_consent("app_name_stats", True)
    repository.add_app_usage(date.today(), "chrome", 120)
    collector.notify()
    usage = window.usage_page
    usage.period_choice.setCurrentIndex(1)
    assert next(entry.seconds for entry in usage.week_chart.entries if entry.label == date.today().strftime("%m/%d")) == 120
    assert any(entry.seconds is None for entry in usage.week_chart.entries)  # no observation, not zero
    assert usage.category_chart.entries[0].label == "浏览器"
    assert usage.app_chart.entries[0].seconds == 120
    repository.add_usage(date.today(), "BROWSER", active_seconds=60)
    collector.notify()
    assert next(entry.seconds for entry in usage.week_chart.entries if entry.label == date.today().strftime("%m/%d")) == 180
    collector.set_app_name_enabled(False)
    assert usage.app_chart.entries == ()
    assert repository.app_usage_for_period(date.today() - timedelta(days=6), date.today()) == []


def test_navigation_separates_status_report_and_settings_groups(shell):
    window, _repository, _collector, _tasks = shell
    window.navigation.setCurrentRow(2)
    assert window.pages.currentWidget() is window.reports_page
    assert window.reports_page.sections.currentIndex() == 0
    window.navigation.setCurrentRow(3)
    assert window.reports_page.sections.currentIndex() == 1
    window.navigation.setCurrentRow(4)
    assert window.pages.currentWidget() is window.settings_page
    assert [window.settings_page.sections.tabText(i) for i in range(4)] == [
        "常用设置", "提醒与状态", "AI 服务", "数据与隐私"
    ]


def test_recorded_zero_active_time_is_not_presented_as_missing_observation(shell):
    window, repository, collector, _tasks = shell
    window.usage_page.period_choice.setCurrentIndex(1)
    chart = window.usage_page.week_chart
    assert all(entry.seconds is None for entry in chart.entries)
    missing = chart.empty_message
    repository.add_usage(date.today(), "IDLE", idle_seconds=120)
    collector.notify()
    assert next(entry.seconds for entry in chart.entries if entry.label == date.today().strftime("%m/%d")) == 0
    assert "0 分钟" in chart.empty_message
    assert chart.empty_message != missing


def test_report_renders_markdown_and_refreshes_after_user_task_action(shell):
    window, _repository, _collector, tasks = shell
    report = window.reports_page.report_text
    before = report.toPlainText()
    assert "还没有添加任务" in before
    assert "# DeskCare" not in before
    assert "<h1" in report.toHtml()
    tasks.add_manual("虚构 UI 体验任务")
    assert "已确认任务 1 项" in report.toPlainText()
    assert not report.openExternalLinks()
    assert report.loadResource(2, "file:///private.png") is None


def test_live_updates_preserve_labelled_ai_snapshot_until_explicit_refresh(shell):
    window, _repository, _collector, tasks = shell
    page = window.reports_page

    class EnabledAI:
        enabled = True

    page.local_ai_service = EnabledAI()
    generation = page._report_ai_generation
    page._report_ai_thread = object()  # deterministic in-flight model request
    tasks.add_manual("虚构新增任务")
    assert page._report_ai_generation == generation
    page._report_ai_base_markdown = page.report_text.markdown
    page._on_report_ai_finished(generation, "## AI 示例摘要\n\n仅根据生成时记录。", True)
    page._report_ai_thread = None
    page.notify_data_changed()
    assert "AI 示例摘要" in page.report_text.toPlainText()
    assert "快照" in page.report_sources.text()
    page.refresh_report()
    assert "AI 示例摘要" not in page.report_text.toPlainText()
    assert "已确认任务 1 项" in page.report_text.toPlainText()
