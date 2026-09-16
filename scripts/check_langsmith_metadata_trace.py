"""Validate Step 5.2 metadata configuration or write one approved synthetic trace."""

from __future__ import annotations

import argparse

from rfp_orchestrator.config import Settings
from rfp_orchestrator.langsmith_metadata import (
    METADATA_TRACE_APPROVAL_TOKEN,
    run_langsmith_metadata_trace,
)
from rfp_orchestrator.langsmith_smoke import (
    LANGSMITH_PROJECT,
    LangSmithConfigurationError,
    validate_langsmith_settings,
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
    print("Metadata allowlist: case, requirement, strategy, specialists, retries, risks, status")
    if not args.execute:
        print("Dry check only. LangSmith client initialized: no")
        print("Network calls made: 0")
        return 0
    if args.approval_token != METADATA_TRACE_APPROVAL_TOKEN:
        print("Execution refused: exact approval token is required")
        print("LangSmith client initialized: no")
        print("Network calls made: 0")
        return 2

    receipt = run_langsmith_metadata_trace(settings=settings)
    print(f"Trace run: {receipt.run_name}")
    print(f"Trace URL: {receipt.trace_url}")
    for key, value in receipt.metadata.as_langsmith_metadata().items():
        print(f"{key}: {value}")
    print("OpenAI calls made: 0")
    print("Pinecone calls made: 0")
    print("LangSmith root traces written: 1")
    print("LangSmith metadata updates: 1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
