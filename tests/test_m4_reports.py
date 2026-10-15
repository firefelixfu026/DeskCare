from datetime import date, timedelta

from deskcare.domain.types import BreakAction, PolicyDecision, TaskStatus, WellnessLevel
from deskcare.services.bodylog_service import BodyLogService
from deskcare.services.report_engine import LocalReportService, ReportPeriod
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository


def _report_fixture(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    task_service = TaskService(repository)
    bodylog = BodyLogService(repository)
    today = date.today()
    repository.set_consent("activity_monitoring", True)
    repository.add_usage(today, "CODE", active_seconds=3600, idle_seconds=300, unknown_seconds=60)
    first = task_service.add_manual("确认任务")
    task_service.set_status(first.id, TaskStatus.DONE)
    task_service.add_manual("未完成任务")
    decision = PolicyDecision(BreakAction.SOFT_NOTIFY, ("POSSIBLE_NATURAL_GAP",), "可考虑留出空档。", 60)
    event = repository.add_reminder_event(
        occurred_at=__import__("datetime").datetime.now().astimezone(),
        decision=decision,
        mode="normal",
        active_minutes=40,
    )
    repository.update_reminder_response(
        event.id,
        "BREAK_NOW",
        __import__("datetime").datetime.now().astimezone(),
    )
    bodylog.set_enabled(True)
    bodylog.save_today(WellnessLevel.COMFORTABLE, today)
    return repository, today


def test_daily_facts_are_reproducible_and_traceable(tmp_path):
    repository, today = _report_fixture(tmp_path)
    service = LocalReportService(repository)
    facts, markdown = service.render(ReportPeriod("daily", today, today))

    assert facts["data_quality"]["activity_monitoring_enabled"] is True
    assert facts["data_quality"]["covered_minutes_estimate"] == 66.0
    assert facts["usage"]["active_minutes_estimate"] == 60.0
    assert facts["tasks"] == {"confirmed_total": 2, "completed_by_user": 1, "open": 1}
    assert facts["reminders"]["break_intent_confirmed"] == 1
    assert facts["wellness"]["entries"][0]["comfort_level"] == "comfortable"
    assert "未进行医学判断" in markdown
    assert "你标记完成 1 项" in markdown
    assert "身体状态总结" not in markdown


def test_report_is_honest_when_wellness_is_not_authorized_and_week_is_short(tmp_path):
    repository = UsageRepository(tmp_path / "deskcare.sqlite3")
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    repository.set_consent("activity_monitoring", True)
    repository.add_usage(week_start, "BROWSER", active_seconds=120)
    repository.add_usage(week_start + timedelta(days=1), "BROWSER", active_seconds=120)
    service = LocalReportService(repository)

    facts, markdown = service.render(ReportPeriod("weekly", week_start, week_start + timedelta(days=6)))

    assert facts["data_quality"]["days_with_activity"] == 2
    assert facts["data_quality"]["trend_eligible"] is False
    assert facts["wellness"] is None
    assert "未开启状态打卡" in markdown
    assert "不做趋势判断" in markdown
    assert "健康改善" not in markdown
