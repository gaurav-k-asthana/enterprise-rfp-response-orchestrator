"""Immutable human approval for the reviewed Step 5.3 V2 telemetry trace."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_freeze import file_sha256, text_sha256
from rfp_orchestrator.provider_final_evaluation import PROJECT_ROOT

TELEMETRY_V2_RECEIPT_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "observability"
    / "langsmith_telemetry_trace_v2_step_5_3.json"
)
DEFAULT_TELEMETRY_V2_APPROVAL_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "observability"
    / "langsmith_telemetry_trace_v2_approval_step_5_3.json"
)


class LangSmithTelemetryApprovalError(ValueError):
    """Raised when approval does not match the reviewed V2 trace receipt."""


class LangSmithTelemetryApprovalRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    approval_id: Literal["northstar-langsmith-telemetry-step-5-3-v2-approval-v1"] = (
        "northstar-langsmith-telemetry-step-5-3-v2-approval-v1"
    )
    decision: Literal["APPROVED"] = "APPROVED"
    reviewed_by: str = Field(min_length=1)
    reviewed_at: str = Field(min_length=1)
    receipt_path: Literal[
        "outputs/observability/langsmith_telemetry_trace_v2_step_5_3.json"
    ] = "outputs/observability/langsmith_telemetry_trace_v2_step_5_3.json"
    receipt_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_operational_field_count: Literal[8] = 8
    approved_telemetry_declaration_field_count: Literal[11] = 11
    v2_metadata_visible_and_correct: Literal[True] = True
    native_duration_visible: Literal[True] = True
    native_error_state_successful: Literal[True] = True
    security_only_path_visible: Literal[True] = True
    raw_inputs_absent: Literal[True] = True
    raw_outputs_absent: Literal[True] = True
    credential_exposure_observed: Literal[False] = False
    raw_exception_detail_observed: Literal[False] = False
    v1_trace_preserved: Literal[True] = True
    failed_repair_preserved: Literal[True] = True
    additional_trace_writes_for_approval: Literal[0] = 0
    step_5_3_completed: Literal[True] = True

    @model_validator(mode="after")
    def review_has_identity_and_timezone(self) -> LangSmithTelemetryApprovalRecord:
        if not self.reviewed_by.strip():
            raise ValueError("reviewed_by cannot be blank")
        parsed = datetime.fromisoformat(self.reviewed_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("reviewed_at must include a timezone")
        return self


def build_langsmith_telemetry_approval(
    *,
    expected_receipt_sha256: str,
    reviewer: str,
    reviewed_at: datetime,
) -> LangSmithTelemetryApprovalRecord:
    observed = file_sha256(TELEMETRY_V2_RECEIPT_PATH)
    if observed != expected_receipt_sha256:
        raise LangSmithTelemetryApprovalError(
            "V2 telemetry receipt SHA-256 does not match the reviewed execution"
        )
    receipt = json.loads(TELEMETRY_V2_RECEIPT_PATH.read_text(encoding="utf-8"))
    expected_operational = {
        "rfp_trace_metadata_schema_version": "1",
        "rfp_case_id": "langsmith-step-5-3-synthetic",
        "rfp_requirement_id": "RFP-003",
        "rfp_strategy": "SINGLE_SPECIALIST",
        "rfp_selected_specialists": ["security"],
        "rfp_retry_count": 0,
        "rfp_risk_classes": [],
        "rfp_final_status": "FINALIZED",
    }
    expected_declaration = {
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
    expected_identity = {
        "project_name": "enterprise-rfp-orchestrator",
        "run_name": "step-5-3-rfp-003-safe-telemetry-check-v2",
        "trace_id": "ecd56982-f1f0-4930-ab84-a65fe6c871e8",
        "data_classification": "SYNTHETIC_ONLY",
        "langsmith_root_traces_written": 1,
        "langsmith_post_run_metadata_updates": 0,
        "openai_calls_made": 0,
        "pinecone_calls_made": 0,
        "api_key_recorded": False,
    }
    for key, expected in expected_identity.items():
        if receipt.get(key) != expected:
            raise LangSmithTelemetryApprovalError(f"V2 trace receipt field drifted: {key}")
    if receipt.get("operational_metadata") != expected_operational:
        raise LangSmithTelemetryApprovalError("V2 operational metadata drifted")
    if receipt.get("telemetry_declaration") != expected_declaration:
        raise LangSmithTelemetryApprovalError("V2 telemetry declaration drifted")
    return LangSmithTelemetryApprovalRecord(
        reviewed_by=reviewer.strip(),
        reviewed_at=reviewed_at.isoformat(),
        receipt_sha256=observed,
    )


def serialize_langsmith_telemetry_approval(
    approval: LangSmithTelemetryApprovalRecord,
) -> tuple[str, str]:
    content = json.dumps(approval.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def _write_exact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise LangSmithTelemetryApprovalError(
            f"refusing to overwrite different content: {path.name}"
        )
    path.write_text(content, encoding="utf-8")


def write_langsmith_telemetry_approval(
    approval: LangSmithTelemetryApprovalRecord,
    *,
    output_path: Path = DEFAULT_TELEMETRY_V2_APPROVAL_PATH,
) -> tuple[str, str]:
    content, digest = serialize_langsmith_telemetry_approval(approval)
    _write_exact(output_path, content)
    _write_exact(
        output_path.with_name(f"{output_path.name}.sha256"),
        f"{digest}  {output_path.name}\n",
    )
    return content, digest


def load_langsmith_telemetry_approval(
    path: Path = DEFAULT_TELEMETRY_V2_APPROVAL_PATH,
) -> LangSmithTelemetryApprovalRecord:
    return LangSmithTelemetryApprovalRecord.model_validate_json(
        path.read_text(encoding="utf-8")
    )
