from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

import pytest
from langchain_core.callbacks import BaseCallbackHandler

from rfp_orchestrator.config import Settings
from rfp_orchestrator.langsmith_metadata import (
    METADATA_TRACE_CASE_ID,
    METADATA_TRACE_RUN_NAME,
    TraceMetadataError,
    run_langsmith_metadata_trace,
    trace_metadata_from_state,
)
from scripts.check_langsmith_metadata_trace import main as cli_main


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        langsmith_api_key="test-langsmith-key",
        langsmith_tracing=True,
        langsmith_project="enterprise-rfp-orchestrator",
    )


def complete_state(**overrides: object) -> dict[str, object]:
    state: dict[str, object] = {
        "case_id": "synthetic-case",
        "requirement_id": "RFP-002",
        "strategy": "PARALLEL_SPECIALISTS",
        "selected_specialists": ["product", "security"],
        "retry_count": 0,
        "risk_classes": [],
        "final_status": "FINALIZED",
        "original_text": "must never be included in metadata",
        "final_answer": "must never be included in metadata",
    }
    state.update(overrides)
    return state


def test_metadata_allowlist_selects_only_operational_labels() -> None:
    metadata = trace_metadata_from_state(complete_state())
    assert metadata.as_langsmith_metadata() == {
        "rfp_trace_metadata_schema_version": "1",
        "rfp_case_id": "synthetic-case",
        "rfp_requirement_id": "RFP-002",
        "rfp_strategy": "PARALLEL_SPECIALISTS",
        "rfp_selected_specialists": ["product", "security"],
        "rfp_retry_count": 0,
        "rfp_risk_classes": [],
        "rfp_final_status": "FINALIZED",
    }


@pytest.mark.parametrize(
    "state",
    [
        complete_state(retry_count=3),
        complete_state(requirement_id="unknown"),
        complete_state(strategy=None),
        complete_state(final_status=None),
    ],
)
def test_metadata_rejects_invalid_completed_state(state: dict[str, object]) -> None:
    with pytest.raises(TraceMetadataError):
        trace_metadata_from_state(state)


@dataclass
class FakeClient:
    updates: list[tuple[object, dict]]
    flush_count: int = 0
    closed: bool = False

    def update_run(self, run_id: object, *, extra: dict) -> None:
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
        return "https://smith.langchain.com/o/example/projects/p/example/r/metadata"


def test_metadata_trace_attaches_complete_allowlist_before_root_run_starts() -> None:
    clients: list[FakeClient] = []

    def fake_client(**kwargs: object) -> FakeClient:
        assert kwargs == {
            "api_key": "test-langsmith-key",
            "hide_inputs": True,
            "hide_outputs": True,
            "omit_traced_runtime_info": True,
        }
        client = FakeClient(updates=[])
        clients.append(client)
        return client

    trace_id = UUID("00000000-0000-0000-0000-000000000222")
    receipt = run_langsmith_metadata_trace(
        settings=configured_settings(),
        client_factory=fake_client,
        tracer_factory=FakeTracer,
        trace_id=trace_id,
    )
    client = clients[0]
    assert receipt.run_name == METADATA_TRACE_RUN_NAME
    assert receipt.metadata.case_id == METADATA_TRACE_CASE_ID
    assert receipt.metadata.requirement_id == "RFP-002"
    assert receipt.metadata.selected_specialists == ["product", "security"]
    assert receipt.metadata.final_status == "FINALIZED"
    assert receipt.langsmith_metadata_updates == 0
    assert receipt.local_graph_executions == 2
    assert client.updates == []
    assert client.flush_count == 1
    assert client.closed is True


def test_metadata_cli_dry_check_and_wrong_token_stay_offline(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "scripts.check_langsmith_metadata_trace.Settings",
        configured_settings,
    )
    assert cli_main([]) == 0
    assert "client initialized: no" in capsys.readouterr().out

    monkeypatch.setattr(
        "scripts.check_langsmith_metadata_trace.run_langsmith_metadata_trace",
        lambda **_kwargs: pytest.fail("trace should not run"),
    )
    assert cli_main(["--execute", "--approval-token", "wrong"]) == 2
    assert "Execution refused" in capsys.readouterr().out
