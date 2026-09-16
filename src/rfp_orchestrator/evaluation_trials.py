"""Predefined, budget-gated repeated evaluation trials for Step 4.16."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.comparison_safety import DEFAULT_SHARED_SAFETY_POLICY_PATH
from rfp_orchestrator.evaluation_freeze import file_sha256, text_sha256, validate_frozen_gold
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    EXPECTED_CASE_IDS,
    EvaluationCaseFamily,
    load_evaluation_dataset,
)
from rfp_orchestrator.fair_comparison import (
    DEFAULT_FAIR_COMPARISON_PATH,
    ComparisonArchitecture,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRICING_SNAPSHOT_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "openai_pricing_snapshot_step_4_14.json"
)
DEFAULT_REPEAT_TRIAL_PLAN_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "repeat_trial_plan_v1.json"
)
DEFAULT_REPEAT_TRIAL_PLAN_DIGEST_PATH = DEFAULT_REPEAT_TRIAL_PLAN_PATH.with_suffix(
    ".sha256"
)
DEFAULT_REPEAT_TRIAL_REVIEW_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "repeat_trial_review_packet_v1.md"
)
DEFAULT_REPEAT_TRIAL_APPROVAL_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "repeat_trial_approval_v1.json"
)
REPEAT_TRIAL_PLAN_ID = "northstar-rfp-repeat-trials-v1"
REPEAT_TRIAL_PREPARED_AT = "2026-09-14T12:00:00-04:00"
SELECTED_REPEAT_CASE_IDS = ("EVAL-001", "EVAL-002", "EVAL-015", "EVAL-021")
TOTAL_TRIALS_PER_SELECTED_CASE = 3
ADDITIONAL_REPEAT_COUNT = 2


class EvaluationTrialPlanError(ValueError):
    """Raised when a repeated-trial request violates its reviewed boundary."""


class TrialPlanStatus(str, Enum):
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"


class VariabilityDimension(str, Enum):
    SIMPLE_STABILITY_CONTROL = "SIMPLE_STABILITY_CONTROL"
    ROUTING_AND_TOOL_SELECTION = "ROUTING_AND_TOOL_SELECTION"
    CONFLICT_AND_AUTHORITY_ESCALATION = "CONFLICT_AND_AUTHORITY_ESCALATION"
    EVIDENCE_GAP_AND_BOUNDED_RECOVERY = "EVIDENCE_GAP_AND_BOUNDED_RECOVERY"


class RepeatCasePlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    case_families: list[EvaluationCaseFamily] = Field(min_length=1)
    variability_dimensions: list[VariabilityDimension] = Field(min_length=1)
    rationale: str = Field(min_length=1)
    primary_trial_number: Literal[1] = 1
    additional_trial_numbers: list[int] = Field(min_length=2, max_length=2)

    @model_validator(mode="after")
    def trial_numbers_are_exact(self) -> RepeatCasePlan:
        if self.additional_trial_numbers != [2, 3]:
            raise ValueError("selected repeat cases require exactly trials 2 and 3")
        if len(self.variability_dimensions) != len(set(self.variability_dimensions)):
            raise ValueError("variability dimensions cannot repeat")
        return self


class TrialBudget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    currency: Literal["USD"] = "USD"
    pricing_snapshot_id: str = Field(min_length=1)
    pricing_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_usd_per_million_tokens: float = Field(gt=0)
    output_usd_per_million_tokens: float = Field(gt=0)
    max_provider_calls_per_architecture_execution: Literal[3] = 3
    max_provider_calls_total: Literal[128] = 128
    max_input_tokens_per_provider_call: Literal[8000] = 8000
    max_output_tokens_per_provider_call: Literal[2000] = 2000
    max_total_input_tokens: Literal[1024000] = 1_024_000
    max_total_output_tokens: Literal[256000] = 256_000
    proposed_hard_cost_cap_usd: Literal[5.12] = 5.12
    currently_authorized_cost_usd: float = Field(ge=0)
    automatic_provider_retries_allowed: Literal[False] = False
    stop_before_next_call_when_cap_would_be_exceeded: Literal[True] = True

    @model_validator(mode="after")
    def hard_cap_matches_token_envelope(self) -> TrialBudget:
        if (
            self.max_total_input_tokens
            != self.max_provider_calls_total * self.max_input_tokens_per_provider_call
        ):
            raise ValueError("total input-token cap must equal the guarded call envelope")
        if (
            self.max_total_output_tokens
            != self.max_provider_calls_total * self.max_output_tokens_per_provider_call
        ):
            raise ValueError("total output-token cap must equal the guarded call envelope")
        calculated = (
            self.max_total_input_tokens * self.input_usd_per_million_tokens
            + self.max_total_output_tokens * self.output_usd_per_million_tokens
        ) / 1_000_000
        if round(calculated, 2) != self.proposed_hard_cost_cap_usd:
            raise ValueError("hard cost cap must match the frozen worst-case token envelope")
        if self.currently_authorized_cost_usd > self.proposed_hard_cost_cap_usd:
            raise ValueError("authorized cost cannot exceed the proposed hard cap")
        return self


class RepeatTrialPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    plan_id: Literal["northstar-rfp-repeat-trials-v1"] = REPEAT_TRIAL_PLAN_ID
    status: TrialPlanStatus
    prepared_at: str = Field(min_length=1)
    frozen_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fair_comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    shared_safety_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    architectures: list[ComparisonArchitecture] = Field(min_length=2, max_length=2)
    primary_case_ids: list[str] = Field(min_length=24, max_length=24)
    repeat_cases: list[RepeatCasePlan] = Field(min_length=4, max_length=4)
    total_trials_per_selected_case: Literal[3] = TOTAL_TRIALS_PER_SELECTED_CASE
    additional_repeat_count: Literal[2] = ADDITIONAL_REPEAT_COUNT
    primary_architecture_execution_count: Literal[48] = 48
    additional_repeat_architecture_execution_count: Literal[16] = 16
    max_total_architecture_execution_count: Literal[64] = 64
    excluded_deterministic_stop_case_ids: list[str]
    budget: TrialBudget
    approval_required: Literal[True] = True
    approved_by: str | None = None
    approved_at: str | None = None
    provider_execution_authorized: bool
    comparative_runs_completed: Literal[0] = 0
    provider_calls_made: Literal[0] = 0

    @model_validator(mode="after")
    def scope_and_approval_are_consistent(self) -> RepeatTrialPlan:
        if self.architectures != list(ComparisonArchitecture):
            raise ValueError("trial plan requires both architectures in canonical order")
        if self.primary_case_ids != list(EXPECTED_CASE_IDS):
            raise ValueError("primary comparison must retain all 24 frozen cases")
        repeat_ids = [case.case_id for case in self.repeat_cases]
        if repeat_ids != list(SELECTED_REPEAT_CASE_IDS):
            raise ValueError("repeat subset or order drifted from the reviewed proposal")
        if len(repeat_ids) != len(set(repeat_ids)):
            raise ValueError("repeat case IDs cannot repeat")
        if set(repeat_ids) & set(self.excluded_deterministic_stop_case_ids):
            raise ValueError("deterministic pre-model stops cannot enter the repeat subset")
        expected_additional = (
            len(repeat_ids) * self.additional_repeat_count * len(self.architectures)
        )
        if expected_additional != self.additional_repeat_architecture_execution_count:
            raise ValueError("additional repeat execution count is inconsistent")
        if (
            self.primary_architecture_execution_count + expected_additional
            != self.max_total_architecture_execution_count
        ):
            raise ValueError("maximum architecture execution count is inconsistent")

        approved = self.status is TrialPlanStatus.APPROVED
        approval_fields_complete = bool(
            self.approved_by
            and self.approved_by.strip()
            and self.approved_at
            and self.provider_execution_authorized
            and self.budget.currently_authorized_cost_usd > 0
        )
        if approved != approval_fields_complete:
            raise ValueError("approval status and authorization fields must agree")
        if not approved and self.budget.currently_authorized_cost_usd != 0:
            raise ValueError("an unapproved plan must authorize zero spend")
        return self


class RepeatTrialApprovalRecord(BaseModel):
    """Human approval of one exact proposal; it never executes provider work."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    approval_id: Literal["northstar-rfp-repeat-trials-v1-approval"] = (
        "northstar-rfp-repeat-trials-v1-approval"
    )
    plan_id: Literal["northstar-rfp-repeat-trials-v1"] = REPEAT_TRIAL_PLAN_ID
    status: Literal["APPROVED"] = "APPROVED"
    proposal_path: Literal["data/evaluation/repeat_trial_plan_v1.json"] = (
        "data/evaluation/repeat_trial_plan_v1.json"
    )
    proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_by: str = Field(min_length=1)
    approved_at: str = Field(min_length=1)
    authorized_cost_usd: float = Field(gt=0, le=5.12)
    currency: Literal["USD"] = "USD"
    repeat_case_ids: list[str] = Field(min_length=4, max_length=4)
    total_trials_per_selected_case: Literal[3] = 3
    max_total_architecture_execution_count: Literal[64] = 64
    max_provider_calls_total: Literal[128] = 128
    max_total_input_tokens: Literal[1024000] = 1_024_000
    max_total_output_tokens: Literal[256000] = 256_000
    budget_authorized: Literal[True] = True
    implementation_review_required: Literal[True] = True
    paid_command_approved: Literal[False] = False
    comparative_runs_completed: Literal[0] = 0
    provider_calls_made: Literal[0] = 0

    @model_validator(mode="after")
    def approval_matches_frozen_scope(self) -> RepeatTrialApprovalRecord:
        if self.repeat_case_ids != list(SELECTED_REPEAT_CASE_IDS):
            raise ValueError("approval repeat subset drifted from the proposal")
        parsed = datetime.fromisoformat(self.approved_at)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("approved_at must include a timezone")
        if not self.approved_by.strip():
            raise ValueError("approved_by cannot be blank")
        return self


