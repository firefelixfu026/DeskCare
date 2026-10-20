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
                "demo_data": self.repository.get_setting("demo_mode") == "true",
                "demo_scenario": self.repository.get_setting("demo_scenario") == "true",
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

    @staticmethod
    def _minutes(value) -> str:
        return f"{float(value):.1f}".rstrip("0").rstrip(".")

    @staticmethod
    def _table_text(value) -> str:
        # Program names are data, not Markdown syntax or external resources.
        text = str(value).replace("\n", " ").replace("\r", " ")
        for character in ("\\", "|", "*", "_", "[", "]", "`", "<", ">"):
            text = text.replace(character, "\\" + character)
        return text

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
            f"# {'【演示数据】' if quality.get('demo_data') else ''}DeskCare {'日报' if period['type'] == 'daily' else '周报'}",
            "",
            period["start"] if period["type"] == "daily" else f"{period['start']} 至 {period['end']}",
            "",
            "本机整理 · 未使用 AI",
            "",
        ]
        if quality.get("demo_data"):
            lines.extend([
                "> 本报告中的任务、电脑活动、提醒和状态记录均为软件生成的虚构演示数据，不是本机真实记录，也不能用于判断健康状况或产品效果。",
                "",
            ])
        lines.append("## 今天一览" if period["type"] == "daily" else "## 这一周")
        if quality["activity_monitoring_enabled"] and quality["covered_minutes_estimate"] > 0:
            lines.extend(
                [
                    f"记录到的电脑活跃时间约 **{self._minutes(usage['active_minutes_estimate'])} 分钟**。",
                    "",
                ]
            )
        elif not quality["activity_monitoring_enabled"]:
            lines.append("电脑使用统计未开启，暂时没有这部分记录；不代表你没有使用电脑。")
        else:
            lines.append("电脑使用统计已开启，这段时间还没有可用记录，不能当作使用了 0 分钟。")

        lines.extend(
            [
                "",
                (f"已确认任务 {tasks['confirmed_total']} 项，你标记完成 {tasks['completed_by_user']} 项，还有 {tasks['open']} 项未标记完成。"
                 if tasks['confirmed_total'] else "还没有添加任务。"),
            ]
        )
        if reminders["shown"]:
            feedback = [f"{text} {reminders[key]} 次" for key, text in (
                ("break_intent_confirmed", "选择现在休息"), ("snoozed", "稍后提醒"),
                ("skipped", "跳过"), ("bad_timing", "觉得时机不合适"), ("reading", "标记正在阅读"),
            ) if reminders.get(key)]
            lines.extend(["", f"休息提醒显示了 {reminders['shown']} 次。" +
                          ("你的选择：" + "，".join(feedback) + "。" if feedback else "暂时没有选择记录。")])
        else:
            lines.extend(["", "这段时间没有弹出休息提醒。"])

        lines.extend(["", "## 今天的状态" if period['type'] == 'daily' else "## 这一周的状态"])
        if wellness is None:
            lines.append("未开启状态打卡，这里不包含个人状态记录。")
        elif wellness["recorded_days"] == 0:
            lines.append("这段时间还没有填写状态。")
        else:
            if period['type'] == 'daily':
                lines.append(f"你记录的是“{self._level_label(wellness['entries'][0]['comfort_level'])}”。")
            else:
                lines.extend(["| 日期 | 你记录的状态 |", "| --- | --- |"])
                lines.extend(f"| {entry['day']} | {self._level_label(entry['comfort_level'])} |"
                             for entry in wellness['entries'])
        lines.extend(["", "## 电脑使用", "", "### 按类别", ""])
        categories = usage["by_category_minutes"]
        assert isinstance(categories, Mapping)
        if categories:
            lines.extend(["| 类别 | 活跃时间估计 |", "| --- | --- |"])
            lines.extend(f"| {self._table_text(category)} | 约 {self._minutes(minutes)} 分钟 |"
                         for category, minutes in sorted(categories.items(), key=lambda item: item[1], reverse=True))
        else:
            lines.append("暂无类别记录。")
        lines.extend(["", "### 常用应用", ""])
        applications = facts.get("applications")
        if applications is None:
            lines.append("未单独开启应用名称统计，这里不显示具体应用。")
        elif not isinstance(applications, Mapping) or applications["total_apps"] == 0:
            lines.append("应用名称统计已开启，暂时还没有记录。")
        else:
            app_list = applications["top_apps"]
            assert isinstance(app_list, list)
            if app_list:
                lines.extend(["| 应用 | 活跃时间估计 |", "| --- | --- |"])
                lines.extend(f"| {self._table_text(app['name'])} | 约 {self._minutes(app['minutes'])} 分钟 |"
                             for app in app_list[:5])
            remaining = applications["other_apps_minutes"] + sum(app["minutes"] for app in app_list[5:])
            if remaining > 0:
                lines.append(f"| 其余应用合计 | 约 {self._minutes(round(remaining, 1))} 分钟 |")
            if applications["total_apps"] > 5:
                lines.extend(["", "这里只列用时最多的 5 个应用，完整排行可在“使用统计”查看。"])

        lines.extend(["", "## 记录说明", ""])
        if period["type"] == "weekly" and not quality["trend_eligible"]:
            lines.extend([f"本周有 {quality['days_with_activity']}/{quality['period_days']} 天的使用记录。有效记录少于 3 天，不做趋势判断。", ""])
        elif period["type"] == "weekly":
            lines.extend([f"本周有 {quality['days_with_activity']}/{quality['period_days']} 天的使用记录，不能据此判断健康或效率变化。", ""])
        if quality["activity_monitoring_enabled"] and quality["covered_minutes_estimate"] > 0:
            lines.extend([f"统计覆盖约 {self._minutes(quality['covered_minutes_estimate'])} 分钟，包含活跃、空闲和暂未识别的时段。活跃时间是估计值，不等于工作或学习时长，也不说明某项任务已经完成。", ""])
        lines.extend(
            [
                "任务和完成状态由你确认；提醒来自本机提示记录。状态由你填写，不是医学测量，这份回顾也不作医学判断。",
                "",
                "电脑使用只包含已授权的统计，不读取窗口标题、网页地址或键盘内容。",
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
