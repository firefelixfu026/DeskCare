"""M3 policy coordinator and non-blocking reminder feedback."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
import math
from datetime import datetime, timedelta

from deskcare.domain.break_policy import BreakPolicy, BreakPolicyConfig
from deskcare.domain.types import BreakAction, PolicyContext, PolicyDecision
from deskcare.services.activity_service import ActivityCollector
from deskcare.services.consent_service import MonitoringController
from deskcare.services.task_service import TaskService
from deskcare.storage.database import UsageRepository


REMINDER_RESPONSES = {
    "BREAK_NOW": "现在休息",
    "SNOOZE_10_MIN": "10 分钟后",
    "SKIP": "跳过",
    "BAD_TIMING": "时机不合适",
    "READING": "我正在阅读",
}


@dataclass(frozen=True)
class ReminderSnapshot:
    decision: PolicyDecision
    visible: bool = False
    event_id: int | None = None
    response: str | None = None
    mode: str = "normal"
    decision_context: dict[str, object] = field(default_factory=dict)


MODE_LABELS = {
    "normal": "普通工作",
    "focus": "专注模式",
    "meeting": "会议中",
    "reading": "阅读中",
    "quiet": "安静时段",
}


def decision_context_summary(context: dict[str, object]) -> str:
    """Summarize a shown reminder without exposing task or app names."""

    parts = [f"当时情境：{MODE_LABELS.get(str(context.get('mode')), '未记录')}"]
    active = context.get("continuous_active_minutes")
    if isinstance(active, (int, float)):
        parts.append(f"连续活跃估计约 {active:g} 分钟")
    elapsed = context.get("reminder_elapsed_minutes")
    if isinstance(elapsed, (int, float)):
        parts.append(f"本轮累计活跃约 {elapsed:g} 分钟")
    if context.get("observation_state") == "active":
        parts.append("最近有键鼠活动")
    if context.get("recent_switch"):
        parts.append("刚出现程序切换")
    if context.get("task_marked_done"):
        parts.append("你刚标记完成一项任务")
    deadline_seconds = context.get("confirmed_deadline_seconds_remaining")
    if isinstance(deadline_seconds, (int, float)) and 0 <= deadline_seconds <= 600:
        parts.append("已确认任务的截止时间临近")
    config = context.get("policy_config")
    if isinstance(config, dict):
        threshold = config.get("break_candidate_minutes")
        if isinstance(threshold, (int, float)):
            parts.append(f"当前提醒候选阈值为 {threshold:g} 分钟")
    return "；".join(parts) + "。"


class ReminderCoordinator:
    """Connect policy, bounded activity memory, confirmed tasks and UI.

    It never creates a modal dialog or changes focus. A soft notification is
    an inline card that the user can dismiss with one of the explicit actions.
    """

    def __init__(
        self,
        controller: MonitoringController,
        collector: ActivityCollector,
        task_service: TaskService,
        repository: UsageRepository,
        policy: BreakPolicy | None = None,
        personalization_service=None,
    ) -> None:
        self.controller = controller
        self.collector = collector
        self.task_service = task_service
        self.repository = repository
        self.policy = policy or BreakPolicy(BreakPolicyConfig(
            break_candidate_minutes=self.saved_interval(repository), max_soft_delay_minutes=5,
        ))
        self.personalization_service = personalization_service
        self.mode = "normal"
        if personalization_service is not None:
            personalization_service.base_candidate_minutes = self.policy.config.break_candidate_minutes
            personalization_service.refresh(self.mode)
        self._listeners: list[Callable[[ReminderSnapshot], None]] = []
        self._active_event_id: int | None = None
        self._last_prompt_at: datetime | None = None
        self._last_feedback_at: datetime | None = None
        self._last_response: str | None = None
        self._postpone_until: datetime | None = None
        self._just_confirmed_task_done = False
        self.snapshot = ReminderSnapshot(
            PolicyDecision(BreakAction.NONE, ("NOT_EVALUATED",), "等待活动样本。", 60)
        )
        self._restore_latest_event()
        controller.subscribe(self._on_controller_state)

    @staticmethod
    def saved_interval(repository) -> int:
        try:
            value = int(repository.get_setting("reminder_interval_minutes", "40"))
        except (ValueError, TypeError):
            return 40
        return value if 5 <= value <= 180 else 40

    def set_interval(self, minutes: int) -> None:
        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 5 <= minutes <= 180:
            raise ValueError("提醒间隔应为 5–180 分钟。")
        self.repository.set_setting("reminder_interval_minutes", str(minutes))
        self.policy.config = replace(self.policy.config, break_candidate_minutes=minutes)
        if self.personalization_service is not None:
            self.personalization_service.base_candidate_minutes = minutes
            self.personalization_service.refresh(self.mode)
        self._notify()

    @property
    def elapsed_minutes(self) -> float:
        elapsed = self.collector.reminder_elapsed_seconds
        return (self.collector.continuous_active_seconds if elapsed is None else elapsed) / 60

    def status_text(self) -> str:
        if not self.controller.enabled:
            return "开启电脑使用统计后，自动提醒才会开始。"
        if self.controller.paused:
            return "已暂停，不会自动提醒。"
        if self.mode in {"meeting", "quiet"}:
            return "会议或安静模式中，暂不提醒。"
        if self.snapshot.visible:
            return "有一条休息提醒，处理后继续计时。"
        reason = self.snapshot.decision.reason_codes[0]
        if reason in {"CONSENT_OR_PAUSE", "NOT_EVALUATED", "OBSERVATION_UNKNOWN"}:
            return "等待可用的电脑活动信号。"
        if reason == "INPUT_IDLE_NOT_PROVEN_BREAK":
            return "最近没有键鼠操作，等你继续使用时再提醒。"
        if reason == "COOLDOWN":
            return "稍后再提醒，暂时不打扰。"
        if reason == "SCHEDULE_OR_FOCUS_CONSTRAINT":
            return "专注或临近任务截止，稍晚再提醒。"
        target = self.policy.config.break_candidate_minutes
        if self.personalization_service is not None:
            target = self.personalization_service.effective_config(self.policy.config, self.mode).break_candidate_minutes
        remaining = max(0, math.ceil(target - self.elapsed_minutes))
        return (f"再累计使用约 {remaining} 分钟后择机提醒。" if remaining
                else "已到提醒时间，正在等一个合适的间隙。")

    def subscribe(self, listener: Callable[[ReminderSnapshot], None]) -> None:
        self._listeners.append(listener)
        listener(self.snapshot)

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener(self.snapshot)

    def _restore_latest_event(self) -> None:
        latest = self.repository.latest_reminder_event()
        if latest is None:
            return
        self._last_prompt_at = latest.occurred_at
        if latest.response:
            self._last_feedback_at = latest.response_at
            self._last_response = latest.response
            self._postpone_until = self._postpone_for(latest.response, latest.response_at)

    @staticmethod
    def _postpone_for(response: str, at: datetime | None) -> datetime | None:
        if at is None:
            return None
        minutes = {
            "BREAK_NOW": 10,
            "SNOOZE_10_MIN": 10,
            "SKIP": 10,
            "BAD_TIMING": 20,
            "READING": 10,
        }.get(response, 10)
        return at + timedelta(minutes=minutes)

    def _on_controller_state(self, enabled: bool, paused: bool) -> None:
        if not enabled or paused:
            self._active_event_id = None
            self.snapshot = ReminderSnapshot(
                PolicyDecision(BreakAction.NONE, ("CONSENT_OR_PAUSE",), "活动监测已关闭或暂停。", 30),
                mode=self.mode,
            )
            self._notify()

    def set_mode(self, mode: str) -> ReminderSnapshot:
        if mode not in {"normal", "focus", "meeting", "reading", "quiet"}:
            raise ValueError(f"unsupported mode: {mode}")
        self.mode = mode
        if self.personalization_service is not None:
            self.personalization_service.refresh(mode)
        if mode in {"meeting", "quiet"}:
            self._active_event_id = None
            self.snapshot = ReminderSnapshot(
                PolicyDecision(BreakAction.DEFER, ("USER_QUIET_MODE",), "你选择了安静情境，暂不弹出提醒。", 60),
                mode=mode,
            )
        else:
            self.snapshot = ReminderSnapshot(
                self.snapshot.decision,
                self.snapshot.visible,
                self.snapshot.event_id,
                self.snapshot.response,
                mode,
                self.snapshot.decision_context,
            )
        self._notify()
        return self.snapshot

    def mark_task_completed(self) -> None:
        """Record only a user action as a possible natural gap signal."""

        self._just_confirmed_task_done = True

    def reset_after_data_clear(self) -> None:
        """Forget persisted-history mirrors after the user clears all data."""

        self._active_event_id = None
        self._last_prompt_at = None
        self._last_feedback_at = None
        self._last_response = None
        self._postpone_until = None
        self._just_confirmed_task_done = False
        self.policy.config = replace(self.policy.config, break_candidate_minutes=40)
        if self.personalization_service is not None:
            self.personalization_service.base_candidate_minutes = 40
        if self.personalization_service is not None:
            self.personalization_service.refresh(self.mode)
        self.snapshot = ReminderSnapshot(
            PolicyDecision(
                BreakAction.NONE,
                ("CONSENT_OR_PAUSE",),
                "本地数据已清除，活动监测保持关闭。",
                30,
            ),
            mode=self.mode,
        )
        self._notify()

    def evaluate(
        self,
        *,
        now: datetime | None = None,
        is_recent_switch: bool = False,
    ) -> ReminderSnapshot:
        current = now or datetime.now().astimezone()
        sample = self.collector.latest_sample
        observation_unknown = sample is None or not sample.observation_ok
        context = PolicyContext(
            monitored=self.controller.enabled,
            mode=self.mode,
            continuous_active_minutes=self.collector.continuous_active_seconds / 60,
            idle_seconds=sample.idle_s if sample is not None and sample.observation_ok else None,
            is_recent_switch=is_recent_switch,
            next_confirmed_deadline=self.task_service.next_confirmed_deadline(now=current),
            now=current,
            last_prompt_at=self._last_prompt_at,
            last_response=self._last_response,
            manual_pause=self.controller.paused,
            observation_is_unknown=observation_unknown,
            just_confirmed_task_done=self._just_confirmed_task_done,
            postpone_until=self._postpone_until,
            last_feedback_at=self._last_feedback_at,
            reminder_elapsed_minutes=self.elapsed_minutes,
        )
        if self.personalization_service is not None:
            from deskcare.domain.break_policy import decide

            config = self.personalization_service.effective_config(self.policy.config, self.mode)
            decision = decide(context, config)
        else:
            config = self.policy.config
            decision = self.policy.decide(context)
        self._just_confirmed_task_done = False
        if decision.action is BreakAction.SOFT_NOTIFY and self._active_event_id is None:
            decision_context = {
                "rule_set": "break_policy_v1",
                "mode": context.mode,
                "monitoring_enabled": context.monitored,
                "manually_paused": context.manual_pause,
                "observation_state": (
                    sample.state.value
                    if sample is not None and sample.observation_ok
                    else "unknown"
                ),
                "idle_seconds": (
                    round(context.idle_seconds, 1)
                    if context.idle_seconds is not None
                    else None
                ),
                "continuous_active_minutes": round(
                    context.continuous_active_minutes, 1
                ),
                "reminder_elapsed_minutes": round(self.elapsed_minutes, 1),
                "recent_switch": context.is_recent_switch,
                "task_marked_done": context.just_confirmed_task_done,
                "confirmed_deadline_seconds_remaining": (
                    round((context.next_confirmed_deadline - current).total_seconds())
                    if context.next_confirmed_deadline is not None
                    else None
                ),
                "last_response": context.last_response,
                "last_prompt_age_seconds": (
                    round((current - context.last_prompt_at).total_seconds())
                    if context.last_prompt_at is not None
                    else None
                ),
                "last_feedback_age_seconds": (
                    round((current - context.last_feedback_at).total_seconds())
                    if context.last_feedback_at is not None
                    else None
                ),
                "postpone_seconds_remaining": (
                    max(0, round((context.postpone_until - current).total_seconds()))
                    if context.postpone_until is not None
                    else 0
                ),
                "policy_config": asdict(config),
            }
            event = self.repository.add_reminder_event(
                occurred_at=current,
                decision=decision,
                mode=self.mode,
                active_minutes=context.continuous_active_minutes,
                decision_context=decision_context,
            )
            self._active_event_id = event.id
            self._last_prompt_at = current
            self.snapshot = ReminderSnapshot(
                decision, True, event.id, None, self.mode, decision_context
            )
        elif self._active_event_id is not None and self.controller.is_collecting:
            self.snapshot = ReminderSnapshot(
                self.snapshot.decision,
                True,
                self._active_event_id,
                None,
                self.mode,
                self.snapshot.decision_context,
            )
        else:
            self.snapshot = ReminderSnapshot(decision, False, None, None, self.mode)
        self._notify()
        return self.snapshot

    def respond(self, response: str, *, now: datetime | None = None) -> ReminderSnapshot:
        if response not in REMINDER_RESPONSES:
            raise ValueError(f"unsupported reminder response: {response}")
        current = now or datetime.now().astimezone()
        if self._active_event_id is not None:
            self.repository.update_reminder_response(self._active_event_id, response, current)
        self._last_feedback_at = current
        self._last_response = response
        self._postpone_until = self._postpone_for(response, current)
        if response in {"BREAK_NOW", "SKIP"}:
            self.collector.reset_reminder_interval()
        if self.personalization_service is not None:
            self.personalization_service.refresh(self.mode)
        self._active_event_id = None
        self.snapshot = ReminderSnapshot(
            PolicyDecision(BreakAction.NONE, ("FEEDBACK_RECORDED",), "已记录你的选择，之后可以继续调整。", 60),
            False,
            None,
            response,
            self.mode,
        )
        self._notify()
        return self.snapshot