_REPEAT_CASE_RATIONALES = {
    "EVAL-001": (
        [VariabilityDimension.SIMPLE_STABILITY_CONTROL],
        "Simple directly supported Product case used as a low-complexity stability control.",
    ),
    "EVAL-002": (
        [VariabilityDimension.ROUTING_AND_TOOL_SELECTION],
        "Cross-domain case where variable tool selection or peer synthesis could change coverage.",
    ),
    "EVAL-015": (
        [VariabilityDimension.CONFLICT_AND_AUTHORITY_ESCALATION],
        "Combined weak-evidence, conflict, authority, and adversarial case where safe escalation must remain stable.",
    ),
    "EVAL-021": (
        [VariabilityDimension.EVIDENCE_GAP_AND_BOUNDED_RECOVERY],
        "Absent direct evidence tests whether unsupported assurance and bounded recovery remain stable.",
    ),
}


def _load_pricing(path: Path = DEFAULT_PRICING_SNAPSHOT_PATH) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    required = {
        "pricing_snapshot_id",
        "provider",
        "model",
        "input_usd_per_unit",
        "output_usd_per_unit",
        "billing_unit_tokens",
    }
    if not required.issubset(payload):
        raise EvaluationTrialPlanError("pricing snapshot is missing required fields")
    if payload["provider"] != "OpenAI API" or payload["model"] != "gpt-5.6-terra":
        raise EvaluationTrialPlanError("pricing snapshot provider or model drifted")
    if payload["billing_unit_tokens"] != 1_000_000:
        raise EvaluationTrialPlanError("pricing snapshot billing unit drifted")
    return payload


