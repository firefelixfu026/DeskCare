"""Deterministic, clearly labelled end-to-end demo data for DeskCare."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from deskcare.domain.types import ActivityKind, ActivitySample, TaskStatus, WellnessLevel
from deskcare.importers.csv_importer import parse_csv_bytes
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.bodylog_service import BodyLogService
from deskcare.services.consent_service import MonitoringController
from deskcare.services.reminder_service import ReminderCoordinator
from deskcare.services.report_engine import LocalReportService, ReportPeriod
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository


class _ScenarioProvider:
    is_demo = True

    def __init__(self, samples: list[ActivitySample]) -> None:
        self.samples = iter(samples)

    def read_sample(self) -> ActivitySample:
        return next(self.samples)


def prepare_demo_scenario(
    repository: UsageRepository,
    now: datetime | None = None,
) -> dict[str, object]:
    """Seed one synthetic, replayable user journey into an isolated DB.

    This function is idempotent. It uses service boundaries also used by the
    app; no OS activity provider, network service or model is contacted.
    """

    now = (now or datetime.now().astimezone()).astimezone()
    today = now.date()
    repository.set_setting("demo_mode", "true")
    repository.set_setting("demo_scenario", "true")
    if repository.get_setting("demo_scenario_seeded") == "true":
        facts, markdown = LocalReportService(repository).render(
            ReportPeriod("daily", today, today)
        )
        return {"seeded": False, "facts": facts, "report": markdown}

    day_start = datetime.combine(today, time.min, tzinfo=now.tzinfo)
    # Avoid splitting the demo activity across two report days when launched
    # shortly after midnight. Elsewhere use the current local time naturally.
    prompt_at = max(now, day_start + timedelta(minutes=40))
    started_at = prompt_at - timedelta(minutes=40)
    due_at = (prompt_at + timedelta(hours=2)).isoformat(timespec="minutes")
    imported = parse_csv_bytes(
        (
            "title,due_at,estimated_minutes\n"
            f"完成课程练习,{due_at},45\n"
            "整理今天的讨论笔记,,25\n"
        ).encode("utf-8"),
        "DeskCare演示任务.csv",
    )
    if not imported.can_confirm:
        raise RuntimeError("内置演示任务未能通过导入校验")

    task_service = TaskService(repository)
    tasks = task_service.confirm_import(imported.drafts, imported.source_name)

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
    repository.set_consent("activity_monitoring", True)
    controller = MonitoringController(_ScenarioProvider(samples), initially_enabled=True)
    collector = ActivityCollector(controller, repository)
    for _ in samples:
        collector.poll_once()
    reminders = ReminderCoordinator(controller, collector, task_service, repository)
    snapshot = reminders.evaluate(
        now=prompt_at,
        is_recent_switch=collector.consume_recent_switch(),
    )
    if not snapshot.visible or snapshot.event_id is None:
        raise RuntimeError("演示数据未能生成预期的休息提醒")
    reminders.respond("SNOOZE_10_MIN", now=prompt_at + timedelta(seconds=1))

    task_service.set_status(tasks[0].id, TaskStatus.DONE)
    bodylog = BodyLogService(repository)
    bodylog.set_enabled(True)
    bodylog.save_today(WellnessLevel.COMFORTABLE, today)
    repository.set_setting("demo_scenario_seeded", "true")

    facts, markdown = LocalReportService(repository).render(
        ReportPeriod("daily", today, today)
    )
    return {"seeded": True, "facts": facts, "report": markdown}
