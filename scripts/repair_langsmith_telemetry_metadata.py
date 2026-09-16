"""Dry-check or perform the hash-bound Step 5.3 metadata-only repair."""

from __future__ import annotations

import argparse

from rfp_orchestrator.config import Settings
from rfp_orchestrator.langsmith_smoke import (
    LANGSMITH_PROJECT,
    LangSmithConfigurationError,
    validate_langsmith_settings,
)
from rfp_orchestrator.langsmith_telemetry_repair import (
    TELEMETRY_RECEIPT_SHA256,
    TELEMETRY_REPAIR_APPROVAL_TOKEN,
    TELEMETRY_REPAIR_DISABLED_REASON,
    TELEMETRY_TRACE_ID,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--approval-token")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = Settings()
    try:
        validate_langsmith_settings(settings)
    except LangSmithConfigurationError as error:
        print(f"Configuration not ready: {error}")
        print("LangSmith client initialized: no")
        print("Network calls made: 0")
        return 2

    print(f"LangSmith project: {LANGSMITH_PROJECT}")
    print(f"Existing trace ID: {TELEMETRY_TRACE_ID}")
    print(f"Bound receipt SHA-256: {TELEMETRY_RECEIPT_SHA256}")
    print("Operation: one metadata-only update; no graph execution and no new trace")
    if not args.execute:
        print("Dry check only. LangSmith client initialized: no")
        print("Network calls made: 0")
        return 0
    if args.approval_token != TELEMETRY_REPAIR_APPROVAL_TOKEN:
        print("Execution refused: exact repair approval token is required")
        print("LangSmith client initialized: no")
        print("Network calls made: 0")
        return 2

    print(f"Execution refused: {TELEMETRY_REPAIR_DISABLED_REASON}")
    print("LangSmith metadata updates: 0")
    print("LangSmith root traces written: 0")
    print("OpenAI calls made: 0")
    print("Pinecone calls made: 0")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
