"""Generate the Step 4.18 evidence-bounded architecture tradeoff analysis."""

from __future__ import annotations

import argparse
from pathlib import Path

from rfp_orchestrator.evaluation_tradeoffs import (
    DEFAULT_TRADEOFF_JSON_PATH,
    DEFAULT_TRADEOFF_MARKDOWN_PATH,
    build_tradeoff_analysis,
    write_tradeoff_analysis,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_TRADEOFF_JSON_PATH)
    parser.add_argument(
        "--markdown-output", type=Path, default=DEFAULT_TRADEOFF_MARKDOWN_PATH
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    analysis = build_tradeoff_analysis()
    json_digest, markdown_digest = write_tradeoff_analysis(
        analysis,
        json_path=args.json_output,
        markdown_path=args.markdown_output,
    )
    print(f"Analysis scope: {analysis.analysis_scope}")
    print("Comparative winner: none")
    print("Phase 4 exit gate passed: no")
    print(f"JSON SHA-256: {json_digest}")
    print(f"Markdown SHA-256: {markdown_digest}")
    print("New architecture or provider calls made: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
