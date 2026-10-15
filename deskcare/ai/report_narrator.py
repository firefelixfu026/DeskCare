"""FactSheet-only local report narration with host-owned fact substitution."""

from __future__ import annotations

import re
from collections.abc import Mapping

from deskcare.ai.optional_local_llm import LocalLLMClient, LocalModelError


_PLACEHOLDER_RE = re.compile(r"\{([a-z_]+)\}")
_FORBIDDEN_PHRASES = (
    "诊断",
    "治疗",
    "治愈",
    "疲劳",
    "效率提升",
    "生产力提升",
    "健康改善",
    "视力改善",
    "情绪由",
)


class LocalReportNarrator:
    """Ask a loopback model for prose while keeping facts owned by DeskCare.

    The model returns templates containing placeholders rather than numbers.
    DeskCare substitutes values from the already-built FactSheet, so a model
    cannot invent a count or date in the displayed report.
    """

    _ALLOWED_PLACEHOLDERS = {
        "period_start",
        "period_end",
        "covered_minutes_estimate",
        "active_minutes_estimate",
        "days_with_activity",
        "period_days",
        "confirmed_total",
        "completed_by_user",
        "open_tasks",
        "reminders_shown",
        "break_intent_confirmed",
        "snoozed",
        "skipped",
        "bad_timing",
        "wellness_recorded_days",
    }

    def __init__(self, client: LocalLLMClient) -> None:
        self.client = client

    def narrate(self, facts: Mapping[str, object]) -> str:
        prompt = (
            "你是 DeskCare 的本地报告文字改写器。你只会看到一份已经汇总的 FactSheet，"
            "不要诊断、不要推断疲劳或效率、不要提出医学建议。返回严格 JSON："
            '{"summary_template": string, "suggestions": [string] }。'
            "summary_template 和每条 suggestion 只能使用普通中文与以下占位符："
            + ", ".join(sorted("{" + name + "}" for name in self._ALLOWED_PLACEHOLDERS))
            + "。不要输出任何阿拉伯数字；数字必须通过占位符由 DeskCare 代入。"
            "建议要低风险、可选择、面向习惯调整，不要把相关性写成因果。"
        )
        parsed = self.client.request_json(prompt, self.client.json_text(facts))
        if not isinstance(parsed, dict):
            raise LocalModelError("本机模型报告响应不是 JSON 对象。")
        summary = parsed.get("summary_template")
        suggestions = parsed.get("suggestions", [])
        if not isinstance(summary, str) or not summary.strip():
            raise LocalModelError("本机模型报告缺少可用摘要。")
        if not isinstance(suggestions, list) or any(not isinstance(item, str) for item in suggestions):
            raise LocalModelError("本机模型报告建议格式无效。")
        templates = [summary.strip(), *(item.strip() for item in suggestions[:5])]
        if any(not item or len(item) > 600 for item in templates):
            raise LocalModelError("本机模型报告文字长度无效。")
        combined = "\n".join(templates)
        if any(char.isdigit() for char in combined):
            raise LocalModelError("本机模型报告直接写入了未经校验的数字。")
        lowered = combined.casefold()
        if any(phrase.casefold() in lowered for phrase in _FORBIDDEN_PHRASES):
            raise LocalModelError("本机模型报告包含不允许的医学或因果表述。")
        names = set(_PLACEHOLDER_RE.findall(combined))
        if names - self._ALLOWED_PLACEHOLDERS:
            raise LocalModelError("本机模型报告引用了未授权的事实字段。")
        values = self._values(facts)
        rendered_summary = self._replace(summary.strip(), values)
        rendered_suggestions = [self._replace(item.strip(), values) for item in suggestions[:5] if item.strip()]
        lines = [
            "## 本地 AI 辅助摘要",
            "",
            rendered_summary,
        ]
        if rendered_suggestions:
            lines.extend(["", "### 可选建议", *(f"- {item}" for item in rendered_suggestions)])
        lines.extend(
            [
                "",
                "### AI 边界",
                "- 本段由本机模型根据 DeskCare FactSheet 改写；日期和数字由本地事实表代入。",
                "- 这不是医学判断，也不代表电脑活动导致了身体或效率变化。",
            ]
        )
        return "\n".join(lines)

    @staticmethod
    def _replace(text: str, values: Mapping[str, str]) -> str:
        return _PLACEHOLDER_RE.sub(lambda match: values[match.group(1)], text)

    @staticmethod
    def _values(facts: Mapping[str, object]) -> dict[str, str]:
        period = facts.get("period")
        quality = facts.get("data_quality")
        usage = facts.get("usage")
        tasks = facts.get("tasks")
        reminders = facts.get("reminders")
        wellness = facts.get("wellness")
        if not all(isinstance(value, Mapping) for value in (period, quality, usage, tasks, reminders)):
            raise LocalModelError("FactSheet 结构不完整。")
        return {
            "period_start": str(period["start"]),
            "period_end": str(period["end"]),
            "covered_minutes_estimate": str(quality["covered_minutes_estimate"]),
            "active_minutes_estimate": str(usage["active_minutes_estimate"]),
            "days_with_activity": str(quality["days_with_activity"]),
            "period_days": str(quality["period_days"]),
            "confirmed_total": str(tasks["confirmed_total"]),
            "completed_by_user": str(tasks["completed_by_user"]),
            "open_tasks": str(tasks["open"]),
            "reminders_shown": str(reminders["shown"]),
            "break_intent_confirmed": str(reminders["break_intent_confirmed"]),
            "snoozed": str(reminders["snoozed"]),
            "skipped": str(reminders["skipped"]),
            "bad_timing": str(reminders["bad_timing"]),
            "wellness_recorded_days": str(wellness["recorded_days"] if isinstance(wellness, Mapping) else 0),
        }
