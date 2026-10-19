from datetime import date, datetime, time, timedelta

from deskcare.domain.types import ActivityKind, ActivitySample, BreakAction, TaskStatus, WellnessLevel
from deskcare.importers.csv_importer import parse_csv_bytes
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.bodylog_service import BodyLogService
from deskcare.services.consent_service import MonitoringController
from deskcare.services.reminder_service import ReminderCoordinator
from deskcare.services.report_engine import LocalReportService, ReportPeriod
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository


class _FlowProvider:
    is_demo = False

    def __init__(self, samples):
        self._samples = iter(samples)

    def read_sample(self):
        return next(self._samples)


def test_confirmed_task_activity_reminder_feedback_bodylog_report_closed_loop(tmp_path):
    """Exercise the complete offline product loop with explicit user actions."""

    today = date.today()
    local_tz = datetime.now().astimezone().tzinfo
    started_at = datetime.combine(today, time(9, 0), tzinfo=local_tz)
    samples = [
        ActivitySample(
            monotonic_s=index * 30.0,
            wall_time=started_at + timedelta(seconds=index * 30),
            idle_s=0.0,
            app_category="CODE",
            state=ActivityKind.ACTIVE,
            is_foreground_change=index == 80,
            observation_ok=True,
        )
        for index in range(81)
    ]
    database_path = tmp_path / "deskcare.sqlite3"
    repository = UsageRepository(database_path)
    controller = MonitoringController(_FlowProvider(samples), initially_enabled=True)
    repository.set_consent("activity_monitoring", True)
    collector = ActivityCollector(controller, repository)
    task_service = TaskService(repository)
    due_at = (started_at + timedelta(hours=2)).isoformat(timespec="minutes")
    import_result = parse_csv_bytes(
        f"title,due_at,estimated_minutes\n完成闭环演示材料,{due_at},60\n".encode("utf-8"),
        "演示任务.csv",
    )
    assert import_result.can_confirm
    task = task_service.confirm_import(import_result.drafts, import_result.source_name)[0]
    reminder = ReminderCoordinator(controller, collector, task_service, repository)

    for _ in samples:
        collector.poll_once()
    snapshot = reminder.evaluate(
        now=started_at + timedelta(minutes=40),
        is_recent_switch=collector.consume_recent_switch(),
    )
    assert snapshot.decision.action is BreakAction.SOFT_NOTIFY
    assert snapshot.decision.reason_codes == ("POSSIBLE_NATURAL_GAP",)
    trace = repository.latest_reminder_event().decision_context
    assert trace["rule_set"] == "break_policy_v1"
    assert trace["observation_state"] == "active"
    assert trace["recent_switch"] is True
    assert trace["policy_config"]["break_candidate_minutes"] == 40
    assert "完成闭环演示材料" not in str(trace)
    assert "CODE" not in str(trace)

    reminder.respond("BREAK_NOW", now=started_at + timedelta(minutes=40, seconds=1))
    task_service.set_status(task.id, TaskStatus.DONE)
    reminder.mark_task_completed()
    bodylog = BodyLogService(repository)
    bodylog.set_enabled(True)
    bodylog.save_today(WellnessLevel.COMFORTABLE, today)

    restarted_repository = UsageRepository(database_path)
    facts, markdown = LocalReportService(restarted_repository).render(
        ReportPeriod("daily", today, today)
    )
    assert facts["usage"]["active_minutes_estimate"] == 40.0
    assert facts["tasks"] == {
        "confirmed_total": 1,
        "completed_by_user": 1,
        "open": 0,
    }
    assert facts["reminders"]["shown"] == 1
    assert facts["reminders"]["break_intent_confirmed"] == 1
    assert facts["wellness"]["recorded_days"] == 1
    assert "活跃电脑操作估计约 40.0 分钟" in markdown
    assert "由你标记完成 1 项" in markdown
    assert "不是医学测量" in markdown
    assert "今天的状态" in markdown

