"""Archive one saved evaluation run into an immutable raw-output bundle."""

from __future__ import annotations

import argparse
from pathlib import Path

from rfp_orchestrator.evaluation_archive import (
    DEFAULT_RAW_ARCHIVE_ROOT,
    ArchivePurpose,
    archive_evaluation_run,
    build_controlled_failure_fixture,
)
from rfp_orchestrator.evaluation_metrics import load_evaluation_run
from rfp_orchestrator.evaluation_runner import DEFAULT_DRY_RUN_OUTPUT_PATH


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_DRY_RUN_OUTPUT_PATH)
    parser.add_argument("--archive-root", type=Path, default=DEFAULT_RAW_ARCHIVE_ROOT)
    parser.add_argument(
        "--include-controlled-failure-fixture",
        action="store_true",
        help="Also archive a labeled non-result fixture proving failure preservation.",
    )
    return parser


def _print_result(label: str, target: Path, manifest_digest: str) -> None:
    print(f"{label} directory: {target}")
    print(f"{label} manifest SHA-256: {manifest_digest}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    target, _, digest = archive_evaluation_run(
        load_evaluation_run(args.input),
        archive_root=args.archive_root,
    )
    _print_result("Raw run", target, digest)
    if args.include_controlled_failure_fixture:
        fixture_target, _, fixture_digest = archive_evaluation_run(
            build_controlled_failure_fixture(),
            archive_root=args.archive_root,
            purpose=ArchivePurpose.CONTROLLED_FAILURE_FIXTURE,
        )
        _print_result("Controlled failure fixture", fixture_target, fixture_digest)
    print("Existing bundles are verified, never overwritten.")
    print("New architecture or provider calls made: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
