from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rfp_orchestrator.langsmith_telemetry_approval import (
    DEFAULT_TELEMETRY_V2_APPROVAL_PATH,
    LangSmithTelemetryApprovalError,
    build_langsmith_telemetry_approval,
    load_langsmith_telemetry_approval,
    serialize_langsmith_telemetry_approval,
    write_langsmith_telemetry_approval,
)

RECEIPT_SHA256 = "c63d5275c549e96896f89927b4e30d861e8d6d9cd75463f593e9cc02f95cb383"


def approval():
    return build_langsmith_telemetry_approval(
        expected_receipt_sha256=RECEIPT_SHA256,
        reviewer="Gaurav Asthana",
        reviewed_at=datetime.fromisoformat("2026-09-15T23:59:59-04:00"),
    )


def test_approval_preserves_reviewed_v2_boundaries() -> None:
    result = approval()
    assert result.receipt_sha256 == RECEIPT_SHA256
    assert result.approved_operational_field_count == 8
    assert result.approved_telemetry_declaration_field_count == 11
    assert result.v2_metadata_visible_and_correct is True
    assert result.native_duration_visible is True
    assert result.native_error_state_successful is True
    assert result.security_only_path_visible is True
    assert result.raw_inputs_absent is True
    assert result.raw_outputs_absent is True
    assert result.credential_exposure_observed is False
    assert result.raw_exception_detail_observed is False
    assert result.additional_trace_writes_for_approval == 0
    assert result.step_5_3_completed is True


def test_approval_rejects_an_unreviewed_receipt_digest() -> None:
    with pytest.raises(LangSmithTelemetryApprovalError, match="does not match"):
        build_langsmith_telemetry_approval(
            expected_receipt_sha256="0" * 64,
            reviewer="Gaurav Asthana",
            reviewed_at=datetime.fromisoformat("2026-09-15T23:59:59-04:00"),
        )


def test_approval_writer_is_idempotent_and_write_once(tmp_path: Path) -> None:
    output = tmp_path / "approval.json"
    result = approval()
    _, digest = write_langsmith_telemetry_approval(result, output_path=output)
    assert output.with_name("approval.json.sha256").read_text(encoding="utf-8") == (
        f"{digest}  approval.json\n"
    )
    write_langsmith_telemetry_approval(result, output_path=output)
    output.write_text("different\n", encoding="utf-8")
    with pytest.raises(LangSmithTelemetryApprovalError, match="refusing to overwrite"):
        write_langsmith_telemetry_approval(result, output_path=output)


def test_checked_in_approval_matches_user_review() -> None:
    result = load_langsmith_telemetry_approval()
    content, digest = serialize_langsmith_telemetry_approval(result)
    assert result.reviewed_by == "Gaurav Asthana"
    assert DEFAULT_TELEMETRY_V2_APPROVAL_PATH.read_text(encoding="utf-8") == content
    assert DEFAULT_TELEMETRY_V2_APPROVAL_PATH.with_name(
        f"{DEFAULT_TELEMETRY_V2_APPROVAL_PATH.name}.sha256"
    ).read_text(encoding="utf-8") == (
        f"{digest}  {DEFAULT_TELEMETRY_V2_APPROVAL_PATH.name}\n"
    )
