"""Immutable human approval for the final Step 4.G8 provider analysis."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_freeze import file_sha256, text_sha256
from rfp_orchestrator.provider_final_evaluation import (
    DEFAULT_FINAL_JSON_PATH,
    DEFAULT_FINAL_MARKDOWN_PATH,
    PROJECT_ROOT,
)

DEFAULT_FINAL_APPROVAL_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "provider_evaluation_final_approval_step_4_g8.json"
)


class ProviderFinalApprovalError(ValueError):
    """Raised when approval does not match the reviewed final analysis."""


class ProviderFinalApprovalRecord(BaseModel):
    """Human approval of exact final artifacts; this never changes or reruns them."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    approval_id: Literal["northstar-provider-final-evaluation-step-4-g8-approval-v1"] = (
        "northstar-provider-final-evaluation-step-4-g8-approval-v1"
    )
    decision: Literal["APPROVED"] = "APPROVED"
    approved_by: str = Field(min_length=1)
    approved_at: str = Field(min_length=1)
    analysis_markdown_path: Literal[
        "outputs/evaluation/provider_evaluation_final_step_4_g8.md"
    ] = "outputs/evaluation/provider_evaluation_final_step_4_g8.md"
    analysis_markdown_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_json_path: Literal[
        "outputs/evaluation/provider_evaluation_final_step_4_g8.json"
    ] = "outputs/evaluation/provider_evaluation_final_step_4_g8.json"
    analysis_json_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analysis_scope: Literal["FROZEN_V1_PRIMARY_WITH_BUDGET_CENSORED_REPEATS"] = (
        "FROZEN_V1_PRIMARY_WITH_BUDGET_CENSORED_REPEATS"
    )
    bounded_preference: Literal["single_generalist_for_frozen_v1"] = (
        "single_generalist_for_frozen_v1"
    )
    preserved_failure_treatment_approved: Literal[True] = True
    repeat_censoring_warning_approved: Literal[True] = True
    explicit_limitations_approved: Literal[True] = True
    universal_multi_agent_superiority_claim_approved: Literal[False] = False
    production_readiness_claim_approved: Literal[False] = False
    phase_4_exit_gate_passed: Literal[True] = True
    provider_calls_made_to_record_approval: Literal[0] = 0

    @model_validator(mode="after")
    def approval_has_review_provenance(self) -> ProviderFinalApprovalRecord:
        if not self.approved_by.strip():
            raise ValueError("approved_by cannot be blank")
        parsed = datetime.fromisoformat(self.approved_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("approved_at must include a timezone")
        return self


def build_provider_final_approval(
    *,
    expected_markdown_sha256: str,
    reviewer: str,
    approved_at: datetime,
) -> ProviderFinalApprovalRecord:
    """Bind approval to the exact reviewed Markdown and companion JSON."""

    observed_markdown_sha256 = file_sha256(DEFAULT_FINAL_MARKDOWN_PATH)
    if observed_markdown_sha256 != expected_markdown_sha256:
        raise ProviderFinalApprovalError(
            "final Markdown SHA-256 does not match the explicitly approved analysis"
        )
    return ProviderFinalApprovalRecord(
        approved_by=reviewer.strip(),
        approved_at=approved_at.isoformat(),
        analysis_markdown_sha256=observed_markdown_sha256,
        analysis_json_sha256=file_sha256(DEFAULT_FINAL_JSON_PATH),
    )


def serialize_provider_final_approval(
    approval: ProviderFinalApprovalRecord,
) -> tuple[str, str]:
    content = json.dumps(approval.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def _write_exact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise ProviderFinalApprovalError(f"refusing to overwrite different content: {path.name}")
    path.write_text(content, encoding="utf-8")


def write_provider_final_approval(
    approval: ProviderFinalApprovalRecord,
    *,
    output_path: Path = DEFAULT_FINAL_APPROVAL_PATH,
) -> tuple[str, str]:
    content, digest = serialize_provider_final_approval(approval)
    _write_exact(output_path, content)
    _write_exact(
        output_path.with_name(f"{output_path.name}.sha256"),
        f"{digest}  {output_path.name}\n",
    )
    return content, digest


def load_provider_final_approval(
    path: Path = DEFAULT_FINAL_APPROVAL_PATH,
) -> ProviderFinalApprovalRecord:
    return ProviderFinalApprovalRecord.model_validate_json(path.read_text(encoding="utf-8"))
