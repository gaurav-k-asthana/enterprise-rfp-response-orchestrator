"""Safe latency, token, and error telemetry for Step 5.3."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.config import Settings
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.langsmith_metadata import (
    TraceOperationalMetadata,
    trace_metadata_from_state,
)
from rfp_orchestrator.langsmith_smoke import LANGSMITH_PROJECT, build_langsmith_callback
from rfp_orchestrator.retrieval import OfflineSpecialistRetrievers, build_offline_retrievers
from rfp_orchestrator.sample_requirements import (
    DEFAULT_SAMPLE_RFP_PATH,
    load_sample_requirements,
)
from rfp_orchestrator.state import new_requirement_state

TELEMETRY_TRACE_REQUIREMENT_ID = "RFP-003"
TELEMETRY_TRACE_CASE_ID = "langsmith-step-5-3-synthetic"
TELEMETRY_TRACE_RUN_NAME = "step-5-3-rfp-003-safe-telemetry-check-v2"
TELEMETRY_TRACE_APPROVAL_TOKEN = "TRACE-TELEMETRY-SYNTHETIC-RFP-003-V2"
TRACE_TELEMETRY_SCHEMA_VERSION = "1"
TRACE_TELEMETRY_DECLARATION_SCHEMA_VERSION = "2"


class TraceErrorCode(str, Enum):
    """Fixed error categories; exception messages never become telemetry."""

    GRAPH_EXECUTION_FAILED = "GRAPH_EXECUTION_FAILED"


class TraceTelemetryDeclaration(BaseModel):
    """Values attached at trace start plus native capture-mode declarations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_telemetry_schema_version: str = TRACE_TELEMETRY_DECLARATION_SCHEMA_VERSION
    latency_capture_mode: Literal["LANGSMITH_NATIVE"] = "LANGSMITH_NATIVE"
    provider_calls: Literal[0] = 0
    token_usage_observed: Literal[True] = True
    input_tokens: Literal[0] = 0
    output_tokens: Literal[0] = 0
    total_tokens: Literal[0] = 0
    error_capture_mode: Literal["LANGSMITH_NATIVE_REDACTED"] = (
        "LANGSMITH_NATIVE_REDACTED"
    )
    raw_inputs_logged: Literal[False] = False
    raw_outputs_logged: Literal[False] = False
    raw_error_details_logged: Literal[False] = False

    def as_langsmith_metadata(self) -> dict[str, object]:
        return {
            "rfp_trace_telemetry_schema_version": self.trace_telemetry_schema_version,
            "rfp_latency_capture_mode": self.latency_capture_mode,
            "rfp_provider_calls": self.provider_calls,
            "rfp_token_usage_observed": self.token_usage_observed,
            "rfp_input_tokens": self.input_tokens,
            "rfp_output_tokens": self.output_tokens,
            "rfp_total_tokens": self.total_tokens,
            "rfp_error_capture_mode": self.error_capture_mode,
            "rfp_raw_inputs_logged": self.raw_inputs_logged,
            "rfp_raw_outputs_logged": self.raw_outputs_logged,
            "rfp_raw_error_details_logged": self.raw_error_details_logged,
        }


class TraceTokenUsage(BaseModel):
    """Exact aggregate usage, or an explicit unavailable observation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider_calls: int = Field(ge=0)
    token_usage_observed: bool
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def usage_is_honest(self) -> TraceTokenUsage:
        counts = (self.input_tokens, self.output_tokens, self.total_tokens)
        if self.token_usage_observed:
            if any(value is None for value in counts):
                raise ValueError("observed token usage requires all token counts")
            if self.total_tokens != self.input_tokens + self.output_tokens:  # type: ignore[operator]
                raise ValueError("total tokens must equal input plus output tokens")
        elif any(value is not None for value in counts):
            raise ValueError("unobserved token usage cannot contain fabricated counts")
        if self.provider_calls == 0 and counts != (0, 0, 0):
            raise ValueError("zero provider calls require observed zero token usage")
        return self

    @classmethod
    def offline_zero(cls) -> TraceTokenUsage:
        return cls(
            provider_calls=0,
            token_usage_observed=True,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
        )


class TraceTelemetry(BaseModel):
    """Complete allowlist for one root run's operational telemetry."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    trace_telemetry_schema_version: str = TRACE_TELEMETRY_SCHEMA_VERSION
    latency_ms: float = Field(ge=0)
    provider_calls: int = Field(ge=0)
    token_usage_observed: bool
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    error_count: Literal[0, 1]
    error_code: TraceErrorCode | None
    raw_inputs_logged: Literal[False] = False
    raw_outputs_logged: Literal[False] = False
    raw_error_details_logged: Literal[False] = False

    @model_validator(mode="after")
    def telemetry_is_consistent(self) -> TraceTelemetry:
        TraceTokenUsage(
            provider_calls=self.provider_calls,
            token_usage_observed=self.token_usage_observed,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
            total_tokens=self.total_tokens,
        )
        if (self.error_count == 0) is not (self.error_code is None):
            raise ValueError("error count and fixed error code must agree")
        return self

    def as_langsmith_metadata(self) -> dict[str, object]:
        return {
            "rfp_trace_telemetry_schema_version": self.trace_telemetry_schema_version,
            "rfp_latency_ms": self.latency_ms,
            "rfp_provider_calls": self.provider_calls,
            "rfp_token_usage_observed": self.token_usage_observed,
            "rfp_input_tokens": self.input_tokens,
            "rfp_output_tokens": self.output_tokens,
            "rfp_total_tokens": self.total_tokens,
            "rfp_error_count": self.error_count,
            "rfp_error_code": self.error_code.value if self.error_code else None,
            "rfp_raw_inputs_logged": self.raw_inputs_logged,
            "rfp_raw_outputs_logged": self.raw_outputs_logged,
            "rfp_raw_error_details_logged": self.raw_error_details_logged,
        }


