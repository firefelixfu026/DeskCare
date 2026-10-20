"""Deterministic, non-medical break recommendation policy for M3."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from deskcare.domain.types import BreakAction, PolicyContext, PolicyDecision


@dataclass(frozen=True)
class BreakPolicyConfig:
    """User-facing timing parameters, not medical thresholds."""

    break_candidate_minutes: int = 40
    max_soft_delay_minutes: int = 20
    idle_threshold_seconds: int = 60
    deadline_window_minutes: int = 10
    cooldown_minutes: int = 10


def _decision(
    action: BreakAction,
    reason: str,
    explanation: str,
    next_check_in_seconds: int,
) -> PolicyDecision:
    return PolicyDecision(action, (reason,), explanation, next_check_in_seconds)


def _within_cooldown(context: PolicyContext, config: BreakPolicyConfig) -> bool:
    now = context.now
    window_seconds = config.cooldown_minutes * 60
    if context.postpone_until is not None and now < context.postpone_until:
        return True
    if context.last_prompt_at is not None:
        elapsed = (now - context.last_prompt_at).total_seconds()
        if 0 <= elapsed < window_seconds:
            return True
    if context.last_feedback_at is not None:
        elapsed = (now - context.last_feedback_at).total_seconds()
        if 0 <= elapsed < window_seconds:
            return True
    return False


def _deadline_is_imminent(context: PolicyContext, config: BreakPolicyConfig) -> bool:
    if context.next_confirmed_deadline is None:
        return False
    seconds = (context.next_confirmed_deadline - context.now).total_seconds()
    return 0 <= seconds <= config.deadline_window_minutes * 60


def decide(
    context: PolicyContext,
    config: BreakPolicyConfig | None = None,
) -> PolicyDecision:
    """Return one explainable action without side effects or UI calls.

    The order is intentionally conservative: consent, user-selected quiet
    modes and observation limits always win over recommendation timing.
    """

    config = config or BreakPolicyConfig()
    if not context.monitored or context.manual_pause:
        return _decision(
            BreakAction.NONE,
            "CONSENT_OR_PAUSE",
            "活动监测未开启或已暂停，不生成休息提示。",
            30,
        )
    if context.mode in {"meeting", "quiet"}:
        return _decision(
            BreakAction.DEFER,
            "USER_QUIET_MODE",
            "你选择了会议或静默模式，暂不弹出提醒；不会连续追偿弹窗。",
            60,
        )
    if context.observation_is_unknown or context.idle_seconds is None:
        return _decision(
            BreakAction.NONE,
            "OBSERVATION_UNKNOWN",
            "当前活动观测不可用，不把缺失信号当作已经休息。",
            60,
        )
    if context.idle_seconds >= config.idle_threshold_seconds:
        return _decision(
            BreakAction.NONE,
            "INPUT_IDLE_NOT_PROVEN_BREAK",
            "最近没有键鼠输入；这不等于已经休息，因此暂不推断。",
            60,
        )
    if _within_cooldown(context, config):
        return _decision(
            BreakAction.NONE,
            "COOLDOWN",
            "你刚处理过提醒，先给你留出时间。",
            60,
        )
    elapsed_minutes = (context.continuous_active_minutes if context.reminder_elapsed_minutes is None
                       else context.reminder_elapsed_minutes)
    if elapsed_minutes < config.break_candidate_minutes:
        return _decision(
            BreakAction.NONE,
            "BELOW_THRESHOLD",
            "累计活跃时间尚未达到你设置的提醒间隔。",
            60,
        )
    delay_limit = config.break_candidate_minutes + config.max_soft_delay_minutes
    if (_deadline_is_imminent(context, config) or context.mode == "focus") and elapsed_minutes < delay_limit:
        return _decision(
            BreakAction.DEFER,
            "SCHEDULE_OR_FOCUS_CONSTRAINT",
            "接近已确认任务截止时间或处于专注模式，先不打断。",
            60,
        )
    if context.is_recent_switch or context.just_confirmed_task_done:
        return _decision(
            BreakAction.SOFT_NOTIFY,
            "POSSIBLE_NATURAL_GAP",
            "已到你设置的提醒时间，刚好出现了一个可能的空档。",
            300,
        )
    if elapsed_minutes >= delay_limit:
        return _decision(
            BreakAction.SOFT_NOTIFY,
            "SOFT_DELAY_LIMIT_REACHED",
            "已到提醒时间，也稍等了一会儿；如果方便，可以短暂休息一下。",
            300,
        )
    return _decision(
        BreakAction.DEFER,
        "WAIT_FOR_OPPORTUNITY",
        "已达到候选阈值，等待自然间隙，不强制打断。",
        60,
    )


class BreakPolicy:
    """Small injectable policy object used by services and tests."""

    def __init__(self, config: BreakPolicyConfig | None = None) -> None:
        self.config = config or BreakPolicyConfig()

    def decide(self, context: PolicyContext) -> PolicyDecision:
        return decide(context, self.config)
