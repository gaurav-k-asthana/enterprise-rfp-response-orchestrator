from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

import pytest
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.tracers.langchain import LangChainTracer

from rfp_orchestrator.config import Settings
from rfp_orchestrator.langsmith_privacy import (
    SANITIZED_TRACE_ERROR,
    PrivacyPreservingLangChainTracer,
)
from rfp_orchestrator.langsmith_telemetry import (
    TELEMETRY_TRACE_CASE_ID,
    TELEMETRY_TRACE_RUN_NAME,
    SafeTelemetryTraceError,
    TraceErrorCode,
    TraceTelemetry,
    TraceTelemetryDeclaration,
    TraceTokenUsage,
    build_trace_telemetry,
    run_langsmith_telemetry_trace,
)
from scripts.check_langsmith_telemetry_trace import main as cli_main


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        langsmith_api_key="test-langsmith-key",
        langsmith_tracing=True,
        langsmith_project="enterprise-rfp-orchestrator",
    )


def test_telemetry_allowlist_contains_only_safe_operational_values() -> None:
    telemetry = build_trace_telemetry(
        elapsed_seconds=0.125,
        usage=TraceTokenUsage.offline_zero(),
    )
    assert telemetry.as_langsmith_metadata() == {
        "rfp_trace_telemetry_schema_version": "1",
        "rfp_latency_ms": 125.0,
        "rfp_provider_calls": 0,
        "rfp_token_usage_observed": True,
        "rfp_input_tokens": 0,
        "rfp_output_tokens": 0,
        "rfp_total_tokens": 0,
        "rfp_error_count": 0,
        "rfp_error_code": None,
        "rfp_raw_inputs_logged": False,
        "rfp_raw_outputs_logged": False,
        "rfp_raw_error_details_logged": False,
    }


def test_trace_start_declaration_uses_native_latency_and_redacted_error_capture() -> None:
    declaration = TraceTelemetryDeclaration()
    assert declaration.as_langsmith_metadata() == {
        "rfp_trace_telemetry_schema_version": "2",
        "rfp_latency_capture_mode": "LANGSMITH_NATIVE",
        "rfp_provider_calls": 0,
        "rfp_token_usage_observed": True,
        "rfp_input_tokens": 0,
        "rfp_output_tokens": 0,
        "rfp_total_tokens": 0,
        "rfp_error_capture_mode": "LANGSMITH_NATIVE_REDACTED",
        "rfp_raw_inputs_logged": False,
        "rfp_raw_outputs_logged": False,
        "rfp_raw_error_details_logged": False,
    }


def test_token_usage_rejects_fabricated_or_inexact_counts() -> None:
    with pytest.raises(ValueError, match="unobserved"):
        TraceTokenUsage(
            provider_calls=1,
            token_usage_observed=False,
            input_tokens=10,
            output_tokens=None,
            total_tokens=None,
        )
    with pytest.raises(ValueError, match="total tokens"):
        TraceTokenUsage(
            provider_calls=1,
            token_usage_observed=True,
            input_tokens=10,
            output_tokens=5,
            total_tokens=14,
        )


def test_error_telemetry_uses_fixed_code_and_accepts_no_exception_text() -> None:
    telemetry = build_trace_telemetry(
        elapsed_seconds=0.25,
        usage=TraceTokenUsage.offline_zero(),
        error_code=TraceErrorCode.GRAPH_EXECUTION_FAILED,
    )
    rendered = str(telemetry.as_langsmith_metadata())
    assert telemetry.error_count == 1
    assert telemetry.error_code is TraceErrorCode.GRAPH_EXECUTION_FAILED
    assert "GRAPH_EXECUTION_FAILED" in rendered
    assert "exception" not in rendered.lower()


@pytest.mark.parametrize(
    "method_name",
    ["on_chain_error", "on_tool_error", "on_llm_error", "on_retriever_error"],
)
def test_privacy_tracer_replaces_error_details_before_parent_serialization(
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
) -> None:
    observed: dict[str, object] = {}

    def fake_parent(self: object, error: BaseException, **kwargs: object) -> str:
        observed["error"] = error
        observed["kwargs"] = kwargs
        return "safe"

    monkeypatch.setattr(LangChainTracer, method_name, fake_parent)
    tracer = object.__new__(PrivacyPreservingLangChainTracer)
    method = getattr(tracer, method_name)
    extra = {"inputs": {"secret": "raw requirement"}} if method_name == "on_chain_error" else {}
    result = method(RuntimeError("api-key raw requirement traceback"), run_id=uuid4(), **extra)
    assert result == "safe"
    assert str(observed["error"]) == SANITIZED_TRACE_ERROR
    assert "api-key" not in str(observed)
    if method_name == "on_chain_error":
        assert observed["kwargs"]["inputs"] is None  # type: ignore[index]


@dataclass
class FakeClient:
    updates: list[tuple[object, dict[str, object]]]
    flush_count: int = 0
    closed: bool = False

    def update_run(self, run_id: object, *, extra: dict[str, object]) -> None:
        self.updates.append((run_id, extra))

    def flush(self, *, timeout: int) -> None:
        assert timeout == 10
        self.flush_count += 1

    def close(self, *, timeout: int) -> None:
        assert timeout == 10
        self.closed = True


class FakeTracer(BaseCallbackHandler):
    def __init__(self, *, project_name: str, client: FakeClient) -> None:
        self.project_name = project_name
        self.client = client

    def get_run_url(self) -> str:
        return "https://smith.langchain.com/o/example/projects/p/example/r/telemetry"


