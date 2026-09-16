"""Validate LangSmith configuration or send one approved synthetic graph trace."""

from __future__ import annotations

import argparse

from rfp_orchestrator.config import Settings
from rfp_orchestrator.langsmith_smoke import (
    LANGSMITH_PROJECT,
    TRACE_APPROVAL_TOKEN,
    LangSmithConfigurationError,
    run_langsmith_trace_smoke,
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
    print("LangSmith API key: present (value hidden)")
    if not args.execute:
        print("Dry check only. LangSmith client initialized: no")
        print("Network calls made: 0")
        return 0
    if args.approval_token != TRACE_APPROVAL_TOKEN:
        print("Execution refused: exact approval token is required")
        print("LangSmith client initialized: no")
        print("Network calls made: 0")
        return 2

    receipt = run_langsmith_trace_smoke(settings=settings)
    print(f"Trace run: {receipt.run_name}")
    print(f"Requirement: {receipt.requirement_id} (synthetic)")
    print(f"Final status: {receipt.final_status}")
    print(f"Trace URL: {receipt.trace_url}")
    print("OpenAI calls made: 0")
    print("Pinecone calls made: 0")
    print("LangSmith traces written: 1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