class TraceGraph(Protocol):
    def invoke(
        self,
        input: Mapping[str, object],
        config: Mapping[str, object],
    ) -> Mapping[str, object]: ...


class SafeTelemetryTraceError(RuntimeError):
    """Raised with fixed copy after a telemetry trace execution fails."""


@dataclass(frozen=True)
class LangSmithTelemetryTraceReceipt:
    project_name: str
    run_name: str
    trace_id: str
    trace_url: str
    metadata: TraceOperationalMetadata
    declaration: TraceTelemetryDeclaration
    telemetry: TraceTelemetry
    local_graph_executions: int = 2
    openai_calls_made: int = 0
    pinecone_calls_made: int = 0
    langsmith_root_traces_written: int = 1
    langsmith_metadata_updates: int = 0


def build_trace_telemetry(
    *,
    elapsed_seconds: float,
    usage: TraceTokenUsage,
    error_code: TraceErrorCode | None = None,
) -> TraceTelemetry:
    """Build telemetry without accepting raw input, output, or exception text."""

    return TraceTelemetry(
        latency_ms=round(max(0.0, elapsed_seconds * 1_000), 3),
        provider_calls=usage.provider_calls,
        token_usage_observed=usage.token_usage_observed,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        error_count=1 if error_code else 0,
        error_code=error_code,
    )


def _combined_metadata(
    operational: TraceOperationalMetadata,
    declaration: TraceTelemetryDeclaration,
) -> dict[str, object]:
    return {
        **operational.as_langsmith_metadata(),
        **declaration.as_langsmith_metadata(),
    }


def run_langsmith_telemetry_trace(
    *,
    settings: Settings | None = None,
    client_factory: Callable[..., Any] | None = None,
    tracer_factory: Callable[..., Any] | None = None,
    graph_factory: Callable[[OfflineSpecialistRetrievers], TraceGraph] = (
        build_selected_fanout_graph
    ),
    kb_directory: Path | None = None,
    trace_id: UUID | None = None,
    timer: Callable[[], float] = perf_counter,
) -> LangSmithTelemetryTraceReceipt:
    """Write one privacy-preserving RFP-003 trace with safe root telemetry."""

    active_settings = settings or Settings()
    usage = TraceTokenUsage.offline_zero()
    requirement = next(
        item
        for item in load_sample_requirements()
        if item.requirement_id == TELEMETRY_TRACE_REQUIREMENT_ID
    )
    retrievers = build_offline_retrievers(
        kb_directory or DEFAULT_SAMPLE_RFP_PATH.parent / "kb"
    )
    preflight_result = graph_factory(retrievers).invoke(
        new_requirement_state(
            TELEMETRY_TRACE_CASE_ID,
            requirement.requirement_id,
            requirement.text,
        ),
        config={},
    )
    operational = trace_metadata_from_state(preflight_result)
    declaration = TraceTelemetryDeclaration()
    callback_args: dict[str, Any] = {}
    if client_factory is not None:
        callback_args["client_factory"] = client_factory
    if tracer_factory is not None:
        callback_args["tracer_factory"] = tracer_factory
    client, tracer = build_langsmith_callback(active_settings, **callback_args)
    root_run_id = trace_id or uuid4()
    try:
        graph = graph_factory(retrievers)
        started = timer()
        try:
            result = graph.invoke(
                new_requirement_state(
                    TELEMETRY_TRACE_CASE_ID,
                    requirement.requirement_id,
                    requirement.text,
                ),
                config={
                    "callbacks": [tracer],
                    "run_id": root_run_id,
                    "run_name": TELEMETRY_TRACE_RUN_NAME,
                    "tags": [
                        "step-5-3",
                        "synthetic-data",
                        "offline-graph",
                        "safe-telemetry",
                    ],
                    "metadata": _combined_metadata(operational, declaration),
                },
            )
        except Exception:  # noqa: BLE001 - telemetry boundary discards exception details.
            client.flush(timeout=10)
            raise SafeTelemetryTraceError(
                "Synthetic graph telemetry trace failed; details were redacted"
            ) from None

        traced_operational = trace_metadata_from_state(result)
        if traced_operational != operational:
            raise SafeTelemetryTraceError(
                "Synthetic graph route changed between local preflight and traced execution"
            )
        telemetry = build_trace_telemetry(
            elapsed_seconds=timer() - started,
            usage=usage,
        )
        client.flush(timeout=10)
        trace_url = tracer.get_run_url()
        if not isinstance(trace_url, str) or not trace_url.startswith("https://"):
            raise RuntimeError("LangSmith did not return a trace URL")
        return LangSmithTelemetryTraceReceipt(
            project_name=LANGSMITH_PROJECT,
            run_name=TELEMETRY_TRACE_RUN_NAME,
            trace_id=str(root_run_id),
            trace_url=trace_url,
            metadata=operational,
            declaration=declaration,
            telemetry=telemetry,
        )
    finally:
        client.close(timeout=10)
