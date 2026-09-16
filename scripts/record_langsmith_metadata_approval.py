"""Record Step 5.2 metadata review without writing another LangSmith trace."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from rfp_orchestrator.langsmith_metadata_approval import (
    DEFAULT_METADATA_TRACE_APPROVAL_PATH,
    build_langsmith_metadata_approval,
    write_langsmith_metadata_approval,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-receipt-sha256", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_METADATA_TRACE_APPROVAL_PATH
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    approval = build_langsmith_metadata_approval(
        expected_receipt_sha256=args.expected_receipt_sha256,
        reviewer=args.reviewer,
        reviewed_at=datetime.fromisoformat(args.reviewed_at),
    )
    _, digest = write_langsmith_metadata_approval(approval, output_path=args.output)
    print(f"Reviewed receipt SHA-256: {approval.receipt_sha256}")
    print(f"Reviewer: {approval.reviewed_by}")
    print(f"Approval record SHA-256: {digest}")
    print("Additional LangSmith traces written: 0")
    print("Step 5.2 complete: yes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
