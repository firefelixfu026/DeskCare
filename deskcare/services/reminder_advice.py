"""User-requested, data-minimal reminder advice. Never drives the timer."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json

from deskcare.domain.types import TaskStatus


class AdviceError(RuntimeError):
    """Safe UI error, with no provider body or personal content."""


ACTION_LABELS = {
    "keep": "先保持现在的提醒间隔",
    "break_at_gap": "下一个方便的间隙，可以考虑短暂停一下",
    "finish_step": "可以先收尾当前任务的一小步，再决定是否休息",
    "review_interval": "可以试着调整提醒间隔，之后再看是否合适",
    "do_not_interrupt": "当前不适合自动打扰，保留手动休息入口",
}
EVIDENCE_LABELS = {
    "mode": "你主动选择的情境",
    "activity": "当前累计活跃时间估计（不等于疲劳）",
    "task": "你为本次分析选定的任务（不是电脑自动识别）",
    "feedback": "当前情境的提醒反馈计数",
    "comfort": "你在本次分析主动提供的粗粒度感受",
    "deadline": "选定任务的截止时间临近",
}


@dataclass(frozen=True)
class AdviceContext:
    captured_at: datetime
    data_json: str

    @property
    def data(self) -> dict:
        return json.loads(self.data_json)


@dataclass(frozen=True)
class ReminderAdvice:
    action: str
    evidence: tuple[str, ...]
    interval_minutes: int | None = None
    source: str = "本机规则建议（未调用 AI）"

    def text(self) -> str:
        text = ACTION_LABELS[self.action]
        if self.interval_minutes is not None:
            text += f"\n建议尝试：{self.interval_minutes} 分钟；确认后才会修改。"
        text += "\n\n参考了：" + "、".join(EVIDENCE_LABELS[key] for key in self.evidence)
        return text + "\n\n" + self.source + "。这不是健康判断，也不会自动改变提醒或任务。"


class ReminderAdviceService:
    CONSENT_SCOPE = "reminder_context_ai"

    def __init__(self, repository, coordinator, task_service, *, now=None):
        self.repository = repository
        self.coordinator = coordinator
        self.tasks = task_service
        self.now = now or (lambda: datetime.now().astimezone())
        self.consent_epoch = 0

    @property
    def enabled(self):
        return self.repository.get_consent(self.CONSENT_SCOPE) is True

    def set_enabled(self, enabled):
        self.repository.set_consent(self.CONSENT_SCOPE, bool(enabled))
        self.consent_epoch += 1

    def capture(self, task_id=None, comfort=None) -> AdviceContext:
        """No journal, screen, application names, notes or activity timeline reads."""
        if comfort not in {None, "comfortable", "some_discomfort"}:
            raise AdviceError("请选择本次愿意提供的感受，或不提供。")
        now = self.now()
        selected = None
        if task_id is not None:
            task = next((item for item in self.tasks.list_today(now.date())
                         if item.id == task_id and item.status is not TaskStatus.DONE
                         and item.confirmed_at is not None), None)
            if task is None:
                raise AdviceError("选定任务已改变，请重新选择今天尚未完成的任务。")
            selected = {"id": task.id, "title": task.title, "status": task.status.value,
                        "due_at": task.due_at.isoformat() if task.due_at else None,
                        "estimated_minutes": task.estimated_minutes}
        coord = self.coordinator
        events = []
        personalization = coord.personalization_service
        if personalization and personalization.enabled and personalization.eligible:
            events = self.repository.recent_reminder_events(limit=30, responded_only=True)
        context_events = [item for item in events if item.mode == coord.mode]
        try:
            reviewed = int(self.repository.get_setting(f"reminder_reviewed_{coord.mode}", "0"))
        except (TypeError, ValueError):
            reviewed = 0
        base = coord.policy.config.break_candidate_minutes
        # These are product choices, not medical recommendations. Never anchor
        # AI advice to an accidentally tiny testing interval (e.g. 1 minute).
        choices = [20, 25, 30, 40, 45, 50, 60]
        sample = coord.collector.latest_sample
        usable = bool(sample is not None and sample.observation_ok and sample.idle_s is not None
                      and sample.idle_s < 60 and sample.state.value == "active")
        data = {
            "captured_at": now.isoformat(),
            "data_is_demo": bool(getattr(coord.controller, "provider_is_demo", False)),
            "mode": coord.mode,
            "monitoring_enabled": coord.controller.enabled,
            "paused": coord.controller.paused,
            "activity_available": usable,
            "active_minutes_estimate": round(coord.elapsed_minutes, 1) if usable else None,
            "interval_minutes": base,
            "interval_choices": choices,
            "feedback": {"total": len(events), "context_count": len(context_events),
                         "bad_timing": sum(item.response == "BAD_TIMING" for item in context_events),
                         "available": bool(personalization and personalization.enabled and personalization.eligible),
                         "review_already_handled": bool(reviewed and sum(item.id > reviewed for item in context_events) < 5)},
            "selected_task": selected,
            "self_report_this_request": comfort,
        }
        return AdviceContext(now, json.dumps(data, ensure_ascii=False, sort_keys=True))

    def is_current(self, context):
        if not timedelta(0) <= self.now() - context.captured_at <= timedelta(minutes=5):
            return False
        old = context.data
        try:
            fresh = self.capture((old["selected_task"] or {}).get("id"), old["self_report_this_request"]).data
        except AdviceError:
            return False
        # Passage of activity time does not invalidate the explicit snapshot;
        # consent, mode, task edits, new feedback and configuration do.
        for key in ("mode", "monitoring_enabled", "paused", "activity_available", "interval_minutes", "selected_task", "feedback"):
            if fresh[key] != old[key]:
                return False
        return True

    @staticmethod
    def available_evidence(context):
        data = context.data
        evidence = {"mode"}
        if data["activity_available"]:
            evidence.add("activity")
        if data["selected_task"]:
            evidence.add("task")
            due = data["selected_task"]["due_at"]
            if due:
                deadline = datetime.fromisoformat(due)
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=context.captured_at.tzinfo)
                if timedelta(0) <= deadline - context.captured_at <= timedelta(minutes=10):
                    evidence.add("deadline")
        if data["feedback"]["context_count"]:
            evidence.add("feedback")
        if data["self_report_this_request"] is not None:
            evidence.add("comfort")
        return evidence

    def fallback(self, context):
        data = context.data
        evidence = self.available_evidence(context)
        if (not data["monitoring_enabled"] or data["paused"] or not data["activity_available"]
                or data["mode"] in {"meeting", "quiet"}):
            return ReminderAdvice("do_not_interrupt", ("mode",))
        if data["self_report_this_request"] == "some_discomfort":
            return ReminderAdvice("break_at_gap", ("comfort",))
        feedback = data["feedback"]
        longer = [v for v in data["interval_choices"] if v > data["interval_minutes"]]
        if data["interval_minutes"] < 15:
            return ReminderAdvice("review_interval", ("mode", "activity"), 40)
        if (feedback["total"] >= 10 and feedback["context_count"] >= 5 and longer
                and not feedback["review_already_handled"]
                and feedback["bad_timing"] / feedback["context_count"] >= .4):
            ratio = feedback["bad_timing"] / feedback["context_count"]
            target = data["interval_minutes"] * (1.5 if ratio >= .7 else 1.25)
            return ReminderAdvice("review_interval", ("feedback",), min(longer, key=lambda value: abs(value-target)))
        if "deadline" in evidence or (data["selected_task"] and data["mode"] == "focus"):
            return ReminderAdvice("finish_step", tuple(k for k in ("mode", "task", "deadline") if k in evidence))
        if data["active_minutes_estimate"] >= data["interval_minutes"]:
            return ReminderAdvice("break_at_gap", ("activity",))
        return ReminderAdvice("keep", ("mode", "activity"))

    def validate(self, raw, context, *, source):
        """Model picks a strategy + factual keys, not arbitrary medical prose."""
        if not isinstance(raw, dict) or set(raw) != {"action", "evidence", "interval_minutes"}:
            raise AdviceError("AI 输出格式不符合约定，保留本机建议。")
        action, evidence, interval = raw["action"], raw["evidence"], raw["interval_minutes"]
        data = context.data
        if not isinstance(action, str) or action not in ACTION_LABELS:
            raise AdviceError("AI 建议未通过校验，保留本机建议。")
        allowed = self.available_evidence(context)
        if (not isinstance(evidence, list) or not 1 <= len(evidence) <= len(allowed)
                or any(not isinstance(key, str) or key not in allowed for key in evidence)
                or len(set(evidence)) != len(evidence)):
            raise AdviceError("AI 引用了未提供的资料，保留本机建议。")
        gate = (not data["monitoring_enabled"] or data["paused"] or not data["activity_available"]
                or data["mode"] in {"meeting", "quiet"})
        if gate and action != "do_not_interrupt":
            raise AdviceError("AI 建议与暂停或静默规则冲突，保留本机建议。")
        if action == "finish_step" and (not data["selected_task"]
                or data["self_report_this_request"] == "some_discomfort"):
            raise AdviceError("AI 不能猜测正在做的任务或要求带着不适继续，保留本机建议。")
        if action == "review_interval":
            if type(interval) is not int or interval not in data["interval_choices"] or interval == data["interval_minutes"]:
                raise AdviceError("AI 建议的间隔超出本次允许范围，保留本机建议。")
            if data["feedback"]["review_already_handled"] and set(evidence) <= {"mode", "feedback"}:
                raise AdviceError("这批反馈的建议已处理，不能据此反复要求延长间隔。")
            if set(evidence) <= {"feedback"}:
                feedback = data["feedback"]
                if feedback["total"] < 10 or feedback["context_count"] < 5 or feedback["bad_timing"] == 0:
                    raise AdviceError("这些反馈不足以支持调整间隔，请结合任务或当前设置重新分析。")
        elif interval is not None:
            raise AdviceError("AI 输出了与建议不一致的间隔，保留本机建议。")
        return ReminderAdvice(action, tuple(evidence), interval, source)

    def apply(self, advice, context, *, confirmed=False):
        if not confirmed or advice.interval_minutes is None:
            raise AdviceError("需要你确认具体间隔，才能修改。")
        if not self.is_current(context):
            raise AdviceError("情境或任务已改变，或建议超过 5 分钟，请重新分析。")
        if "AI" in advice.source and "未调用 AI" not in advice.source and not self.enabled:
            raise AdviceError("提醒 AI 授权已撤回，请重新分析。")
        validated = self.validate({"action": advice.action, "evidence": list(advice.evidence),
                                   "interval_minutes": advice.interval_minutes}, context, source=advice.source)
        self.coordinator.set_interval(validated.interval_minutes)
        if self.coordinator.personalization_service:
            try:
                self.coordinator.personalization_service.dismiss_current_suggestion()
            except Exception:
                # The primary setting is already persisted and broadcast. A
                # review-bookmark failure must not hide a successful change.
                pass
