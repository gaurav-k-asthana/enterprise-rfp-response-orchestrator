"""Record approval of the exact Step 4.G8 final analysis without provider calls."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from rfp_orchestrator.provider_final_approval import (
    DEFAULT_FINAL_APPROVAL_PATH,
    build_provider_final_approval,
    write_provider_final_approval,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-markdown-sha256", required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--approved-at", required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_FINAL_APPROVAL_PATH)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    approval = build_provider_final_approval(
        expected_markdown_sha256=args.expected_markdown_sha256,
        reviewer=args.reviewer,
        approved_at=datetime.fromisoformat(args.approved_at),
    )
    _, digest = write_provider_final_approval(approval, output_path=args.output)
    print(f"Approved Markdown SHA-256: {approval.analysis_markdown_sha256}")
    print(f"Reviewer: {approval.approved_by}")
    print(f"Approval record SHA-256: {digest}")
    print("Phase 4 exit gate passed: yes")
    print("Provider calls made: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
