"""Guarded synthetic LangSmith trace used to verify Step 5.1 configuration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langsmith import Client

from rfp_orchestrator.config import Settings
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.langsmith_privacy import (
    LANGSMITH_CLIENT_PRIVACY_OPTIONS,
    PrivacyPreservingLangChainTracer,
)
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.sample_requirements import (
    DEFAULT_SAMPLE_RFP_PATH,
    load_sample_requirements,
)
from rfp_orchestrator.state import new_requirement_state

LANGSMITH_PROJECT = "enterprise-rfp-orchestrator"
TRACE_REQUIREMENT_ID = "RFP-001"
TRACE_RUN_NAME = "step-5-1-rfp-001-configuration-check"
TRACE_APPROVAL_TOKEN = "TRACE-SYNTHETIC-RFP-001"


class LangSmithConfigurationError(ValueError):
    """Raised before client creation when tracing configuration is unsafe or incomplete."""


@dataclass(frozen=True)
class LangSmithTraceReceipt:
    project_name: str
    run_name: str
    requirement_id: str
    final_status: str
    trace_url: str
    openai_calls_made: int = 0
    pinecone_calls_made: int = 0
    langsmith_trace_writes: int = 1


def validate_langsmith_settings(settings: Settings) -> None:
    """Fail closed before LangSmith initialization when Step 5.1 is incomplete."""

    if settings.langsmith_tracing is not True:
        raise LangSmithConfigurationError("LANGSMITH_TRACING must be true")
    if not settings.langsmith_api_key or not settings.langsmith_api_key.strip():
        raise LangSmithConfigurationError("LANGSMITH_API_KEY is missing")
    if settings.langsmith_project != LANGSMITH_PROJECT:
        raise LangSmithConfigurationError(
            f"LANGSMITH_PROJECT must be {LANGSMITH_PROJECT} for V1"
        )


def build_langsmith_callback(
    settings: Settings,
    *,
    client_factory: Callable[..., Any] = Client,
    tracer_factory: Callable[..., Any] = PrivacyPreservingLangChainTracer,
) -> tuple[Any, Any]:
    """Create an explicit client/callback pair without exporting the API key."""

    validate_langsmith_settings(settings)
    client = client_factory(
        api_key=settings.langsmith_api_key,
        **LANGSMITH_CLIENT_PRIVACY_OPTIONS,
    )
    tracer = tracer_factory(project_name=settings.langsmith_project, client=client)
    return client, tracer


def run_langsmith_trace_smoke(
    *,
    settings: Settings | None = None,
    client_factory: Callable[..., Any] = Client,
    tracer_factory: Callable[..., Any] = PrivacyPreservingLangChainTracer,
    kb_directory: Path | None = None,
) -> LangSmithTraceReceipt:
    """Send exactly one trace for the real offline RFP-001 graph path."""

    active_settings = settings or Settings()
    client, tracer = build_langsmith_callback(
        active_settings,
        client_factory=client_factory,
        tracer_factory=tracer_factory,
    )
    try:
        requirement = next(
            item
            for item in load_sample_requirements()
            if item.requirement_id == TRACE_REQUIREMENT_ID
        )
        graph = build_selected_fanout_graph(
            build_offline_retrievers(kb_directory or DEFAULT_SAMPLE_RFP_PATH.parent / "kb")
        )
        result = graph.invoke(
            new_requirement_state(
                "langsmith-step-5-1-synthetic",
                requirement.requirement_id,
                requirement.text,
            ),
            config={
                "callbacks": [tracer],
                "run_name": TRACE_RUN_NAME,
                "tags": ["step-5-1", "synthetic-data", "offline-graph"],
            },
        )
        if result.get("final_status") != "FINALIZED":
            raise RuntimeError("RFP-001 trace smoke did not finalize safely")
        client.flush(timeout=10)
        trace_url = tracer.get_run_url()
        if not isinstance(trace_url, str) or not trace_url.startswith("https://"):
            raise RuntimeError("LangSmith did not return a trace URL")
        return LangSmithTraceReceipt(
            project_name=active_settings.langsmith_project,
            run_name=TRACE_RUN_NAME,
            requirement_id=requirement.requirement_id,
            final_status=str(result["final_status"]),
            trace_url=trace_url,
        )
    finally:
        client.close(timeout=10)
