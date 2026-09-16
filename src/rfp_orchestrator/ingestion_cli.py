"""Beginner-facing CLI boundaries for dry-run preparation and approved upload."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import TextIO

from rfp_orchestrator.config import Settings
from rfp_orchestrator.ingestion import (
    DEFAULT_CORPUS_DIRECTORY,
    DEFAULT_MANIFEST_PATH,
    IngestionApprovalError,
    IngestionError,
    OpenAIClientFactory,
    PineconeIndexFactory,
    _default_openai_client_factory,
    _default_pinecone_index_factory,
    build_ingestion_plan,
    execute_reviewed_ingestion,
    load_reviewed_manifest,
    validate_runtime_settings,
    write_manifest,
)


def _safe_error(error: Exception, *, include_message: bool) -> dict[str, str]:
    payload = {"status": "refused", "error_type": type(error).__name__}
    if include_message:
        payload["message"] = str(error)
    return payload


def prepare_main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    output_stream: TextIO = sys.stdout,
    error_stream: TextIO = sys.stderr,
) -> int:
    """Create a local manifest without provider clients or network access."""

    parser = argparse.ArgumentParser(description="Prepare the V1 ingestion dry-run manifest")
    parser.add_argument("--corpus-directory", type=Path, default=DEFAULT_CORPUS_DIRECTORY)
    parser.add_argument("--output", type=Path, default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        validate_runtime_settings(settings or Settings(), require_secrets=False)
        plan = build_ingestion_plan(args.corpus_directory)
        manifest = write_manifest(plan, args.output)
    except IngestionError as error:
        print(json.dumps(_safe_error(error, include_message=True), sort_keys=True), file=error_stream)
        return 2
    except Exception as error:  # noqa: BLE001 - CLI boundary redacts unexpected details.
        print(json.dumps(_safe_error(error, include_message=False), sort_keys=True), file=error_stream)
        return 1

    summary = {
        "status": "dry_run_ready",
        "manifest_path": str(args.output),
        "manifest_sha256": manifest["manifest_sha256"],
        "document_count": manifest["document_count"],
        "record_count": manifest["record_count"],
        "hybrid_record_count": manifest["hybrid_record_count"],
        "dense_only_record_count": manifest["dense_only_record_count"],
        "network_calls_made": 0,
        "upload_authorized": False,
    }
    print(json.dumps(summary, indent=2, sort_keys=True), file=output_stream)
    return 0


def upload_main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    openai_client_factory: OpenAIClientFactory = _default_openai_client_factory,
    pinecone_index_factory: PineconeIndexFactory = _default_pinecone_index_factory,
    output_stream: TextIO = sys.stdout,
    error_stream: TextIO = sys.stderr,
) -> int:
    """Upload only after three independent, reviewed CLI guards are satisfied."""

    parser = argparse.ArgumentParser(description="Upload one explicitly approved V1 manifest")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approval-token")
    parser.add_argument("--expected-manifest-sha256")
    parser.add_argument("--corpus-directory", type=Path, default=DEFAULT_CORPUS_DIRECTORY)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        if not args.execute:
            raise IngestionApprovalError(
                "upload is disabled unless --execute is supplied after explicit review"
            )
        plan = build_ingestion_plan(args.corpus_directory)
        reviewed_manifest = load_reviewed_manifest(args.manifest)
        result = execute_reviewed_ingestion(
            plan=plan,
            reviewed_manifest=reviewed_manifest,
            expected_manifest_sha256=args.expected_manifest_sha256 or "",
            approval_token=args.approval_token or "",
            settings=settings,
            openai_client_factory=openai_client_factory,
            pinecone_index_factory=pinecone_index_factory,
        )
    except IngestionError as error:
        print(json.dumps(_safe_error(error, include_message=True), sort_keys=True), file=error_stream)
        return 2
    except Exception as error:  # noqa: BLE001 - provider details may contain sensitive context.
        print(json.dumps(_safe_error(error, include_message=False), sort_keys=True), file=error_stream)
        return 1

    print(json.dumps(result.public_fields(), indent=2, sort_keys=True), file=output_stream)
    return 0

