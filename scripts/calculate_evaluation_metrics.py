"""Calculate Step 4.12 metrics from a saved, gold-isolated evaluation run."""

from __future__ import annotations

import argparse
from pathlib import Path

from rfp_orchestrator.evaluation_metrics import (
    DEFAULT_METRICS_OUTPUT_PATH,
    calculate_metrics,
    load_evaluation_run,
    write_metric_report,
)
from rfp_orchestrator.evaluation_runner import DEFAULT_DRY_RUN_OUTPUT_PATH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_DRY_RUN_OUTPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_METRICS_OUTPUT_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = calculate_metrics(load_evaluation_run(args.input))
    _, digest = write_metric_report(report, args.output)
    print(f"Report scope: {report.report_scope}")
    print(f"Cases: {report.case_count}")
    print(f"Architecture summaries: {len(report.architecture_summaries)}")
    print(f"Preserved failures: {report.failure_count}")
    print(f"Artifact SHA-256: {digest}")
    print("Gold scoring performed after execution: yes")
    print("Safe Completion Rate calculated: no (Step 4.13)")
    print("New provider calls made: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
