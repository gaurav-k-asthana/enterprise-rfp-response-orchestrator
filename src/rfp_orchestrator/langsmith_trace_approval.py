"""Immutable human review approval for the Step 5.1 LangSmith trace."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_freeze import file_sha256, text_sha256
from rfp_orchestrator.provider_final_evaluation import PROJECT_ROOT

TRACE_RECEIPT_PATH = (
    PROJECT_ROOT / "outputs" / "observability" / "langsmith_trace_step_5_1.json"
)
DEFAULT_TRACE_APPROVAL_PATH = (
    PROJECT_ROOT / "outputs" / "observability" / "langsmith_trace_approval_step_5_1.json"
)


class LangSmithTraceApprovalError(ValueError):
    """Raised when review approval does not match the saved trace receipt."""


class LangSmithTraceApprovalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    approval_id: Literal["northstar-langsmith-trace-step-5-1-approval-v1"] = (
        "northstar-langsmith-trace-step-5-1-approval-v1"
    )
    decision: Literal["APPROVED"] = "APPROVED"
    reviewed_by: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)
    receipt_path: Literal["outputs/observability/langsmith_trace_step_5_1.json"] = (
        "outputs/observability/langsmith_trace_step_5_1.json"
    )
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    project_name: Literal["enterprise-rfp-orchestrator"] = (
        "enterprise-rfp-orchestrator"
    )
    run_name: Literal["step-5-1-rfp-001-configuration-check"] = (
        "step-5-1-rfp-001-configuration-check"
    )
    requirement_id: Literal["RFP-001"] = "RFP-001"
    expected_graph_path_visible: Literal[True] = True
    unselected_specialists_remained_absent: Literal[True] = True
    final_status_verified: Literal["FINALIZED"] = "FINALIZED"
    synthetic_data_only_verified: Literal[True] = True
    credential_exposure_observed: Literal[False] = False
    additional_trace_writes_for_approval: Literal[0] = 0
    step_5_1_completed: Literal[True] = True

    @model_validator(mode="after")
    def review_has_identity_and_timezone(self) -> LangSmithTraceApprovalRecord:
        if not self.reviewed_by.strip():
            raise ValueError("reviewed_by cannot be blank")
        parsed = datetime.fromisoformat(self.reviewed_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        return self


def build_langsmith_trace_approval(
    *,
    expected_receipt_sha256: str,
    reviewer: str,
    reviewed_at: datetime,
) -> LangSmithTraceApprovalRecord:
    observed = file_sha256(TRACE_RECEIPT_PATH)
    if observed != expected_receipt_sha256:
        raise LangSmithTraceApprovalError(
            "trace receipt SHA-256 does not match the reviewed execution"
        )
    receipt = json.loads(TRACE_RECEIPT_PATH.read_text(encoding="utf-8"))
    expected = {
        "project_name": "enterprise-rfp-orchestrator",
        "run_name": "step-5-1-rfp-001-configuration-check",
        "requirement_id": "RFP-001",
        "data_classification": "SYNTHETIC_ONLY",
        "final_status": "FINALIZED",
        "openai_calls_made": 0,
        "pinecone_calls_made": 0,
        "langsmith_root_traces_written": 1,
        "api_key_recorded": False,
    }
    for key, value in expected.items():
        if receipt.get(key) != value:
            raise LangSmithTraceApprovalError(f"trace receipt field drifted: {key}")
    return LangSmithTraceApprovalRecord(
        reviewed_by=reviewer.strip(),
        reviewed_at=reviewed_at.isoformat(),
        receipt_sha256=observed,
    )


def serialize_langsmith_trace_approval(
    approval: LangSmithTraceApprovalRecord,
) -> tuple[str, str]:
    content = json.dumps(approval.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def _write_exact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise LangSmithTraceApprovalError(f"refusing to overwrite different content: {path.name}")
    path.write_text(content, encoding="utf-8")


def write_langsmith_trace_approval(
    approval: LangSmithTraceApprovalRecord,
    *,
    output_path: Path = DEFAULT_TRACE_APPROVAL_PATH,
) -> tuple[str, str]:
    content, digest = serialize_langsmith_trace_approval(approval)
    _write_exact(output_path, content)
    _write_exact(
        output_path.with_name(f"{output_path.name}.sha256"),
        f"{digest}  {output_path.name}\n",
    )
    return content, digest


def load_langsmith_trace_approval(
    path: Path = DEFAULT_TRACE_APPROVAL_PATH,
) -> LangSmithTraceApprovalRecord:
    return LangSmithTraceApprovalRecord.model_validate_json(path.read_text(encoding="utf-8"))
