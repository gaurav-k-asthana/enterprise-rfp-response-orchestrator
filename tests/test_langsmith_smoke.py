from __future__ import annotations

from dataclasses import dataclass

import pytest
from langchain_core.callbacks import BaseCallbackHandler

from rfp_orchestrator.config import Settings
from rfp_orchestrator.langsmith_smoke import (
    LANGSMITH_PROJECT,
    LangSmithConfigurationError,
    build_langsmith_callback,
    run_langsmith_trace_smoke,
)
from scripts.check_langsmith_trace import main as cli_main


def configured_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "langsmith_api_key": "test-langsmith-key",
        "langsmith_tracing": True,
        "langsmith_project": LANGSMITH_PROJECT,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def test_settings_fail_closed_before_client_creation() -> None:
    calls = 0

    def forbidden_client(**_kwargs: object):
        nonlocal calls
        calls += 1

    for settings in (
        configured_settings(langsmith_api_key=None),
        configured_settings(langsmith_tracing=False),
        configured_settings(langsmith_project="wrong-project"),
    ):
        with pytest.raises(LangSmithConfigurationError):
            build_langsmith_callback(settings, client_factory=forbidden_client)
    assert calls == 0


def test_callback_receives_hidden_key_and_frozen_project() -> None:
    observed: dict[str, object] = {}

    def fake_client(**kwargs: object):
        observed["client"] = kwargs
        return "client"

    def fake_tracer(**kwargs: object):
        observed["tracer"] = kwargs
        return "tracer"

    client, tracer = build_langsmith_callback(
        configured_settings(),
        client_factory=fake_client,
        tracer_factory=fake_tracer,
    )
    assert (client, tracer) == ("client", "tracer")
    assert observed == {
        "client": {
            "api_key": "test-langsmith-key",
            "hide_inputs": True,
            "hide_outputs": True,
            "omit_traced_runtime_info": True,
        },
        "tracer": {"project_name": LANGSMITH_PROJECT, "client": "client"},
    }


@dataclass
class FakeClient:
    flushed: bool = False
    closed: bool = False

    def flush(self, *, timeout: int) -> None:
        assert timeout == 10
        self.flushed = True

    def close(self, *, timeout: int) -> None:
        assert timeout == 10
        self.closed = True


class FakeTracer(BaseCallbackHandler):
    def __init__(self, *, project_name: str, client: FakeClient) -> None:
        self.project_name = project_name
        self.client = client

    def get_run_url(self) -> str:
        return "https://smith.langchain.com/o/example/projects/p/example/r/test"


def test_smoke_uses_real_offline_graph_and_reports_zero_provider_calls() -> None:
    clients: list[FakeClient] = []

    def fake_client(**kwargs: object) -> FakeClient:
        assert kwargs == {
            "api_key": "test-langsmith-key",
            "hide_inputs": True,
            "hide_outputs": True,
            "omit_traced_runtime_info": True,
        }
        client = FakeClient()
        clients.append(client)
        return client

    receipt = run_langsmith_trace_smoke(
        settings=configured_settings(),
        client_factory=fake_client,
        tracer_factory=FakeTracer,
    )

    assert receipt.requirement_id == "RFP-001"
    assert receipt.final_status == "FINALIZED"
    assert receipt.openai_calls_made == 0
    assert receipt.pinecone_calls_made == 0
    assert receipt.langsmith_trace_writes == 1
    assert clients[0].flushed is True
    assert clients[0].closed is True


def test_cli_dry_check_never_initializes_langsmith(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "scripts.check_langsmith_trace.Settings",
        lambda: configured_settings(),
    )
    assert cli_main([]) == 0
    output = capsys.readouterr().out
    assert "API key: present (value hidden)" in output
    assert "client initialized: no" in output
    assert "Network calls made: 0" in output


def test_cli_refuses_wrong_execution_token_before_client_creation(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr(
        "scripts.check_langsmith_trace.Settings",
        lambda: configured_settings(),
    )
    monkeypatch.setattr(
        "scripts.check_langsmith_trace.run_langsmith_trace_smoke",
        lambda **_kwargs: pytest.fail("trace should not run"),
    )
    assert cli_main(["--execute", "--approval-token", "wrong"]) == 2
    output = capsys.readouterr().out
    assert "Execution refused" in output
    assert "Network calls made: 0" in output
