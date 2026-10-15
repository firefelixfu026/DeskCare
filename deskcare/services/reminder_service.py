"""M3 policy coordinator and non-blocking reminder feedback."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from deskcare.domain.break_policy import BreakPolicy
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
        self.policy = policy or BreakPolicy()
        self.personalization_service = personalization_service
        self.mode = "normal"
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
        )
        if self.personalization_service is not None:
            from deskcare.domain.break_policy import decide

            config = self.personalization_service.effective_config(self.policy.config, self.mode)
            decision = decide(context, config)
        else:
            decision = self.policy.decide(context)
        self._just_confirmed_task_done = False
        if decision.action is BreakAction.SOFT_NOTIFY:
            event = self.repository.add_reminder_event(
                occurred_at=current,
                decision=decision,
                mode=self.mode,
                active_minutes=context.continuous_active_minutes,
            )
            self._active_event_id = event.id
            self._last_prompt_at = current
            self.snapshot = ReminderSnapshot(decision, True, event.id, None, self.mode)
        elif self._active_event_id is not None and self.controller.is_collecting:
            self.snapshot = ReminderSnapshot(
                self.snapshot.decision,
                True,
                self._active_event_id,
                None,
                self.mode,
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

