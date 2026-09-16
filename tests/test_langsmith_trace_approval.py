from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from rfp_orchestrator.langsmith_trace_approval import (
    DEFAULT_TRACE_APPROVAL_PATH,
    LangSmithTraceApprovalError,
    build_langsmith_trace_approval,
    load_langsmith_trace_approval,
    serialize_langsmith_trace_approval,
    write_langsmith_trace_approval,
)

RECEIPT_SHA256 = "efaa9e0df0d77876e0b4386a63a8c2fb7e54b27de0e106a305c938049f004e6a"


def approval():
    return build_langsmith_trace_approval(
        expected_receipt_sha256=RECEIPT_SHA256,
        reviewer="Gaurav Asthana",
        reviewed_at=datetime.fromisoformat("2026-09-15T20:59:46-04:00"),
    )


def test_approval_preserves_reviewed_trace_boundaries() -> None:
    result = approval()
    assert result.receipt_sha256 == RECEIPT_SHA256
    assert result.expected_graph_path_visible is True
    assert result.unselected_specialists_remained_absent is True
    assert result.final_status_verified == "FINALIZED"
    assert result.synthetic_data_only_verified is True
    assert result.credential_exposure_observed is False
    assert result.additional_trace_writes_for_approval == 0
    assert result.step_5_1_completed is True


def test_approval_rejects_an_unreviewed_receipt_digest() -> None:
    with pytest.raises(LangSmithTraceApprovalError, match="does not match"):
        build_langsmith_trace_approval(
            expected_receipt_sha256="0" * 64,
            reviewer="Gaurav Asthana",
            reviewed_at=datetime.fromisoformat("2026-09-15T20:59:46-04:00"),
        )


def test_approval_writer_is_idempotent_and_write_once(tmp_path: Path) -> None:
    output = tmp_path / "approval.json"
    result = approval()
    _, digest = write_langsmith_trace_approval(result, output_path=output)
    assert output.with_name("approval.json.sha256").read_text(encoding="utf-8") == (
        f"{digest}  approval.json\n"
    )
    write_langsmith_trace_approval(result, output_path=output)
    output.write_text("different\n", encoding="utf-8")
    with pytest.raises(LangSmithTraceApprovalError, match="refusing to overwrite"):
        write_langsmith_trace_approval(result, output_path=output)


def test_checked_in_approval_matches_user_review() -> None:
    result = load_langsmith_trace_approval()
    content, digest = serialize_langsmith_trace_approval(result)
    assert result.reviewed_by == "Gaurav Asthana"
    assert DEFAULT_TRACE_APPROVAL_PATH.read_text(encoding="utf-8") == content
    assert DEFAULT_TRACE_APPROVAL_PATH.with_name(
        f"{DEFAULT_TRACE_APPROVAL_PATH.name}.sha256"
    ).read_text(encoding="utf-8") == f"{digest}  {DEFAULT_TRACE_APPROVAL_PATH.name}\n"
