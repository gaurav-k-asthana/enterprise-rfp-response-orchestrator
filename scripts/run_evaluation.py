"""Run the guarded evaluation workflow without exposing frozen gold to executors."""

from __future__ import annotations

import argparse
from pathlib import Path

from rfp_orchestrator.evaluation_runner import (
    DEFAULT_DRY_RUN_OUTPUT_PATH,
    EvaluationRunMode,
    EvaluationRunnerError,
    build_step_4_11_dry_run,
    write_evaluation_run,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        required=True,
        choices=["offline-dry-run", "provider-comparison"],
    )
    parser.add_argument("--case-id", required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_DRY_RUN_OUTPUT_PATH,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.mode == "provider-comparison":
        raise EvaluationRunnerError(
            "provider comparison is disabled until a reviewed execution budget and explicit approval exist"
        )
    if args.case_id != "EVAL-001":
        raise EvaluationRunnerError(
            "Step 4.11 offline dry mode is intentionally limited to EVAL-001"
        )
    artifact = build_step_4_11_dry_run()
    _, digest = write_evaluation_run(artifact, args.output)
    print(f"Run mode: {EvaluationRunMode.OFFLINE_DRY_RUN.value}")
    print("Cases: 1")
    print("Architecture records: 2")
    print(f"Status: {artifact.status.value}")
    print(f"Artifact SHA-256: {digest}")
    print("Gold scoring performed: no")
    print("Provider calls made: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