def build_repeat_trial_proposal() -> RepeatTrialPlan:
    dataset = load_evaluation_dataset()
    validate_frozen_gold(dataset)
    cases_by_id = {case.case_id: case for case in dataset.cases}
    pricing = _load_pricing()
    repeat_cases = []
    for case_id in SELECTED_REPEAT_CASE_IDS:
        case = cases_by_id[case_id]
        dimensions, rationale = _REPEAT_CASE_RATIONALES[case_id]
        repeat_cases.append(
            RepeatCasePlan(
                case_id=case.case_id,
                requirement_id=case.requirement_id,
                case_families=case.case_families,
                variability_dimensions=dimensions,
                rationale=rationale,
                additional_trial_numbers=[2, 3],
            )
        )
    return RepeatTrialPlan(
        status=TrialPlanStatus.AWAITING_APPROVAL,
        prepared_at=REPEAT_TRIAL_PREPARED_AT,
        frozen_dataset_sha256=file_sha256(DEFAULT_EVALUATION_DATASET_PATH),
        fair_comparison_sha256=file_sha256(DEFAULT_FAIR_COMPARISON_PATH),
        shared_safety_policy_sha256=file_sha256(DEFAULT_SHARED_SAFETY_POLICY_PATH),
        architectures=list(ComparisonArchitecture),
        primary_case_ids=list(EXPECTED_CASE_IDS),
        repeat_cases=repeat_cases,
        excluded_deterministic_stop_case_ids=["EVAL-023", "EVAL-024"],
        budget=TrialBudget(
            pricing_snapshot_id=str(pricing["pricing_snapshot_id"]),
            pricing_snapshot_sha256=file_sha256(DEFAULT_PRICING_SNAPSHOT_PATH),
            input_usd_per_million_tokens=float(pricing["input_usd_per_unit"]),
            output_usd_per_million_tokens=float(pricing["output_usd_per_unit"]),
            currently_authorized_cost_usd=0,
        ),
        provider_execution_authorized=False,
    )


