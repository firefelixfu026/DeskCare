"""Submission fixes: readable factual reports and symmetric companion styles."""

from datetime import date

import pytest
from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import QApplication, QLabel

from deskcare.domain.types import WellnessLevel
from deskcare.services.report_engine import LocalReportService, ReportPeriod
from deskcare.storage.database import UsageRepository
from deskcare.ui.companion import CompanionWindow
from deskcare.ui.report_preview import ReportPreview
from deskcare.ui.theme import apply_theme


@pytest.fixture
def app():
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    yield app
    for window in app.topLevelWidgets():
        window.close()
        window.deleteLater()
    app.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.mark.parametrize("initial,target,label", [
    ("panel", "mascot", "切换为吉祥物"),
    ("mascot", "panel", "切换为简洁面板"),
])
def test_companion_context_menu_switches_both_ways(app, tmp_path, initial, target, label):
    repo = UsageRepository(tmp_path / "companion.sqlite3")
    window = CompanionWindow(repository=repo)
    window.set_presentation(initial)
    notifications = []
    window.presentation_changed.connect(notifications.append)
    menu = window._build_context_menu()
    next(action for action in menu.actions() if action.text() == label).trigger()
    assert window.presentation == target
    assert repo.get_setting("companion_style") == target
    assert notifications == [target]
    assert repo.get_consent("activity_monitoring") is not True
    assert repo.get_consent("wellness_checkin") is not True


def test_panel_header_and_background_have_context_menu(app, tmp_path, monkeypatch):
    window = CompanionWindow(repository=UsageRepository(tmp_path / "context.sqlite3"))
    calls = []
    monkeypatch.setattr(window, "_mascot_menu", calls.append)
    header = window.findChild(QLabel, "companionDragHandle")
    assert header.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu
    header.customContextMenuRequested.emit(QPoint(4, 4))
    window.content.customContextMenuRequested.emit(QPoint(8, 8))
    assert len(calls) == 2


def report_data(tmp_path):
    repo = UsageRepository(tmp_path / "report.sqlite3")
    repo.set_consent("activity_monitoring", True)
    repo.set_consent("app_name_stats", True)
    repo.set_consent("wellness_checkin", True)
    repo.add_usage(date.today(), "CODE", active_seconds=60 * 65, idle_seconds=60 * 10)
    for index in range(12):
        repo.add_app_usage(date.today(), f"app{index}", (12 - index) * 60)
    repo.upsert_wellness_entry(date.today(), WellnessLevel.COMFORTABLE)
    return LocalReportService(repo).render(ReportPeriod("daily", date.today(), date.today()))


def test_report_shortens_copy_without_changing_facts(tmp_path):
    facts, text = report_data(tmp_path)
    assert "事实摘要" not in text and "数据完整性与可选建议" not in text
    assert "电脑活跃时间约 **65 分钟**" in text
    assert "不是医学测量" in text and "不作医学判断" in text
    assert "未标记完成" not in text  # no tasks, no fabricated task progress
    assert "你记录的是“无明显不适”" in text
    assert "| app0 | 约 12 分钟 |" in text
    assert "| app5 |" not in text
    assert "| 其余应用合计 | 约 28 分钟 |" in text
    assert facts["applications"]["total_apps"] == 12
    assert len(facts["applications"]["top_apps"]) == 10


@pytest.mark.parametrize("width", [660, 1060])
def test_report_has_real_spacing_and_no_horizontal_scroll(app, tmp_path, width):
    facts, text = report_data(tmp_path)
    preview = ReportPreview()
    preview.resize(width, 600)
    preview.show()
    preview.set_report(text)
    app.processEvents()
    assert preview.horizontalScrollBar().maximum() == 0
    assert preview.document().rootFrame().frameFormat().leftMargin() >= 24
    block = preview.document().begin()
    headings = []
    while block.isValid():
        fmt = block.blockFormat()
        if fmt.headingLevel() == 2:
            headings.append(fmt)
        block = block.next()
    assert headings and all(fmt.topMargin() >= 24 for fmt in headings)
    assert "不作医学判断" in preview.toPlainText()
    assert not preview.openExternalLinks()
    position = min(120, preview.verticalScrollBar().maximum())
    preview.verticalScrollBar().setValue(position)
    preview.set_report(text)
    assert preview.verticalScrollBar().value() == position
