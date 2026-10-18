"""M4 fact sheets and conservative local template reports."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

from deskcare.domain.display_names import CATEGORY_DISPLAY_NAMES, display_app_name
from deskcare.domain.types import WELLNESS_LEVEL_LABELS
from deskcare.storage.database import UsageRepository


@dataclass(frozen=True)
class ReportPeriod:
    kind: str
    start: date
    end: date

    def __post_init__(self) -> None:
        if self.kind not in {"daily", "weekly"}:
            raise ValueError("report period kind must be daily or weekly")
        if self.end < self.start:
            raise ValueError("report period end must not precede start")


def _days(period: ReportPeriod):
    current = period.start
    while current <= period.end:
        yield current
        current += timedelta(days=1)


class ReportFactsBuilder:
    """Build a non-diagnostic, reproducible dictionary from local records."""

    def __init__(self, repository: UsageRepository) -> None:
        self.repository = repository

    def build_facts(self, period: ReportPeriod) -> dict[str, object]:
        days = list(_days(period))
        usage_by_day = {day: self.repository.usage_for_day(day) for day in days}
        usage_rows = [row for rows in usage_by_day.values() for row in rows]
        active_seconds = sum(row.active_seconds for row in usage_rows)
        idle_seconds = sum(row.idle_seconds for row in usage_rows)
        unknown_seconds = sum(row.unknown_seconds for row in usage_rows)
        by_category: dict[str, float] = {}
        for row in usage_rows:
            by_category[row.category] = by_category.get(row.category, 0.0) + row.active_seconds / 60
        activity_enabled = self.repository.get_consent("activity_monitoring") is True
        app_details_enabled = (
            activity_enabled and self.repository.get_consent("app_name_stats") is True
        )
        app_rows = (
            self.repository.app_usage_for_period(period.start, period.end)
            if app_details_enabled
            else []
        )
        visible_app_rows = [row for row in app_rows if row.active_seconds > 0]
        days_with_activity = sum(
            any((row.active_seconds + row.idle_seconds + row.unknown_seconds) > 0 for row in rows)
            for rows in usage_by_day.values()
        )

        tasks_by_id = {
            task.id: task
            for day in days
            for task in self.repository.tasks_for_day(day)
        }
        tasks = list(tasks_by_id.values())
        reminders = [
            event
            for day in days
            for event in self.repository.reminder_events_for_day(day)
        ]
        wellness_enabled = self.repository.get_consent("wellness_checkin") is True
        wellness_entries = (
            self.repository.wellness_entries_for_period(period.start, period.end)
            if wellness_enabled
            else []
        )

        missing_sections: list[str] = []
        if not activity_enabled or not usage_rows:
            missing_sections.append("activity")
        if not wellness_enabled:
            missing_sections.append("wellness")
        if not tasks:
            missing_sections.append("tasks")
        return {
            "period": {
                "type": period.kind,
                "start": period.start.isoformat(),
                "end": period.end.isoformat(),
            },
            "data_quality": {
                "activity_monitoring_enabled": activity_enabled,
                "covered_minutes_estimate": round(
                    (active_seconds + idle_seconds + unknown_seconds) / 60, 1
                ),
                "days_with_activity": days_with_activity,
                "period_days": len(days),
                "wellness_opt_in": wellness_enabled,
                "wellness_recorded_days": len(wellness_entries),
                "application_details_enabled": app_details_enabled,
                "trend_eligible": period.kind == "weekly" and days_with_activity >= 3,
                "missing_sections": missing_sections,
            },
            "usage": {
                "active_minutes_estimate": round(active_seconds / 60, 1),
                "idle_minutes_estimate": round(idle_seconds / 60, 1),
                "unknown_minutes_estimate": round(unknown_seconds / 60, 1),
                "by_category_minutes": {
                    CATEGORY_DISPLAY_NAMES.get(category, "其他应用"): round(minutes, 1)
                    for category, minutes in sorted(by_category.items())
                    if minutes > 0
                },
            },
            "applications": (
                {
                    "total_apps": len(visible_app_rows),
                    "top_apps": [
                        {
                            "name": display_app_name(row.app_id),
                            "minutes": round(row.active_seconds / 60, 1),
                        }
                        for row in visible_app_rows[:10]
                    ],
                    "other_apps_minutes": round(
                        sum(row.active_seconds for row in visible_app_rows[10:]) / 60, 1
                    ),
                }
                if app_details_enabled
                else None
            ),
            "tasks": {
                "confirmed_total": len(tasks),
                "completed_by_user": sum(task.status.value == "done" for task in tasks),
                "open": sum(task.status.value != "done" for task in tasks),
            },
            "reminders": {
                "shown": len(reminders),
                "break_intent_confirmed": sum(event.response == "BREAK_NOW" for event in reminders),
                "snoozed": sum(event.response == "SNOOZE_10_MIN" for event in reminders),
                "skipped": sum(event.response == "SKIP" for event in reminders),
                "bad_timing": sum(event.response == "BAD_TIMING" for event in reminders),
                "reading": sum(event.response == "READING" for event in reminders),
            },
            "wellness": (
                {
                    "recorded_days": len(wellness_entries),
                    "entries": [
                        {"day": entry.day.isoformat(), "comfort_level": entry.comfort_level.value}
                        for entry in wellness_entries
                    ],
                }
                if wellness_enabled
                else None
            ),
            "sources": {
                "activity": "usage_daily aggregate" if activity_enabled else "not authorized",
                "applications": "separately authorized daily application totals" if app_details_enabled else "not authorized",
                "tasks": "user-confirmed tasks",
                "reminders": "local reminder_events feedback",
                "wellness": "user self-report" if wellness_enabled else "not authorized",
                "generator": "deterministic local template",
            },
        }


class TemplateNarrator:
    """Turn a FactSheet into cautious, traceable Markdown prose."""

    @staticmethod
    def _level_label(value: str) -> str:
        for level, label in WELLNESS_LEVEL_LABELS.items():
            if level.value == value:
                return label
        return "未识别的自报选项"

    def narrate(self, facts: Mapping[str, object]) -> str:
        period = facts["period"]
        quality = facts["data_quality"]
        usage = facts["usage"]
        tasks = facts["tasks"]
        reminders = facts["reminders"]
        wellness = facts["wellness"]
        assert isinstance(period, Mapping)
        assert isinstance(quality, Mapping)
        assert isinstance(usage, Mapping)
        assert isinstance(tasks, Mapping)
        assert isinstance(reminders, Mapping)
        lines = [
            f"# DeskCare {'日报' if period['type'] == 'daily' else '周报'}",
            "",
            f"时间范围：{period['start']} 至 {period['end']}（本地日期）",
            "生成方式：本地规则/模板；未调用在线模型，也未进行医学判断。",
            "",
            "## 事实摘要",
        ]
        if quality["activity_monitoring_enabled"] and quality["covered_minutes_estimate"] > 0:
            lines.extend(
                [
                    f"- 电脑活动观测覆盖约 {quality['covered_minutes_estimate']} 分钟（估计值，包含活跃、空闲和未知观测区间）。",
                    f"- 其中活跃电脑操作估计约 {usage['active_minutes_estimate']} 分钟；这不等同于真实工作时长或学习质量。",
                    f"- 有活动聚合的日期：{quality['days_with_activity']}/{quality['period_days']} 天。",
                ]
            )
        elif not quality["activity_monitoring_enabled"]:
            lines.append("- 本期间未开启活动监测，无法提供电脑活动统计；这不代表期间没有使用电脑。")
        else:
            lines.append("- 活动监测已开启，但本期间没有可用活动聚合；不能解释为 0 分钟使用。")

        lines.extend(
            [
                f"- 已确认任务 {tasks['confirmed_total']} 项，其中由你标记完成 {tasks['completed_by_user']} 项，未完成/未标记完成 {tasks['open']} 项。",
                f"- 提醒卡片显示 {reminders['shown']} 次；你选择“现在休息” {reminders['break_intent_confirmed']} 次、“10 分钟后” {reminders['snoozed']} 次、“跳过” {reminders['skipped']} 次、“时机不合适” {reminders['bad_timing']} 次。",
            ]
        )
        lines.extend(["", "## 电脑使用类别与常用应用"])
        categories = usage["by_category_minutes"]
        assert isinstance(categories, Mapping)
        if categories:
            lines.extend(
                f"- {category}：约 {minutes} 分钟。"
                for category, minutes in sorted(categories.items())
            )
        else:
            lines.append("- 本期间没有可展示的电脑使用类别记录。")
        applications = facts.get("applications")
        if applications is None:
            lines.append("- 未单独开启应用名称统计，因此这里不显示具体应用。")
        elif not isinstance(applications, Mapping) or applications["total_apps"] == 0:
            lines.append("- 应用名称统计已开启，但本期间没有可展示的应用记录。")
        else:
            app_list = applications["top_apps"]
            assert isinstance(app_list, list)
            if app_list:
                lines.extend(
                    f"- {app['name']}：约 {app['minutes']} 分钟。"
                    for app in app_list
                )
            if applications["other_apps_minutes"] > 0:
                lines.append(
                    f"- 其他应用合计：约 {applications['other_apps_minutes']} 分钟。"
                )
            lines.append("- 应用使用时间不代表具体任务内容或任务完成情况。")

        lines.extend(["", "## 今天的状态记录"])
        if wellness is None:
            lines.append("- 未开启状态打卡，因此不提供身体状态总结。")
        elif wellness["recorded_days"] == 0:
            lines.append("- 已开启状态打卡，但本期间没有主动记录。")
        else:
            entries = "；".join(
                f"{entry['day']}：{self._level_label(entry['comfort_level'])}"
                for entry in wellness["entries"]
            )
            lines.append(f"- 这是你主动填写的粗粒度舒适度记录，不是医学测量：{entries}。")

        lines.extend(["", "## 数据完整性与可选建议"])
        if period["type"] == "weekly" and not quality["trend_eligible"]:
            lines.append("- 本周活动有效记录少于 3 天，不做趋势判断；当前仅列出已记录事实。")
        elif period["type"] == "weekly":
            lines.append("- 本周至少有 3 天活动聚合，但趋势仍只表示记录变化，不代表健康或效率因果。")
        if "activity" in quality["missing_sections"]:
            lines.append("- 如果你需要活动回顾，可以在设置中单独开启活动监测；是否开启由你决定。")
        if "wellness" in quality["missing_sections"]:
            lines.append("- 如果你愿意，可以主动记录今天的状态；也可以选择不记录。")
        lines.append("- 如果提醒常常不合适，可以在今日页选择会议/专注/阅读等情境或使用反馈按钮调整当下提示。")
        lines.extend(
            [
                "",
                "## 这些信息从哪里来",
                "- 电脑使用类别来自活动统计；具体应用仅在你单独开启后纳入。任务和完成状态由你确认，提醒次数来自你的选择，状态记录由你主动填写。",
                "- 原始窗口标题、网页地址、键盘内容、截图和未选择文件不属于本报告输入。",
            ]
        )
        return "\n".join(lines)


class LocalReportService:
    """M4 local facts + template implementation; no network dependency."""

    def __init__(self, repository: UsageRepository) -> None:
        self.builder = ReportFactsBuilder(repository)
        self.narrator = TemplateNarrator()

    def build_facts(self, period: ReportPeriod) -> dict[str, object]:
        return self.builder.build_facts(period)

    def narrate(self, facts: Mapping[str, object]) -> str:
        return self.narrator.narrate(facts)

    def render(self, period: ReportPeriod) -> tuple[dict[str, object], str]:
        facts = self.build_facts(period)
        return facts, self.narrate(facts)

    @staticmethod
    def facts_json(facts: Mapping[str, object]) -> str:
        return json.dumps(facts, ensure_ascii=False, indent=2)

    def export_markdown(self, path: str | Path, period: ReportPeriod) -> Path:
        _facts, markdown = self.render(period)
        target = Path(path)
        target.write_text(markdown + "\n", encoding="utf-8")
        return target
