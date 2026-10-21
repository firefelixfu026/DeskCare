"""Bounded, explainable reminder personalization from explicit feedback."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
import math

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
    suggested_minutes: int | None = None
    snooze_count: int = 0
    consecutive_snoozes: int = 0
    skipped_count: int = 0


class ReminderPersonalizationService:
    """Suggest an interval review; never silently change the user's setting.

    Explicit BAD_TIMING and repeated snoozing are distinct review signals.
    It never changes intervals or hard gates, or infers a health state.
    Demo-provider feedback is ineligible by construction.
    """

    CONSENT_SCOPE = "reminder_personalization"
    MIN_TOTAL_SAMPLES = 10
    MIN_CONTEXT_SAMPLES = 5
    RECENT_LIMIT = 30
    BAD_TIMING_RATIO = 0.40
    SNOOZE_STREAK_FOR_REVIEW = 3

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
        return base_config

    def dismiss_current_suggestion(self) -> None:
        """Wait for five new responses in this context before asking again."""
        events = self.repository.recent_reminder_events(limit=self.RECENT_LIMIT, responded_only=True)
        latest = max((event.id for event in events if event.mode == self.snapshot.mode), default=0)
        self.repository.set_setting(f"reminder_reviewed_{self.snapshot.mode}", str(latest))
        self.refresh(self.snapshot.mode)

    def _calculate(self, mode: str) -> PersonalizationSnapshot:
        events = self.repository.recent_reminder_events(limit=self.RECENT_LIMIT, responded_only=True) if self.eligible else []
        context = [event for event in events if event.mode == mode]
        streak = 0
        for event in context:
            if event.response != "SNOOZE_10_MIN":
                break
            streak += 1
        result = self._calculate_from_events(mode, events)
        if self.eligible and self._enabled and streak >= self.SNOOZE_STREAK_FOR_REVIEW and result.suggested_minutes is None:
            try:
                reviewed = int(self.repository.get_setting(f"reminder_reviewed_{mode}", "0"))
            except (TypeError, ValueError):
                reviewed = 0
            handled = bool(reviewed and sum(event.id > reviewed for event in context) < self.MIN_CONTEXT_SAMPLES)
            suggested = 40 if self.base_candidate_minutes < 15 else min(180, int(math.ceil(self.base_candidate_minutes * 1.25 / 5) * 5))
            if handled:
                result = replace(result, explanation="已处理这次建议，收到 5 条新的同情境反馈后再评估。")
            elif suggested > self.base_candidate_minutes:
                result = replace(result, suggested_minutes=suggested,
                    explanation=(f"同情境最近连续 {streak} 次选择了“10 分钟后”。要不要复核提醒频率，"
                                 f"例如从 {self.base_candidate_minutes} 改为 {suggested} 分钟？"
                                 "这只是推迟线索，不算“时机不合适”，也不会自动修改。"))
        snoozed = sum(event.response == "SNOOZE_10_MIN" for event in context)
        skipped = sum(event.response == "SKIP" for event in context)
        prefix = (f"同情境：推迟 {snoozed} 次 · 跳过 {skipped} 次 · 明确不合适 {result.bad_timing_count} 次。\n"
                  if self.eligible and context else "")
        return replace(result, snooze_count=snoozed, skipped_count=skipped, consecutive_snoozes=streak,
                       explanation=prefix + result.explanation)

    def _calculate_from_events(self, mode: str, events) -> PersonalizationSnapshot:
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
        context_events = [event for event in events if event.mode == mode]
        bad_timing_count = sum(event.response == "BAD_TIMING" for event in context_events)
        if not self._enabled:
            return self._snapshot(
                mode,
                len(events),
                len(context_events),
                bad_timing_count,
                False,
                "反馈建议已关闭，仍按你设置的间隔提醒。历史反馈保留。",
            )
        if len(events) < self.MIN_TOTAL_SAMPLES:
            return self._snapshot(
                mode,
                len(events),
                len(context_events),
                bad_timing_count,
                False,
                f"已收到 {len(events)} 条反馈，满 {self.MIN_TOTAL_SAMPLES} 条后再评估；不会自动改间隔。",
            )
        if len(context_events) < self.MIN_CONTEXT_SAMPLES:
            return self._snapshot(
                mode,
                len(events),
                len(context_events),
                bad_timing_count,
                False,
                f"共 {len(events)} 条反馈，{mode_label}情境 {len(context_events)}/{self.MIN_CONTEXT_SAMPLES} 条；暂不建议调整。",
            )
        ratio = bad_timing_count / len(context_events)
        if ratio < self.BAD_TIMING_RATIO:
            return self._snapshot(
                mode,
                len(events),
                len(context_events),
                bad_timing_count,
                False,
                f"{mode_label}情境最近 {len(context_events)} 条反馈中有 {bad_timing_count} 次“时机不合适”，保持当前间隔。",
            )
        try:
            reviewed = int(self.repository.get_setting(f"reminder_reviewed_{mode}", "0"))
        except (TypeError, ValueError):
            reviewed = 0
        if reviewed and sum(event.id > reviewed for event in context_events) < self.MIN_CONTEXT_SAMPLES:
            return self._snapshot(mode, len(events), len(context_events), bad_timing_count, False,
                                  "已处理这次建议，收到 5 条新的同情境反馈后再评估。")
        suggested = (40 if self.base_candidate_minutes < 15 else
                     min(180, int(math.ceil(self.base_candidate_minutes * (1.5 if ratio >= .7 else 1.25) / 5) * 5)))
        if suggested <= self.base_candidate_minutes:
            return self._snapshot(mode, len(events), len(context_events), bad_timing_count, False,
                                  "提醒间隔已达上限；可以按工作安排切换专注、会议或安静模式。")
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
            effective_candidate_minutes=self.base_candidate_minutes,
            applied=False,
            explanation=(
                f"{mode_label}情境最近 {len(context_events)} 条反馈中，{bad_timing_count} 次认为时机不合适。"
                f"要不要把间隔从 {self.base_candidate_minutes} 改为 {suggested} 分钟？也可以先分析当前安排；不会自动修改。"
            ),
            suggested_minutes=suggested,
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
