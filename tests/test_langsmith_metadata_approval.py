from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rfp_orchestrator.langsmith_metadata_approval import (
    DEFAULT_METADATA_TRACE_APPROVAL_PATH,
    LangSmithMetadataApprovalError,
    build_langsmith_metadata_approval,
    load_langsmith_metadata_approval,
    serialize_langsmith_metadata_approval,
    write_langsmith_metadata_approval,
)

RECEIPT_SHA256 = "328b446264f63847cda6c806ef72294c0958187ac1275f0e5b70031447348df0"


def approval():
    return build_langsmith_metadata_approval(
        expected_receipt_sha256=RECEIPT_SHA256,
        reviewer="Gaurav Asthana",
        reviewed_at=datetime.fromisoformat("2026-09-15T22:33:33-04:00"),
    )


def test_approval_preserves_reviewed_metadata_boundaries() -> None:
    result = approval()
    assert result.receipt_sha256 == RECEIPT_SHA256
    assert result.approved_metadata_field_count == 8
    assert result.metadata_values_visible_and_correct is True
    assert result.raw_content_absent_from_metadata is True
    assert result.credential_exposure_observed is False
    assert result.additional_trace_writes_for_approval == 0
    assert result.step_5_2_completed is True


def test_approval_rejects_an_unreviewed_receipt_digest() -> None:
    with pytest.raises(LangSmithMetadataApprovalError, match="does not match"):
        build_langsmith_metadata_approval(
            expected_receipt_sha256="0" * 64,
            reviewer="Gaurav Asthana",
            reviewed_at=datetime.fromisoformat("2026-09-15T22:33:33-04:00"),
        )


def test_approval_writer_is_idempotent_and_write_once(tmp_path: Path) -> None:
    output = tmp_path / "approval.json"
    result = approval()
    _, digest = write_langsmith_metadata_approval(result, output_path=output)
    assert output.with_name("approval.json.sha256").read_text(encoding="utf-8") == (
        f"{digest}  approval.json\n"
    )
    write_langsmith_metadata_approval(result, output_path=output)
    output.write_text("different\n", encoding="utf-8")
    with pytest.raises(LangSmithMetadataApprovalError, match="refusing to overwrite"):
        write_langsmith_metadata_approval(result, output_path=output)


def test_checked_in_approval_matches_user_review() -> None:
    result = load_langsmith_metadata_approval()
    content, digest = serialize_langsmith_metadata_approval(result)
    assert result.reviewed_by == "Gaurav Asthana"
    assert DEFAULT_METADATA_TRACE_APPROVAL_PATH.read_text(encoding="utf-8") == content
    assert DEFAULT_METADATA_TRACE_APPROVAL_PATH.with_name(
        f"{DEFAULT_METADATA_TRACE_APPROVAL_PATH.name}.sha256"
    ).read_text(encoding="utf-8") == (
        f"{digest}  {DEFAULT_METADATA_TRACE_APPROVAL_PATH.name}\n"
    )
