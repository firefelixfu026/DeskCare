"""Run a deterministic fixed-interval vs context-aware policy comparison.

This is a behavior check, not a clinical or productivity study. Every input
is synthetic and the script intentionally avoids declaring a winner.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Make ``python scripts\run_baseline.py`` work from the project root without
# requiring an editable install.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from deskcare.domain.break_policy import BreakPolicy
from deskcare.domain.types import PolicyContext


def _context(**overrides) -> PolicyContext:
    now = datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc)
    values = {
        "monitored": True,
        "mode": "normal",
        "continuous_active_minutes": 45.0,
        "idle_seconds": 0.0,
        "is_recent_switch": False,
        "next_confirmed_deadline": None,
        "now": now,
    }
    values.update(overrides)
    return PolicyContext(**values)


SCENARIOS = {
    "ordinary_work": _context(),
    "meeting_mode": _context(mode="meeting"),
    "imminent_confirmed_deadline": _context(
        next_confirmed_deadline=datetime(2026, 10, 14, 10, 5, tzinfo=timezone.utc)
    ),
    "input_idle": _context(idle_seconds=120.0),
    "natural_gap": _context(is_recent_switch=True),
    "soft_delay_limit": _context(continuous_active_minutes=61.0),
    "monitoring_off": _context(monitored=False),
}


def fixed_interval_action(context: PolicyContext) -> str:
    """A deliberately simple 40-minute reminder baseline."""

    if context.monitored and context.continuous_active_minutes >= 40:
        return "soft_notify"
    return "none"


def run() -> dict[str, object]:
    policy = BreakPolicy()
    rows = []
    for name, context in SCENARIOS.items():
        adaptive = policy.decide(context)
        rows.append(
            {
                "scenario": name,
                "fixed_baseline_action": fixed_interval_action(context),
                "context_aware_action": adaptive.action.value,
                "reason_codes": list(adaptive.reason_codes),
            }
        )
    return {
        "experiment": "synthetic_fixed_interval_vs_context_aware",
        "conditions": {
            "fixed_threshold_minutes": 40,
            "adaptive_policy": "DeskCare BreakPolicy defaults",
            "input": "synthetic scenarios only",
            "interpretation": "behavioral comparison only; no clinical/productivity claim",
        },
        "rows": rows,
        "counts": {
            "fixed_soft_notifications": sum(row["fixed_baseline_action"] == "soft_notify" for row in rows),
            "adaptive_soft_notifications": sum(row["context_aware_action"] == "soft_notify" for row in rows),
            "adaptive_deferrals": sum(row["context_aware_action"] == "defer" for row in rows),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    args = parser.parse_args()
    payload = json.dumps(run(), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
