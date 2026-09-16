from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rfp_orchestrator.provider_final_approval import (
    DEFAULT_FINAL_APPROVAL_PATH,
    ProviderFinalApprovalError,
    build_provider_final_approval,
    load_provider_final_approval,
    serialize_provider_final_approval,
    write_provider_final_approval,
)
from scripts.record_provider_final_approval import main as approval_main

APPROVED_MARKDOWN_SHA256 = (
    "fd2e20fa430248463c3267f29c5cde663cc8230c9b5cb7ffbd31a77faf2f9a08"
)


def approval():
    return build_provider_final_approval(
        expected_markdown_sha256=APPROVED_MARKDOWN_SHA256,
        reviewer="Gaurav Asthana",
        approved_at=datetime.fromisoformat("2026-09-15T11:30:28-04:00"),
    )


def test_approval_binds_exact_artifacts_and_preserves_bounded_claims() -> None:
    result = approval()

    assert result.analysis_markdown_sha256 == APPROVED_MARKDOWN_SHA256
    assert result.analysis_json_sha256 == (
        "84edc4919789043e30dc6c78b672475627c5906f515af238faf78ac4bb61bca8"
    )
    assert result.bounded_preference == "single_generalist_for_frozen_v1"
    assert result.preserved_failure_treatment_approved is True
    assert result.repeat_censoring_warning_approved is True
    assert result.explicit_limitations_approved is True
    assert result.universal_multi_agent_superiority_claim_approved is False
    assert result.production_readiness_claim_approved is False
    assert result.phase_4_exit_gate_passed is True
    assert result.provider_calls_made_to_record_approval == 0


def test_approval_rejects_unreviewed_markdown_digest() -> None:
    with pytest.raises(ProviderFinalApprovalError, match="does not match"):
        build_provider_final_approval(
            expected_markdown_sha256="0" * 64,
            reviewer="Gaurav Asthana",
            approved_at=datetime.fromisoformat("2026-09-15T11:30:28-04:00"),
        )


def test_approval_writer_is_idempotent_and_write_once(tmp_path: Path) -> None:
    output = tmp_path / "approval.json"
    result = approval()
    _, digest = write_provider_final_approval(result, output_path=output)

    assert output.with_name("approval.json.sha256").read_text(encoding="utf-8") == (
        f"{digest}  approval.json\n"
    )
    write_provider_final_approval(result, output_path=output)
    output.write_text("different\n", encoding="utf-8")
    with pytest.raises(ProviderFinalApprovalError, match="refusing to overwrite"):
        write_provider_final_approval(result, output_path=output)


def test_checked_in_approval_matches_explicit_user_authorization() -> None:
    result = load_provider_final_approval()
    content, digest = serialize_provider_final_approval(result)

    assert result.approved_by == "Gaurav Asthana"
    assert result.approved_at == "2026-09-15T11:30:28-04:00"
    assert DEFAULT_FINAL_APPROVAL_PATH.read_text(encoding="utf-8") == content
    assert DEFAULT_FINAL_APPROVAL_PATH.with_name(
        f"{DEFAULT_FINAL_APPROVAL_PATH.name}.sha256"
    ).read_text(encoding="utf-8") == f"{digest}  {DEFAULT_FINAL_APPROVAL_PATH.name}\n"


def test_approval_cli_records_provenance_without_provider_calls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "approval.json"
    assert approval_main(
        [
            "--expected-markdown-sha256",
            APPROVED_MARKDOWN_SHA256,
            "--reviewer",
            "Gaurav Asthana",
            "--approved-at",
            "2026-09-15T11:30:28-04:00",
            "--output",
            str(output),
        ]
    ) == 0
    stdout = capsys.readouterr().out
    assert "Phase 4 exit gate passed: yes" in stdout
    assert "Provider calls made: 0" in stdout
    assert output.exists()
