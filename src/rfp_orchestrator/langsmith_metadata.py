"""Safe operational metadata for the Step 5.2 LangSmith trace boundary."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

from rfp_orchestrator.config import Settings
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.langsmith_privacy import PrivacyPreservingLangChainTracer
from rfp_orchestrator.langsmith_smoke import (
    LANGSMITH_PROJECT,
    build_langsmith_callback,
)
from rfp_orchestrator.models import Domain, RequirementStatus, RiskClass, StrategyType
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.sample_requirements import (
    DEFAULT_SAMPLE_RFP_PATH,
    load_sample_requirements,
)
from rfp_orchestrator.state import new_requirement_state

METADATA_TRACE_REQUIREMENT_ID = "RFP-002"
METADATA_TRACE_CASE_ID = "langsmith-step-5-2-synthetic"
METADATA_TRACE_RUN_NAME = "step-5-2-rfp-002-metadata-check"
METADATA_TRACE_APPROVAL_TOKEN = "TRACE-METADATA-SYNTHETIC-RFP-002"
TRACE_METADATA_SCHEMA_VERSION = "1"


class TraceMetadataError(ValueError):
    """Raised if a graph result cannot be represented as safe trace metadata."""


class TraceOperationalMetadata(BaseModel):
    """The complete Step 5.2 allowlist for searchable trace metadata."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_metadata_schema_version: str = TRACE_METADATA_SCHEMA_VERSION
    case_id: str = Field(min_length=1, max_length=128)
    requirement_id: str = Field(pattern=r"^RFP-\d{3}$")
    strategy: StrategyType
    selected_specialists: list[Domain]
    retry_count: int = Field(ge=0, le=2)
    risk_classes: list[RiskClass]
    final_status: RequirementStatus

    def as_langsmith_metadata(self) -> dict[str, object]:
        """Use stable, namespaced keys and only primitive/enum values."""

        return {
            "rfp_trace_metadata_schema_version": self.trace_metadata_schema_version,
            "rfp_case_id": self.case_id,
            "rfp_requirement_id": self.requirement_id,
            "rfp_strategy": self.strategy.value,
            "rfp_selected_specialists": [item.value for item in self.selected_specialists],
            "rfp_retry_count": self.retry_count,
            "rfp_risk_classes": [item.value for item in self.risk_classes],
            "rfp_final_status": self.final_status.value,
        }


@dataclass(frozen=True)
class LangSmithMetadataTraceReceipt:
    project_name: str
    run_name: str
    trace_id: str
    trace_url: str
    metadata: TraceOperationalMetadata
    openai_calls_made: int = 0
    pinecone_calls_made: int = 0
    langsmith_root_traces_written: int = 1
    langsmith_metadata_updates: int = 0
    local_graph_executions: int = 2


def trace_metadata_from_state(state: Mapping[str, object]) -> TraceOperationalMetadata:
    """Select and validate the allowlisted labels from completed graph state."""

    try:
        return TraceOperationalMetadata.model_validate(
            {
                "case_id": state["case_id"],
                "requirement_id": state["requirement_id"],
                "strategy": state["strategy"],
                "selected_specialists": state["selected_specialists"],
                "retry_count": state["retry_count"],
                "risk_classes": state["risk_classes"],
                "final_status": state["final_status"],
            }
        )
    except (KeyError, TypeError, ValueError) as error:
        raise TraceMetadataError("completed graph state lacks valid trace metadata") from error


def run_langsmith_metadata_trace(
    *,
    settings: Settings | None = None,
    client_factory: Callable[..., Any] | None = None,
    tracer_factory: Callable[..., Any] = PrivacyPreservingLangChainTracer,
    kb_directory: Path | None = None,
    trace_id: UUID | None = None,
) -> LangSmithMetadataTraceReceipt:
    """Write one RFP-002 trace then append the post-run allowlisted metadata."""

    active_settings = settings or Settings()
    requirement = next(
        item
        for item in load_sample_requirements()
        if item.requirement_id == METADATA_TRACE_REQUIREMENT_ID
    )
    retrievers = build_offline_retrievers(
        kb_directory or DEFAULT_SAMPLE_RFP_PATH.parent / "kb"
    )
    preflight_result = build_selected_fanout_graph(retrievers).invoke(
        new_requirement_state(
            METADATA_TRACE_CASE_ID,
            requirement.requirement_id,
            requirement.text,
        )
    )
    metadata = trace_metadata_from_state(preflight_result)
    callback_args: dict[str, Any] = {"tracer_factory": tracer_factory}
    if client_factory is not None:
        callback_args["client_factory"] = client_factory
    client, tracer = build_langsmith_callback(active_settings, **callback_args)
    root_run_id = trace_id or uuid4()
    try:
        graph = build_selected_fanout_graph(retrievers)
        result = graph.invoke(
            new_requirement_state(
                METADATA_TRACE_CASE_ID,
                requirement.requirement_id,
                requirement.text,
            ),
            config={
                "callbacks": [tracer],
                "run_id": root_run_id,
                "run_name": METADATA_TRACE_RUN_NAME,
                "tags": ["step-5-2", "synthetic-data", "offline-graph", "metadata"],
                "metadata": metadata.as_langsmith_metadata(),
            },
        )
        if trace_metadata_from_state(result) != metadata:
            raise TraceMetadataError(
                "graph metadata changed between local preflight and traced execution"
            )
        client.flush(timeout=10)
        trace_url = tracer.get_run_url()
        if not isinstance(trace_url, str) or not trace_url.startswith("https://"):
            raise RuntimeError("LangSmith did not return a trace URL")
        return LangSmithMetadataTraceReceipt(
            project_name=LANGSMITH_PROJECT,
            run_name=METADATA_TRACE_RUN_NAME,
            trace_id=str(root_run_id),
            trace_url=trace_url,
            metadata=metadata,
        )
    finally:
        client.close(timeout=10)
