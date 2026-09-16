from __future__ import annotations

from pathlib import Path

import pytest

from rfp_orchestrator.config import Settings
from rfp_orchestrator.langsmith_telemetry_repair import (
    LangSmithTelemetryRepairError,
    _validated_repair_metadata,
    repair_langsmith_telemetry_metadata,
)
from scripts.repair_langsmith_telemetry_metadata import main as cli_main


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        langsmith_api_key="test-langsmith-key",
        langsmith_tracing=True,
        langsmith_project="enterprise-rfp-orchestrator",
    )


def test_checked_in_receipt_produces_exact_twenty_field_patch() -> None:
    metadata = _validated_repair_metadata()
    assert len(metadata) == 20
    assert metadata["rfp_requirement_id"] == "RFP-003"
    assert metadata["rfp_selected_specialists"] == ["security"]
    assert metadata["rfp_latency_ms"] == 38.952
    assert metadata["rfp_total_tokens"] == 0
    assert metadata["rfp_raw_inputs_logged"] is False


def test_repair_rejects_receipt_digest_drift_before_client_creation(
    tmp_path: Path,
) -> None:
    changed = tmp_path / "receipt.json"
    changed.write_text("{}\n", encoding="utf-8")
    calls = 0

    def forbidden_client(**_kwargs: object):
        nonlocal calls
        calls += 1

    with pytest.raises(LangSmithTelemetryRepairError, match="SHA-256"):
        repair_langsmith_telemetry_metadata(
            settings=configured_settings(),
            client_factory=forbidden_client,
            receipt_path=changed,
        )
    assert calls == 0


def test_repair_retry_is_disabled_before_client_creation() -> None:
    calls = 0

    def forbidden_client(**_kwargs: object):
        nonlocal calls
        calls += 1

    with pytest.raises(LangSmithTelemetryRepairError, match="HTTP 409"):
        repair_langsmith_telemetry_metadata(
            settings=configured_settings(),
            client_factory=forbidden_client,
        )
    assert calls == 0


def test_repair_cli_dry_check_and_wrong_token_stay_offline(monkeypatch, capsys) -> None:
    monkeypatch.setattr(
        "scripts.repair_langsmith_telemetry_metadata.Settings",
        configured_settings,
    )
    assert cli_main([]) == 0
    output = capsys.readouterr().out
    assert "metadata-only update" in output
    assert "client initialized: no" in output

    assert cli_main(["--execute", "--approval-token", "wrong"]) == 2
    assert "Execution refused" in capsys.readouterr().out

    assert (
        cli_main(
            [
                "--execute",
                "--approval-token",
                "REPAIR-TELEMETRY-METADATA-RFP-003",
            ]
        )
        == 2
    )
    output = capsys.readouterr().out
    assert "HTTP 409" in output
    assert "metadata updates: 0" in output
