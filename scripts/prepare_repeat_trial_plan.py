"""Prepare the provider-free Step 4.16 repeat-trial review packet."""

from __future__ import annotations

import argparse
from pathlib import Path

from rfp_orchestrator.evaluation_trials import (
    DEFAULT_REPEAT_TRIAL_PLAN_PATH,
    DEFAULT_REPEAT_TRIAL_REVIEW_PATH,
    build_repeat_trial_proposal,
    write_repeat_trial_proposal,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPEAT_TRIAL_PLAN_PATH)
    parser.add_argument(
        "--review-output",
        type=Path,
        default=DEFAULT_REPEAT_TRIAL_REVIEW_PATH,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    plan = build_repeat_trial_proposal()
    _, digest = write_repeat_trial_proposal(
        plan,
        output_path=args.output,
        review_path=args.review_output,
    )
    print(f"Repeat cases: {', '.join(case.case_id for case in plan.repeat_cases)}")
    print(f"Total trials per selected case: {plan.total_trials_per_selected_case}")
    print(f"Additional architecture executions: {plan.additional_repeat_architecture_execution_count}")
    print(f"Proposed hard cost cap: ${plan.budget.proposed_hard_cost_cap_usd:.2f}")
    print(f"Currently authorized spend: ${plan.budget.currently_authorized_cost_usd:.2f}")
    print(f"Plan SHA-256: {digest}")
    print("Provider execution authorized: no")
    print("Provider calls made: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
