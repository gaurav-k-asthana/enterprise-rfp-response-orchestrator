"""Beginner-facing, fail-closed CLI for the exact provider comparison command."""

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
from rfp_orchestrator.provider_config import (
    OPENAI_EMBEDDING_MODEL,
    OPENAI_GENERATION_MODEL,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE,
    RETRIEVAL_TOP_K,
)
from rfp_orchestrator.provider_execution import (
    ProviderExecutionReceipt,
    execute_provider_runs,
)
from rfp_orchestrator.provider_execution_manifest import (
    DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH,
    EXECUTION_APPROVAL_TOKEN,
    ProviderExecutionManifest,
    ProviderExecutionManifestError,
    load_provider_execution_manifest,
    verify_manifest_against_current_files,
)

ExecutionFunction = Callable[..., ProviderExecutionReceipt]


def _validate_runtime(settings: Settings) -> None:
    values = {
        "OPENAI_API_KEY": settings.openai_api_key,
        "PINECONE_API_KEY": settings.pinecone_api_key,
    }
    missing = [name for name, value in values.items() if not value or not value.strip()]
    if missing:
        raise ProviderExecutionManifestError(
            "required credentials are missing: " + ", ".join(missing)
        )
    exact = {
        "OPENAI_MODEL": (settings.openai_model, OPENAI_GENERATION_MODEL),
        "OPENAI_EMBEDDING_MODEL": (
            settings.openai_embedding_model,
            OPENAI_EMBEDDING_MODEL,
        ),
        "PINECONE_INDEX": (settings.pinecone_index, PINECONE_INDEX_NAME),
        "PINECONE_NAMESPACE": (settings.pinecone_namespace, PINECONE_NAMESPACE),
        "RETRIEVAL_TOP_K": (settings.retrieval_top_k, RETRIEVAL_TOP_K),
        "MAX_RETRIEVAL_RETRIES": (settings.max_retrieval_retries, 2),
    }
    drifted = [name for name, (actual, expected) in exact.items() if actual != expected]
    if drifted:
        raise ProviderExecutionManifestError(
            "runtime configuration drifted: " + ", ".join(drifted)
        )
    if settings.provider_graph_calls_enabled is not True:
        raise ProviderExecutionManifestError(
            "PROVIDER_GRAPH_CALLS_ENABLED must be true for the exact approved command"
        )


def validate_exact_execution_request(
    *,
    execute: bool,
    approval_token: str,
    expected_manifest_sha256: str,
    manifest_path: Path,
    settings: Settings,
) -> ProviderExecutionManifest:
    if not execute:
        raise ProviderExecutionManifestError("provider execution requires --execute")
    if approval_token != EXECUTION_APPROVAL_TOKEN:
        raise ProviderExecutionManifestError("exact-command approval token does not match")
    if len(expected_manifest_sha256) != 64:
        raise ProviderExecutionManifestError("expected manifest SHA-256 is invalid")
    if not manifest_path.is_file():
        raise ProviderExecutionManifestError("reviewed provider manifest is missing")
    if file_sha256(manifest_path) != expected_manifest_sha256:
        raise ProviderExecutionManifestError("reviewed provider manifest SHA-256 does not match")
    manifest = load_provider_execution_manifest(manifest_path)
    verify_manifest_against_current_files(manifest)
    _validate_runtime(settings)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--manifest", type=Path, default=DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH)
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
        manifest = validate_exact_execution_request(
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
        )
    except ProviderExecutionManifestError as error:
        print(
            json.dumps(
                {"status": "refused", "error_type": type(error).__name__, "message": str(error)},
                sort_keys=True,
            ),
            file=error_stream,
        )
        return 2
    except Exception as error:  # noqa: BLE001 - provider failures remain redacted here.
        print(
            json.dumps({"status": "failed", "error_type": type(error).__name__}, sort_keys=True),
            file=error_stream,
        )
        return 1

    print(json.dumps(receipt.model_dump(mode="json"), indent=2, sort_keys=True), file=output_stream)
    return 0
