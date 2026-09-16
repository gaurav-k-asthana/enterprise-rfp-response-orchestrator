"""Record explicit approval of the exact Step 4.16 plan without running providers."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from rfp_orchestrator.evaluation_trials import (
    DEFAULT_REPEAT_TRIAL_APPROVAL_PATH,
    build_repeat_trial_approval_record,
    load_repeat_trial_plan,
    write_repeat_trial_approval,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-plan-sha256", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--approved-at", required=True)
    parser.add_argument("--authorized-cost-usd", required=True, type=float)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPEAT_TRIAL_APPROVAL_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    approval = build_repeat_trial_approval_record(
        load_repeat_trial_plan(),
        expected_proposal_sha256=args.expected_plan_sha256,
        reviewer=args.reviewer,
        approved_at=datetime.fromisoformat(args.approved_at),
        authorized_cost_usd=args.authorized_cost_usd,
    )
    _, digest = write_repeat_trial_approval(approval, output_path=args.output)
    print(f"Approved proposal SHA-256: {approval.proposal_sha256}")
    print(f"Reviewer: {approval.approved_by}")
    print(f"Authorized maximum: ${approval.authorized_cost_usd:.2f}")
    print(f"Approval record SHA-256: {digest}")
    print("Paid command approved: no")
    print("Provider calls made: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