def approve_repeat_trial_plan(
    plan: RepeatTrialPlan,
    *,
    reviewer: str,
    approved_at: datetime,
    authorized_cost_usd: float,
) -> RepeatTrialPlan:
    if plan.status is not TrialPlanStatus.AWAITING_APPROVAL:
        raise EvaluationTrialPlanError("only an awaiting-approval plan can be approved")
    if not reviewer.strip():
        raise EvaluationTrialPlanError("reviewer cannot be blank")
    if approved_at.tzinfo is None or approved_at.utcoffset() is None:
        raise EvaluationTrialPlanError("approved_at must include a timezone")
    if not 0 < authorized_cost_usd <= plan.budget.proposed_hard_cost_cap_usd:
        raise EvaluationTrialPlanError("authorized cost must be positive and no greater than the proposed hard cap")
    payload = plan.model_dump(mode="json")
    payload.update(
        status=TrialPlanStatus.APPROVED.value,
        approved_by=reviewer.strip(),
        approved_at=approved_at.isoformat(),
        provider_execution_authorized=True,
    )
    payload["budget"]["currently_authorized_cost_usd"] = authorized_cost_usd
    return RepeatTrialPlan.model_validate(payload)


def build_repeat_trial_approval_record(
    plan: RepeatTrialPlan,
    *,
    expected_proposal_sha256: str,
    reviewer: str,
    approved_at: datetime,
    authorized_cost_usd: float,
) -> RepeatTrialApprovalRecord:
    _, observed_digest = serialize_repeat_trial_plan(plan)
    if observed_digest != expected_proposal_sha256:
        raise EvaluationTrialPlanError(
            "proposal SHA-256 does not match the explicitly approved plan"
        )
    approved_plan = approve_repeat_trial_plan(
        plan,
        reviewer=reviewer,
        approved_at=approved_at,
        authorized_cost_usd=authorized_cost_usd,
    )
    return RepeatTrialApprovalRecord(
        proposal_sha256=observed_digest,
        approved_by=approved_plan.approved_by or "",
        approved_at=approved_plan.approved_at or "",
        authorized_cost_usd=approved_plan.budget.currently_authorized_cost_usd,
        repeat_case_ids=[case.case_id for case in approved_plan.repeat_cases],
    )


def require_provider_execution_approval(plan: RepeatTrialPlan) -> None:
    if plan.status is not TrialPlanStatus.APPROVED or not plan.provider_execution_authorized:
        raise EvaluationTrialPlanError(
            "provider execution requires explicit approval of the frozen repeat-trial plan and budget"
        )


def validate_trial_request(
    plan: RepeatTrialPlan,
    *,
    case_id: str,
    trial_number: int,
) -> None:
    if case_id not in plan.primary_case_ids:
        raise EvaluationTrialPlanError(f"unknown frozen case ID: {case_id}")
    if trial_number < 1:
        raise EvaluationTrialPlanError("trial number must be at least one")
    if trial_number == 1:
        return
    repeat_ids = {case.case_id for case in plan.repeat_cases}
    if case_id not in repeat_ids:
        raise EvaluationTrialPlanError(
            f"{case_id} is not in the predefined repeat subset"
        )
    if trial_number > plan.total_trials_per_selected_case:
        raise EvaluationTrialPlanError(
            f"trial number exceeds the frozen maximum of {plan.total_trials_per_selected_case}"
        )


