"""Generate Step 4.17 side-by-side tables from one canonical raw run."""

from __future__ import annotations

import argparse
from pathlib import Path

from rfp_orchestrator.evaluation_metrics import load_evaluation_run
from rfp_orchestrator.evaluation_tables import (
    DEFAULT_CANONICAL_RAW_RUN_PATH,
    DEFAULT_COMPARISON_TABLE_JSON_PATH,
    DEFAULT_COMPARISON_TABLE_MARKDOWN_PATH,
    generate_comparison_tables,
    write_comparison_tables,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_CANONICAL_RAW_RUN_PATH)
    parser.add_argument(
        "--json-output", type=Path, default=DEFAULT_COMPARISON_TABLE_JSON_PATH
    )
    parser.add_argument(
        "--markdown-output",
        type=Path,
        default=DEFAULT_COMPARISON_TABLE_MARKDOWN_PATH,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = generate_comparison_tables(load_evaluation_run(args.input))
    json_digest, markdown_digest = write_comparison_tables(
        report,
        json_path=args.json_output,
        markdown_path=args.markdown_output,
    )
    print(f"Table scope: {report.table_scope.value}")
    print(f"Cases: {report.case_count}")
    print(f"Preserved failures: {report.failure_count}")
    print(f"JSON SHA-256: {json_digest}")
    print(f"Markdown SHA-256: {markdown_digest}")
    print("Manual values entered: no")
    print("New architecture or provider calls made: 0")
    print("Comparative conclusions allowed: no")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
