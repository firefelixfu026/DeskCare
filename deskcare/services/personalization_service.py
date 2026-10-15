"""Bounded, explainable reminder personalization from explicit feedback."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace

from deskcare.domain.break_policy import BreakPolicyConfig


MODE_LABELS = {
    "normal": "普通",
    "focus": "专注",
    "meeting": "会议",
    "reading": "阅读",
    "quiet": "静默",
}


@dataclass(frozen=True)
class PersonalizationSnapshot:
    enabled: bool
    eligible: bool
    mode: str
    sample_count: int
    context_sample_count: int
    bad_timing_count: int
    required_samples: int
    required_context_samples: int
    base_candidate_minutes: int
    effective_candidate_minutes: int
    applied: bool
    explanation: str


class ReminderPersonalizationService:
    """Apply one conservative 5-minute step after enough real feedback.

    Only an explicit ``BAD_TIMING`` response can make reminders less frequent.
    It never makes reminders more frequent, changes hard gates, or infers a
    health state. Demo-provider feedback is ineligible by construction.
    """

    CONSENT_SCOPE = "reminder_personalization"
    MIN_TOTAL_SAMPLES = 10
    MIN_CONTEXT_SAMPLES = 5
    RECENT_LIMIT = 30
    BAD_TIMING_RATIO = 0.40
    ADJUSTMENT_MINUTES = 5

    def __init__(
        self,
        repository,
        *,
        initially_enabled: bool = False,
        data_is_demo: bool = False,
        base_candidate_minutes: int = 40,
    ) -> None:
        self.repository = repository
        self.eligible = not bool(data_is_demo)
        self.base_candidate_minutes = int(base_candidate_minutes)
        self._enabled = bool(initially_enabled) and self.eligible
        self._listeners: list[Callable[[PersonalizationSnapshot], None]] = []
        self.snapshot = self._calculate("normal")

    @property
    def enabled(self) -> bool:
        return self._enabled

    def subscribe(self, listener: Callable[[PersonalizationSnapshot], None]) -> None:
        self._listeners.append(listener)
        listener(self.snapshot)

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener(self.snapshot)

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled) and self.eligible
        self.repository.set_consent(self.CONSENT_SCOPE, self._enabled)
        self.refresh(self.snapshot.mode)

    def reset_to_default(self) -> None:
        """Disable adaptation without deleting the user's feedback history."""

        self.set_enabled(False)

    def refresh(self, mode: str = "normal") -> PersonalizationSnapshot:
        self.snapshot = self._calculate(mode)
        self._notify()
        return self.snapshot

    def effective_config(
        self,
        base_config: BreakPolicyConfig,
        mode: str,
    ) -> BreakPolicyConfig:
        if self.snapshot.mode != mode:
            self.snapshot = self._calculate(mode)
        if not self.snapshot.applied:
            return base_config
        return replace(
            base_config,
            break_candidate_minutes=self.snapshot.effective_candidate_minutes,
        )

    def _calculate(self, mode: str) -> PersonalizationSnapshot:
        mode_label = MODE_LABELS.get(mode, mode)
        if not self.eligible:
            return self._snapshot(
                mode,
                0,
                0,
                0,
                False,
                "演示数据不会用于提醒个性化；真实模式下仍需单独授权。",
            )
        events = self.repository.recent_reminder_events(
            limit=self.RECENT_LIMIT,
            responded_only=True,
        )
        context_events = [event for event in events if event.mode == mode]
        bad_timing_count = sum(event.response == "BAD_TIMING" for event in context_events)
        if not self._enabled:
            return self._snapshot(
                mode,
                len(events),
                len(context_events),
                bad_timing_count,
                False,
                "个性化已关闭，提醒候选窗口保持默认；历史反馈不会被删除。",
            )
        if len(events) < self.MIN_TOTAL_SAMPLES:
            return self._snapshot(
                mode,
                len(events),
                len(context_events),
                bad_timing_count,
                False,
                f"反馈样本 {len(events)}/{self.MIN_TOTAL_SAMPLES}，资料不足，尚未调整提醒参数。",
            )
        if len(context_events) < self.MIN_CONTEXT_SAMPLES:
            return self._snapshot(
                mode,
                len(events),
                len(context_events),
                bad_timing_count,
                False,
                f"共有 {len(events)} 条反馈，但{mode_label}情境只有 {len(context_events)}/{self.MIN_CONTEXT_SAMPLES} 条，保持默认。",
            )
        ratio = bad_timing_count / len(context_events)
        if ratio < self.BAD_TIMING_RATIO:
            return self._snapshot(
                mode,
                len(events),
                len(context_events),
                bad_timing_count,
                False,
                f"{mode_label}情境最近 {len(context_events)} 条反馈中有 {bad_timing_count} 次“时机不合适”，保持默认。",
            )
        effective = self.base_candidate_minutes + self.ADJUSTMENT_MINUTES
        return PersonalizationSnapshot(
            enabled=True,
            eligible=True,
            mode=mode,
            sample_count=len(events),
            context_sample_count=len(context_events),
            bad_timing_count=bad_timing_count,
            required_samples=self.MIN_TOTAL_SAMPLES,
            required_context_samples=self.MIN_CONTEXT_SAMPLES,
            base_candidate_minutes=self.base_candidate_minutes,
            effective_candidate_minutes=effective,
            applied=True,
            explanation=(
                f"{mode_label}情境最近 {len(context_events)} 条反馈中有 {bad_timing_count} 次“时机不合适”；"
                f"候选窗口从 {self.base_candidate_minutes} 调整为 {effective} 分钟。"
            ),
        )

    def _snapshot(
        self,
        mode: str,
        sample_count: int,
        context_sample_count: int,
        bad_timing_count: int,
        applied: bool,
        explanation: str,
    ) -> PersonalizationSnapshot:
        return PersonalizationSnapshot(
            enabled=self._enabled,
            eligible=self.eligible,
            mode=mode,
            sample_count=sample_count,
            context_sample_count=context_sample_count,
            bad_timing_count=bad_timing_count,
            required_samples=self.MIN_TOTAL_SAMPLES,
            required_context_samples=self.MIN_CONTEXT_SAMPLES,
            base_candidate_minutes=self.base_candidate_minutes,
            effective_candidate_minutes=self.base_candidate_minutes,
            applied=applied,
            explanation=explanation,
        )
