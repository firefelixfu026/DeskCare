from datetime import datetime, timedelta, timezone

from deskcare.domain.break_policy import BreakPolicy, BreakPolicyConfig
from deskcare.domain.types import BreakAction, PolicyContext


NOW = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)


def context(**changes):
    values = dict(
        monitored=True,
        mode="normal",
        continuous_active_minutes=45,
        idle_seconds=0,
        is_recent_switch=False,
        next_confirmed_deadline=None,
        now=NOW,
    )
    values.update(changes)
    return PolicyContext(**values)


def test_m3_policy_hard_gates_and_evidence_boundaries():
    policy = BreakPolicy()
    cases = [
        (context(monitored=False), "CONSENT_OR_PAUSE", BreakAction.NONE),
        (context(manual_pause=True), "CONSENT_OR_PAUSE", BreakAction.NONE),
        (context(mode="meeting"), "USER_QUIET_MODE", BreakAction.DEFER),
        (context(observation_is_unknown=True), "OBSERVATION_UNKNOWN", BreakAction.NONE),
        (context(idle_seconds=90), "INPUT_IDLE_NOT_PROVEN_BREAK", BreakAction.NONE),
        (context(continuous_active_minutes=20), "BELOW_THRESHOLD", BreakAction.NONE),
        (context(last_prompt_at=NOW - timedelta(minutes=2)), "COOLDOWN", BreakAction.NONE),
    ]
    for test_context, reason, action in cases:
        decision = policy.decide(test_context)
        assert decision.reason_codes == (reason,)
        assert decision.action is action


def test_m3_policy_schedule_focus_and_natural_gap_scenarios():
    policy = BreakPolicy()
    deadline = policy.decide(
        context(next_confirmed_deadline=NOW + timedelta(minutes=5))
    )
    assert deadline.reason_codes == ("SCHEDULE_OR_FOCUS_CONSTRAINT",)
    assert deadline.action is BreakAction.DEFER

    focus = policy.decide(context(mode="focus"))
    assert focus.reason_codes == ("SCHEDULE_OR_FOCUS_CONSTRAINT",)

    natural = policy.decide(context(is_recent_switch=True))
    assert natural.reason_codes == ("POSSIBLE_NATURAL_GAP",)
    assert natural.action is BreakAction.SOFT_NOTIFY

    completed = policy.decide(context(just_confirmed_task_done=True))
    assert completed.reason_codes == ("POSSIBLE_NATURAL_GAP",)


def test_m3_policy_delay_limit_and_unconfirmed_tasks():
    policy = BreakPolicy(BreakPolicyConfig(break_candidate_minutes=40, max_soft_delay_minutes=20))
    no_confirmed_task = policy.decide(context(continuous_active_minutes=61))
    assert no_confirmed_task.reason_codes == ("SOFT_DELAY_LIMIT_REACHED",)
    assert no_confirmed_task.action is BreakAction.SOFT_NOTIFY

    waiting = policy.decide(context(continuous_active_minutes=45))
    assert waiting.reason_codes == ("WAIT_FOR_OPPORTUNITY",)
    assert waiting.action is BreakAction.DEFER

    # An unconfirmed draft is not represented by next_confirmed_deadline and
    # therefore cannot alter the policy input.
    assert policy.decide(context(next_confirmed_deadline=None, is_recent_switch=True)).reason_codes == (
        "POSSIBLE_NATURAL_GAP",
    )


def test_m3_policy_postpone_and_feedback_cooldown():
    policy = BreakPolicy()
    decision = policy.decide(
        context(postpone_until=NOW + timedelta(minutes=9), last_response="SNOOZE_10_MIN")
    )
    assert decision.reason_codes == ("COOLDOWN",)
