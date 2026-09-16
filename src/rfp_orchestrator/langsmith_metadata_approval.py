"""Immutable human approval for the Step 5.2 LangSmith metadata trace."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_freeze import file_sha256, text_sha256
from rfp_orchestrator.provider_final_evaluation import PROJECT_ROOT

METADATA_TRACE_RECEIPT_PATH = (
    PROJECT_ROOT / "outputs" / "observability" / "langsmith_metadata_trace_step_5_2.json"
)
DEFAULT_METADATA_TRACE_APPROVAL_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "observability"
    / "langsmith_metadata_trace_approval_step_5_2.json"
)


class LangSmithMetadataApprovalError(ValueError):
    """Raised when approval does not match the reviewed metadata trace receipt."""


class LangSmithMetadataApprovalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    approval_id: Literal["northstar-langsmith-metadata-step-5-2-approval-v1"] = (
        "northstar-langsmith-metadata-step-5-2-approval-v1"
    )
    decision: Literal["APPROVED"] = "APPROVED"
    reviewed_by: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)
    receipt_path: Literal[
        "outputs/observability/langsmith_metadata_trace_step_5_2.json"
    ] = "outputs/observability/langsmith_metadata_trace_step_5_2.json"
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_metadata_field_count: Literal[8] = 8
    metadata_values_visible_and_correct: Literal[True] = True
    raw_content_absent_from_metadata: Literal[True] = True
    credential_exposure_observed: Literal[False] = False
    additional_trace_writes_for_approval: Literal[0] = 0
    step_5_2_completed: Literal[True] = True

    @model_validator(mode="after")
    def review_has_identity_and_timezone(self) -> LangSmithMetadataApprovalRecord:
        if not self.reviewed_by.strip():
            raise ValueError("reviewed_by cannot be blank")
        parsed = datetime.fromisoformat(self.reviewed_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        return self


def build_langsmith_metadata_approval(
    *,
    expected_receipt_sha256: str,
    reviewer: str,
    reviewed_at: datetime,
) -> LangSmithMetadataApprovalRecord:
    observed = file_sha256(METADATA_TRACE_RECEIPT_PATH)
    if observed != expected_receipt_sha256:
        raise LangSmithMetadataApprovalError(
            "metadata trace receipt SHA-256 does not match the reviewed execution"
        )
    receipt = json.loads(METADATA_TRACE_RECEIPT_PATH.read_text(encoding="utf-8"))
    expected_metadata = {
        "rfp_trace_metadata_schema_version": "1",
        "rfp_case_id": "langsmith-step-5-2-synthetic",
        "rfp_requirement_id": "RFP-002",
        "rfp_strategy": "PARALLEL_SPECIALISTS",
        "rfp_selected_specialists": ["product", "security"],
        "rfp_retry_count": 0,
        "rfp_risk_classes": [],
        "rfp_final_status": "FINALIZED",
    }
    if receipt.get("metadata") != expected_metadata:
        raise LangSmithMetadataApprovalError("metadata trace receipt fields drifted")
    if receipt.get("api_key_recorded") is not False:
        raise LangSmithMetadataApprovalError("metadata trace receipt key boundary drifted")
    return LangSmithMetadataApprovalRecord(
        reviewed_by=reviewer.strip(),
        reviewed_at=reviewed_at.isoformat(),
        receipt_sha256=observed,
    )


def serialize_langsmith_metadata_approval(
    approval: LangSmithMetadataApprovalRecord,
) -> tuple[str, str]:
    content = json.dumps(approval.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def _write_exact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise LangSmithMetadataApprovalError(
            f"refusing to overwrite different content: {path.name}"
        )
    path.write_text(content, encoding="utf-8")


def write_langsmith_metadata_approval(
    approval: LangSmithMetadataApprovalRecord,
    *,
    output_path: Path = DEFAULT_METADATA_TRACE_APPROVAL_PATH,
) -> tuple[str, str]:
    content, digest = serialize_langsmith_metadata_approval(approval)
    _write_exact(output_path, content)
    _write_exact(
        output_path.with_name(f"{output_path.name}.sha256"),
        f"{digest}  {output_path.name}\n",
    )
    return content, digest


def load_langsmith_metadata_approval(
    path: Path = DEFAULT_METADATA_TRACE_APPROVAL_PATH,
) -> LangSmithMetadataApprovalRecord:
    return LangSmithMetadataApprovalRecord.model_validate_json(
        path.read_text(encoding="utf-8")
    )
