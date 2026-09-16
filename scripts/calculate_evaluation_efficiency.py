"""Generate Step 4.14 usage, latency, and estimated-cost summaries."""

from __future__ import annotations

import argparse
from pathlib import Path

from rfp_orchestrator.evaluation_efficiency import (
    DEFAULT_EFFICIENCY_OUTPUT_PATH,
    DEFAULT_PRICING_SNAPSHOT_PATH,
    build_pricing_snapshot,
    calculate_efficiency,
    write_efficiency_report,
    write_pricing_snapshot,
)
from rfp_orchestrator.evaluation_metrics import load_evaluation_run
from rfp_orchestrator.evaluation_runner import DEFAULT_DRY_RUN_OUTPUT_PATH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_DRY_RUN_OUTPUT_PATH)
    parser.add_argument("--output", type=Path, default=DEFAULT_EFFICIENCY_OUTPUT_PATH)
    parser.add_argument(
        "--pricing-output",
        type=Path,
        default=DEFAULT_PRICING_SNAPSHOT_PATH,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    pricing = build_pricing_snapshot()
    _, pricing_digest = write_pricing_snapshot(pricing, args.pricing_output)
    report = calculate_efficiency(load_evaluation_run(args.input), pricing)
    _, report_digest = write_efficiency_report(report, args.output)
    print(f"Report scope: {report.report_scope}")
    print(f"Cases per architecture: {report.case_count}")
    for summary in report.architecture_summaries:
        print(
            f"{summary.architecture.value}: calls={summary.model_calls_total}, "
            f"tokens={summary.total_tokens}, "
            f"mean_latency_ms={summary.latency_ms.mean}, "
            f"estimated_cost_usd={summary.estimated_cost_usd_total:.8f}"
        )
    print(f"Pricing snapshot SHA-256: {pricing_digest}")
    print(f"Efficiency artifact SHA-256: {report_digest}")
    print("New provider calls made: 0")
    print("Comparative conclusions allowed: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