def serialize_repeat_trial_plan(plan: RepeatTrialPlan) -> tuple[str, str]:
    content = json.dumps(plan.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def serialize_repeat_trial_approval(
    approval: RepeatTrialApprovalRecord,
) -> tuple[str, str]:
    content = json.dumps(approval.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def render_repeat_trial_review_packet(plan: RepeatTrialPlan) -> str:
    content, digest = serialize_repeat_trial_plan(plan)
    del content
    lines = [
        "# Repeat-Trial Plan — V1 Review Packet",
        "",
        f"**Status:** {plan.status.value}; provider execution is not authorized.",
        f"**Plan SHA-256:** `{digest}`",
        "",
        "## Proposed repeated cases",
        "",
        "| Case | Requirement | Why variability matters | Total trials |",
        "|---|---|---|---:|",
    ]
    for case in plan.repeat_cases:
        lines.append(
            f"| {case.case_id} | {case.requirement_id} | {case.rationale} | "
            f"{plan.total_trials_per_selected_case} |"
        )
    lines.extend(
        [
            "",
            "Trial 1 is the case's primary comparison run. Only Trials 2 and 3 are additional repeats.",
            "EVAL-023 and EVAL-024 are not repeated because their correct deterministic pre-model stops remove model variability.",
            "",
            "## Execution and cost ceiling",
            "",
            f"- Primary paired executions: {plan.primary_architecture_execution_count}",
            f"- Additional repeat executions: {plan.additional_repeat_architecture_execution_count}",
            f"- Maximum architecture executions: {plan.max_total_architecture_execution_count}",
            f"- Maximum provider calls: {plan.budget.max_provider_calls_total}",
            f"- Proposed hard cost cap: ${plan.budget.proposed_hard_cost_cap_usd:.2f}",
            f"- Currently authorized spend: ${plan.budget.currently_authorized_cost_usd:.2f}",
            "- Automatic provider retries: forbidden",
            "- Stop before the next call if any call, token, execution, or cost ceiling would be exceeded.",
            "",
            "The $5.12 value is a worst-case ceiling calculated from the frozen dated pricing snapshot and token envelope, not an expected charge or spending target.",
            "",
            "## Approval boundary",
            "",
            "No provider comparison or repeated trial may run until the user explicitly approves this exact plan and names an authorized USD cap no greater than $5.12. Approval of this review packet does not itself implement or execute a provider-backed architecture.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_exact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise EvaluationTrialPlanError(f"refusing to overwrite different content: {path.name}")
    path.write_text(content, encoding="utf-8")


def write_repeat_trial_proposal(
    plan: RepeatTrialPlan,
    *,
    output_path: Path = DEFAULT_REPEAT_TRIAL_PLAN_PATH,
    review_path: Path = DEFAULT_REPEAT_TRIAL_REVIEW_PATH,
) -> tuple[str, str]:
    if plan.status is not TrialPlanStatus.AWAITING_APPROVAL:
        raise EvaluationTrialPlanError("proposal writer accepts only an unapproved plan")
    content, digest = serialize_repeat_trial_plan(plan)
    _write_exact(output_path, content)
    _write_exact(output_path.with_suffix(".sha256"), f"{digest}  {output_path.name}\n")
    _write_exact(review_path, render_repeat_trial_review_packet(plan))
    return content, digest


def write_repeat_trial_approval(
    approval: RepeatTrialApprovalRecord,
    *,
    output_path: Path = DEFAULT_REPEAT_TRIAL_APPROVAL_PATH,
) -> tuple[str, str]:
    content, digest = serialize_repeat_trial_approval(approval)
    _write_exact(output_path, content)
    _write_exact(output_path.with_suffix(".sha256"), f"{digest}  {output_path.name}\n")
    return content, digest


def load_repeat_trial_plan(path: Path = DEFAULT_REPEAT_TRIAL_PLAN_PATH) -> RepeatTrialPlan:
    return RepeatTrialPlan.model_validate_json(path.read_text(encoding="utf-8"))


def load_repeat_trial_approval(
    path: Path = DEFAULT_REPEAT_TRIAL_APPROVAL_PATH,
) -> RepeatTrialApprovalRecord:
    return RepeatTrialApprovalRecord.model_validate_json(path.read_text(encoding="utf-8"))
