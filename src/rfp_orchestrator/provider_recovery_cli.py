"""Fail-closed CLI for the separately approved provider recovery command."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import TextIO

from rfp_orchestrator.config import Settings
from rfp_orchestrator.evaluation_freeze import file_sha256
from rfp_orchestrator.evaluation_trials import load_repeat_trial_plan
from rfp_orchestrator.provider_execution import (
    ProviderExecutionReceipt,
    execute_provider_runs,
)
from rfp_orchestrator.provider_execution_cli import _validate_runtime
from rfp_orchestrator.provider_execution_manifest import ProviderExecutionManifestError
from rfp_orchestrator.provider_recovery_manifest import (
    DEFAULT_PROVIDER_RECOVERY_MANIFEST_PATH,
    RECOVERY_APPROVAL_TOKEN,
    ProviderRecoveryManifest,
    ProviderRecoveryManifestError,
    load_provider_recovery_manifest,
    verify_recovery_manifest_against_current_files,
)

ExecutionFunction = Callable[..., ProviderExecutionReceipt]


def validate_exact_recovery_request(
    *,
    execute: bool,
    approval_token: str,
    expected_manifest_sha256: str,
    manifest_path: Path,
    settings: Settings,
) -> ProviderRecoveryManifest:
    if not execute:
        raise ProviderRecoveryManifestError("provider recovery requires --execute")
    if approval_token != RECOVERY_APPROVAL_TOKEN:
        raise ProviderRecoveryManifestError("recovery approval token does not match")
    if len(expected_manifest_sha256) != 64:
        raise ProviderRecoveryManifestError("expected recovery manifest SHA-256 is invalid")
    if not manifest_path.is_file():
        raise ProviderRecoveryManifestError("reviewed recovery manifest is missing")
    if file_sha256(manifest_path) != expected_manifest_sha256:
        raise ProviderRecoveryManifestError("reviewed recovery manifest SHA-256 does not match")
    manifest = load_provider_recovery_manifest(manifest_path)
    verify_recovery_manifest_against_current_files(manifest)
    _validate_runtime(settings)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_PROVIDER_RECOVERY_MANIFEST_PATH)
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--approval-token")
    return parser


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    execution_function: ExecutionFunction = execute_provider_runs,
    output_stream: TextIO = sys.stdout,
    error_stream: TextIO = sys.stderr,
) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    active_settings = settings or Settings()
    try:
        manifest = validate_exact_recovery_request(
            execute=args.execute,
            approval_token=args.approval_token or "",
            expected_manifest_sha256=args.expected_manifest_sha256 or "",
            manifest_path=args.manifest,
            settings=active_settings,
        )
        receipt = execution_function(
            manifest_sha256=args.expected_manifest_sha256,
            run_specifications=manifest.runs,
            budget=load_repeat_trial_plan().budget,
            settings=active_settings,
            initial_budget_usage=manifest.prior_usage,
        )
    except (ProviderRecoveryManifestError, ProviderExecutionManifestError) as error:
        print(
            json.dumps(
                {"status": "refused", "error_type": type(error).__name__, "message": str(error)},
                sort_keys=True,
            ),
            file=error_stream,
        )
        return 2
    except Exception as error:  # noqa: BLE001 - provider failures stay redacted here.
        print(
            json.dumps({"status": "failed", "error_type": type(error).__name__}, sort_keys=True),
            file=error_stream,
        )
        return 1

    print(json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True), file=output_stream)
    return 0
