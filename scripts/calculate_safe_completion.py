"""Calculate Step 4.13 Safe Completion Rate from one saved evaluation run."""

from __future__ import annotations

import argparse
from pathlib import Path

from rfp_orchestrator.evaluation_metrics import load_evaluation_run
from rfp_orchestrator.evaluation_runner import DEFAULT_DRY_RUN_OUTPUT_PATH
from rfp_orchestrator.safe_completion import (
    DEFAULT_SAFE_COMPLETION_OUTPUT_PATH,
    calculate_safe_completion,
    write_safe_completion_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_DRY_RUN_OUTPUT_PATH)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_SAFE_COMPLETION_OUTPUT_PATH,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = calculate_safe_completion(load_evaluation_run(args.input))
    _, digest = write_safe_completion_report(report, args.output)
    print(f"Report scope: {report.report_scope}")
    print(f"Cases per architecture: {report.case_count}")
    for summary in report.architecture_summaries:
        print(
            f"{summary.architecture.value}: "
            f"{summary.safe_completion_rate.numerator}/"
            f"{summary.safe_completion_rate.denominator} "
            f"({summary.safe_completion_rate.value:.3f})"
        )
    print(f"Artifact SHA-256: {digest}")
    print("New architecture or provider calls made: 0")
    print("Comparative conclusions allowed: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