def _fake_client_factory(clients: list[FakeClient]):
    def factory(**kwargs: object) -> FakeClient:
        assert kwargs == {
            "api_key": "test-langsmith-key",
            "hide_inputs": True,
            "hide_outputs": True,
            "omit_traced_runtime_info": True,
        }
        client = FakeClient(updates=[])
        clients.append(client)
        return client

    return factory


def test_telemetry_trace_attaches_metadata_at_start_and_uses_native_capture() -> None:
    clients: list[FakeClient] = []
    ticks = iter((10.0, 10.125))
    trace_id = UUID("00000000-0000-0000-0000-000000000333")
    receipt = run_langsmith_telemetry_trace(
        settings=configured_settings(),
        client_factory=_fake_client_factory(clients),
        tracer_factory=FakeTracer,
        trace_id=trace_id,
        timer=lambda: next(ticks),
    )
    client = clients[0]
    assert receipt.run_name == TELEMETRY_TRACE_RUN_NAME
    assert receipt.metadata.case_id == TELEMETRY_TRACE_CASE_ID
    assert receipt.declaration.latency_capture_mode == "LANGSMITH_NATIVE"
    assert receipt.telemetry.latency_ms == 125.0
    assert receipt.telemetry.total_tokens == 0
    assert receipt.telemetry.error_count == 0
    assert receipt.trace_id == str(trace_id)
    assert receipt.local_graph_executions == 2
    assert receipt.langsmith_metadata_updates == 0
    assert client.updates == []
    assert client.flush_count == 1
    assert client.closed is True


def test_complete_safe_metadata_is_present_before_the_traced_invoke() -> None:
    clients: list[FakeClient] = []
    observed_configs: list[object] = []

    class RecordingGraph:
        def invoke(
            self,
            input: dict[str, object],
            config: object,
        ) -> dict[str, object]:
            observed_configs.append(config)
            return {
                **input,
                "case_id": TELEMETRY_TRACE_CASE_ID,
                "requirement_id": "RFP-003",
                "strategy": "SINGLE_SPECIALIST",
                "selected_specialists": ["security"],
                "retry_count": 0,
                "risk_classes": [],
                "final_status": "FINALIZED",
            }

    ticks = iter((30.0, 30.02))
    run_langsmith_telemetry_trace(
        settings=configured_settings(),
        client_factory=_fake_client_factory(clients),
        tracer_factory=FakeTracer,
        graph_factory=lambda _retrievers: RecordingGraph(),
        timer=lambda: next(ticks),
    )
    assert observed_configs[0] == {}
    traced_config = observed_configs[1]
    assert isinstance(traced_config, dict)
    metadata = traced_config["metadata"]
    assert isinstance(metadata, dict)
    assert len(metadata) == 19
    assert metadata["rfp_strategy"] == "SINGLE_SPECIALIST"
    assert metadata["rfp_latency_capture_mode"] == "LANGSMITH_NATIVE"
    assert metadata["rfp_error_capture_mode"] == "LANGSMITH_NATIVE_REDACTED"
    assert metadata["rfp_total_tokens"] == 0
    assert "rfp_latency_ms" not in metadata
    assert "rfp_error_count" not in metadata


class FailingGraph:
    def invoke(self, input: object, config: object) -> dict[str, object]:
        del input, config
        raise RuntimeError("api-key raw requirement traceback")


def test_failed_trace_records_only_fixed_error_code_and_raises_safe_copy() -> None:
    clients: list[FakeClient] = []
    ticks = iter((20.0, 20.5))
    calls = 0

    class SuccessfulPreflightGraph:
        def invoke(self, input: dict[str, object], config: object) -> dict[str, object]:
            del config
            return {
                **input,
                "case_id": TELEMETRY_TRACE_CASE_ID,
                "requirement_id": "RFP-003",
                "strategy": "SINGLE_SPECIALIST",
                "selected_specialists": ["security"],
                "retry_count": 0,
                "risk_classes": [],
                "final_status": "FINALIZED",
            }

    def graph_factory(_retrievers: object):
        nonlocal calls
        calls += 1
        return SuccessfulPreflightGraph() if calls == 1 else FailingGraph()

    with pytest.raises(SafeTelemetryTraceError) as captured:
        run_langsmith_telemetry_trace(
            settings=configured_settings(),
            client_factory=_fake_client_factory(clients),
            tracer_factory=FakeTracer,
            graph_factory=graph_factory,
            timer=lambda: next(ticks),
        )
    assert "details were redacted" in str(captured.value)
    assert clients[0].updates == []
    assert clients[0].flush_count == 1
    assert clients[0].closed is True


def test_telemetry_model_rejects_error_count_code_mismatch() -> None:
    with pytest.raises(ValueError, match="error count"):
        TraceTelemetry(
            latency_ms=1.0,
            provider_calls=0,
            token_usage_observed=True,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            error_count=1,
            error_code=None,
        )


def test_telemetry_cli_dry_check_and_wrong_token_stay_offline(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "scripts.check_langsmith_telemetry_trace.Settings",
        configured_settings,
    )
    assert cli_main([]) == 0
    output = capsys.readouterr().out
    assert "raw inputs hidden" in output
    assert "client initialized: no" in output

    monkeypatch.setattr(
        "scripts.check_langsmith_telemetry_trace.run_langsmith_telemetry_trace",
        lambda **_kwargs: pytest.fail("trace should not run"),
    )
    assert cli_main(["--execute", "--approval-token", "wrong"]) == 2
    assert "Execution refused" in capsys.readouterr().out
