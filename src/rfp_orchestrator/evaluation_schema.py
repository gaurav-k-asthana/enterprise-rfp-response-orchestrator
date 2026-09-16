"""Typed contract for the 24-case synthetic RFP evaluation set."""

from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.corpus import SourceStatus
from rfp_orchestrator.models import (
    ApprovalDecision,
    Domain,
    RequirementStatus,
    RiskClass,
    StrategyType,
    SupportStatus,
)
from rfp_orchestrator.sample_requirements import (
    DEFAULT_SAMPLE_RFP_PATH,
    EXPECTED_REQUIREMENT_IDS,
    SampleRequirement,
    load_sample_requirements,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVALUATION_DATASET_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "evaluation_cases_v1.json"
)
EVALUATION_SCHEMA_VERSION = "1.0"
EVALUATION_DATASET_ID = "northstar-rfp-evaluation-v1"
EXPECTED_CASE_IDS = tuple(f"EVAL-{number:03d}" for number in range(1, 25))


class EvaluationCaseFamily(str, Enum):
    """The six coverage families assigned and reviewed in Step 4.2."""

    SIMPLE = "SIMPLE"
    CROSS_DOMAIN = "CROSS_DOMAIN"
    WEAK_EVIDENCE = "WEAK_EVIDENCE"
    CONFLICT = "CONFLICT"
    AUTHORITY_RISK = "AUTHORITY_RISK"
    ADVERSARIAL = "ADVERSARIAL"


class ExpectedHitlBehavior(str, Enum):
    """Whether correct execution should stop for human review."""

    NOT_REQUIRED = "NOT_REQUIRED"
    REQUIRED = "REQUIRED"
    CONDITIONAL = "CONDITIONAL"


class EvaluationFailureCategory(str, Enum):
    """Stable failure taxonomy for unsafe or incomplete evaluation outcomes."""

    ROUTING_FAILURE = "ROUTING_FAILURE"
    RETRIEVAL_MISS = "RETRIEVAL_MISS"
    RANKING_FUSION_FAILURE = "RANKING_FUSION_FAILURE"
    STALE_AUTHORITY_FAILURE = "STALE_AUTHORITY_FAILURE"
    EVIDENCE_GRADING_FAILURE = "EVIDENCE_GRADING_FAILURE"
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    CITATION_FAILURE = "CITATION_FAILURE"
    CONSISTENCY_FAILURE = "CONSISTENCY_FAILURE"
    AUTHORITY_FAILURE = "AUTHORITY_FAILURE"
    FALSE_ESCALATION = "FALSE_ESCALATION"
    RECOVERY_FAILURE = "RECOVERY_FAILURE"
    PROMPT_INJECTION_FAILURE = "PROMPT_INJECTION_FAILURE"
    OPERATIONAL_FAILURE = "OPERATIONAL_FAILURE"


class EvaluationReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"


class EvaluationDatasetStatus(str, Enum):
    DRAFT = "DRAFT"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    FROZEN = "FROZEN"


class ExpectedMaterialClaim(BaseModel):
    """One gold atomic claim and its expected binary evidence judgment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    specialist: Domain
    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    supported: bool
    evidence_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def identifiers_are_clean(self) -> ExpectedMaterialClaim:
        if not self.claim_id.strip() or not self.text.strip():
            raise ValueError("claim ID and text cannot be blank")
        _validate_unique_nonblank(self.evidence_ids, "claim evidence IDs")
        return self


class ExpectedAuthorityTier(BaseModel):
    """One equal-precedence group in expected evidence-source ordering."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source_status: SourceStatus
    authority_rank: int = Field(ge=1, le=5)
    evidence_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_ids_are_clean(self) -> ExpectedAuthorityTier:
        _validate_unique_nonblank(self.evidence_ids, "authority-tier evidence IDs")
        return self


class EvaluationGoldLabels(BaseModel):
    """All reviewed answers required before the dataset can be frozen."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_atomic_requirements: list[str] = Field(default_factory=list)
    expected_domains: list[Domain] = Field(default_factory=list)
    expected_strategy_family: StrategyType | None = None
    expected_specialists: list[Domain] = Field(default_factory=list)
    gold_evidence_ids: list[str] = Field(default_factory=list)
    expected_authority_order: list[ExpectedAuthorityTier] = Field(default_factory=list)
    expected_material_claims: list[ExpectedMaterialClaim] = Field(default_factory=list)
    expected_support_status: SupportStatus | None = None
    expected_risk_classes: list[RiskClass] = Field(default_factory=list)
    expected_hitl_behavior: ExpectedHitlBehavior | None = None
    allowed_human_outcomes: list[ApprovalDecision] = Field(default_factory=list)
    allowed_final_statuses: list[RequirementStatus] = Field(default_factory=list)
    failure_category: EvaluationFailureCategory | None = Field(
        default=None,
        description=(
            "Primary failure mode the case is designed to expose; this does not "
            "assert that a correct run failed."
        ),
    )
    rationale: str | None = None

    @model_validator(mode="after")
    def labels_are_internally_consistent(self) -> EvaluationGoldLabels:
        _validate_unique_nonblank(
            self.expected_atomic_requirements,
            "expected atomic requirements",
        )
        _validate_unique(self.expected_domains, "expected domains")
        _validate_unique(self.expected_specialists, "expected specialists")
        _validate_unique_nonblank(self.gold_evidence_ids, "gold evidence IDs")
        _validate_unique(self.expected_risk_classes, "expected risk classes")
        _validate_unique(self.allowed_human_outcomes, "allowed human outcomes")
        _validate_unique(self.allowed_final_statuses, "allowed final statuses")

        claim_ids = [claim.claim_id for claim in self.expected_material_claims]
        _validate_unique_nonblank(claim_ids, "expected material claim IDs")

        authority_priorities = [
            (
                1 if tier.source_status is SourceStatus.CURRENT else 0,
                tier.authority_rank,
            )
            for tier in self.expected_authority_order
        ]
        if len(authority_priorities) != len(set(authority_priorities)):
            raise ValueError(
                "equal-status and equal-rank evidence must share one authority tier"
            )
        if authority_priorities != sorted(authority_priorities, reverse=True):
            raise ValueError(
                "authority tiers must order current before archived, then higher rank first"
            )
        ordered_evidence_ids = [
            evidence_id
            for tier in self.expected_authority_order
            for evidence_id in tier.evidence_ids
        ]
        if ordered_evidence_ids != self.gold_evidence_ids:
            raise ValueError(
                "gold evidence IDs must exactly follow the expected authority tiers"
            )

        if not set(self.expected_specialists).issubset(self.expected_domains):
            raise ValueError("expected specialists must be a subset of expected domains")

        routing_is_labeled = bool(
            self.expected_domains
            or self.expected_specialists
            or self.expected_strategy_family is not None
        )
        if routing_is_labeled:
            if self.expected_strategy_family is None:
                raise ValueError("routing labels require an expected strategy family")
            if self.expected_strategy_family is StrategyType.SINGLE_SPECIALIST:
                if len(self.expected_domains) != 1 or len(self.expected_specialists) != 1:
                    raise ValueError(
                        "SINGLE_SPECIALIST gold requires one domain and one specialist"
                    )
                if self.expected_domains != self.expected_specialists:
                    raise ValueError(
                        "SINGLE_SPECIALIST gold domain and specialist must match"
                    )
            elif self.expected_strategy_family is StrategyType.PARALLEL_SPECIALISTS:
                if not 2 <= len(self.expected_domains) <= 3:
                    raise ValueError(
                        "PARALLEL_SPECIALISTS gold requires two or three domains"
                    )
                if self.expected_domains != self.expected_specialists:
                    raise ValueError(
                        "PARALLEL_SPECIALISTS gold must select every expected domain"
                    )
            elif self.expected_strategy_family is StrategyType.IMMEDIATE_HITL:
                if self.expected_domains or self.expected_specialists:
                    raise ValueError(
                        "IMMEDIATE_HITL initial gold cannot select a domain or specialist"
                    )
            else:
                raise ValueError(
                    "initial strategy gold must be single, parallel, or immediate HITL"
                )

        for claim in self.expected_material_claims:
            if claim.specialist not in self.expected_specialists:
                raise ValueError(
                    "expected claim specialist must be a selected specialist"
                )
            if not set(claim.evidence_ids).issubset(self.gold_evidence_ids):
                raise ValueError("claim evidence IDs must be gold evidence IDs")
            if claim.supported and not claim.evidence_ids:
                raise ValueError("a supported expected claim requires gold evidence")
            if not claim.supported and claim.evidence_ids:
                raise ValueError("an unsupported expected claim cannot cite gold evidence")

        if self.expected_support_status is not None:
            if not self.expected_atomic_requirements:
                raise ValueError(
                    "support labels require expected atomic requirements"
                )
            flags = [claim.supported for claim in self.expected_material_claims]
            aggregate = (
                SupportStatus.SUPPORTED
                if flags and all(flags)
                else SupportStatus.PARTIAL
                if any(flags)
                else SupportStatus.UNSUPPORTED
            )
            if self.expected_support_status is not aggregate:
                raise ValueError(
                    "expected support status must aggregate from claim.supported booleans"
                )
            if self.expected_specialists and not self.expected_material_claims:
                raise ValueError("a selected specialist requires expected material claims")
            if (
                self.expected_strategy_family is StrategyType.IMMEDIATE_HITL
                and self.expected_material_claims
            ):
                raise ValueError("IMMEDIATE_HITL cannot have specialist material claims")

        safety_is_labeled = bool(
            self.expected_risk_classes
            or self.expected_hitl_behavior is not None
            or self.allowed_human_outcomes
            or self.allowed_final_statuses
            or self.failure_category is not None
            or self.rationale is not None
        )
        if safety_is_labeled:
            if self.expected_hitl_behavior is None:
                raise ValueError("safety labels require expected HITL behavior")
            if not self.allowed_final_statuses:
                raise ValueError("safety labels require allowed final statuses")
            if self.failure_category is None:
                raise ValueError("safety labels require a primary failure category")
            if self.rationale is None or not self.rationale.strip():
                raise ValueError("safety labels require a nonblank rationale")

            terminal_statuses = {
                RequirementStatus.NEEDS_HUMAN,
                RequirementStatus.FINALIZED,
                RequirementStatus.REJECTED,
            }
            if not set(self.allowed_final_statuses).issubset(terminal_statuses):
                raise ValueError("allowed final statuses must be terminal outcomes")

            if self.expected_hitl_behavior is ExpectedHitlBehavior.NOT_REQUIRED:
                if self.expected_risk_classes or self.allowed_human_outcomes:
                    raise ValueError(
                        "NOT_REQUIRED HITL cannot have risk triggers or human outcomes"
                    )
                if self.allowed_final_statuses != [RequirementStatus.FINALIZED]:
                    raise ValueError(
                        "NOT_REQUIRED HITL must allow only FINALIZED"
                    )
            elif self.expected_hitl_behavior is ExpectedHitlBehavior.REQUIRED:
                if RequirementStatus.NEEDS_HUMAN not in self.allowed_final_statuses:
                    raise ValueError(
                        "REQUIRED HITL must allow NEEDS_HUMAN"
                    )
                if not self.allowed_human_outcomes:
                    raise ValueError(
                        "REQUIRED HITL must define allowed human outcomes"
                    )
            else:
                required_statuses = {
                    RequirementStatus.NEEDS_HUMAN,
                    RequirementStatus.FINALIZED,
                }
                if not required_statuses.issubset(self.allowed_final_statuses):
                    raise ValueError(
                        "CONDITIONAL HITL must allow NEEDS_HUMAN and FINALIZED"
                    )
                if not self.allowed_human_outcomes:
                    raise ValueError(
                        "CONDITIONAL HITL must define allowed human outcomes"
                    )

            if (
                ApprovalDecision.REJECT in self.allowed_human_outcomes
                and RequirementStatus.REJECTED not in self.allowed_final_statuses
            ):
                raise ValueError("REJECT outcome requires REJECTED final status")
            if (
                {
                    ApprovalDecision.APPROVE,
                    ApprovalDecision.EDIT_AND_APPROVE,
                }.intersection(self.allowed_human_outcomes)
                and RequirementStatus.FINALIZED not in self.allowed_final_statuses
            ):
                raise ValueError(
                    "approval outcomes require FINALIZED to be allowed"
                )
            if (
                self.expected_strategy_family is StrategyType.IMMEDIATE_HITL
                and self.expected_hitl_behavior is not ExpectedHitlBehavior.REQUIRED
            ):
                raise ValueError("IMMEDIATE_HITL requires REQUIRED HITL behavior")

        if self.rationale is not None and not self.rationale.strip():
            raise ValueError("evaluation rationale cannot be blank")
        return self


class EvaluationReview(BaseModel):
    """Human provenance for one case's reviewed gold labels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: EvaluationReviewStatus = EvaluationReviewStatus.DRAFT
    reviewer: str | None = None
    reviewed_at: datetime | None = None
    notes: str | None = None

    @model_validator(mode="after")
    def provenance_matches_status(self) -> EvaluationReview:
        has_reviewer = bool(self.reviewer and self.reviewer.strip())
        has_timestamp = self.reviewed_at is not None
        if self.status is EvaluationReviewStatus.DRAFT and (
            has_reviewer or has_timestamp
        ):
            raise ValueError("draft evaluation cases cannot claim review provenance")
        if self.status is not EvaluationReviewStatus.DRAFT and not (
            has_reviewer and has_timestamp
        ):
            raise ValueError("reviewed evaluation cases require reviewer and timestamp")
        if self.reviewer is not None and not self.reviewer.strip():
            raise ValueError("reviewer cannot be blank")
        if self.notes is not None and not self.notes.strip():
            raise ValueError("review notes cannot be blank")
        return self


class EvaluationCase(BaseModel):
    """One stable synthetic RFP input plus its future reviewed gold labels."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(pattern=r"^EVAL-\d{3}$")
    requirement_id: str = Field(pattern=r"^RFP-\d{3}$")
    untrusted_rfp_text: str = Field(min_length=1)
    case_families: list[EvaluationCaseFamily] = Field(default_factory=list)
    gold_labels: EvaluationGoldLabels = Field(default_factory=EvaluationGoldLabels)
    review: EvaluationReview = Field(default_factory=EvaluationReview)

    @model_validator(mode="after")
    def identity_and_families_are_valid(self) -> EvaluationCase:
        if self.case_id.removeprefix("EVAL-") != self.requirement_id.removeprefix(
            "RFP-"
        ):
            raise ValueError("evaluation and requirement numeric IDs must match")
        if not self.untrusted_rfp_text.strip():
            raise ValueError("untrusted RFP text cannot be blank")
        _validate_unique(self.case_families, "case families")
        return self


class EvaluationDataset(BaseModel):
    """Versioned evaluation dataset whose identity and order fail closed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["1.0"] = EVALUATION_SCHEMA_VERSION
    dataset_id: Literal["northstar-rfp-evaluation-v1"] = EVALUATION_DATASET_ID
    status: EvaluationDatasetStatus = EvaluationDatasetStatus.DRAFT
    source_rfp: Literal["data/sample_rfp.md"] = "data/sample_rfp.md"
    cases: list[EvaluationCase] = Field(min_length=24, max_length=24)

    @model_validator(mode="after")
    def case_set_is_exact(self) -> EvaluationDataset:
        case_ids = tuple(case.case_id for case in self.cases)
        requirement_ids = tuple(case.requirement_id for case in self.cases)
        if case_ids != EXPECTED_CASE_IDS:
            raise ValueError("dataset must contain ordered cases EVAL-001 through EVAL-024")
        if requirement_ids != EXPECTED_REQUIREMENT_IDS:
            raise ValueError(
                "dataset must contain ordered requirements RFP-001 through RFP-024"
            )

        expected_review_status = {
            EvaluationDatasetStatus.DRAFT: EvaluationReviewStatus.DRAFT,
            EvaluationDatasetStatus.READY_FOR_REVIEW: (
                EvaluationReviewStatus.READY_FOR_REVIEW
            ),
            EvaluationDatasetStatus.FROZEN: EvaluationReviewStatus.APPROVED,
        }[self.status]
        if any(
            case.review.status is not expected_review_status for case in self.cases
        ):
            raise ValueError(
                f"{self.status.value} dataset requires every case review to be "
                f"{expected_review_status.value}"
            )
        return self


def build_evaluation_skeleton(
    requirements: tuple[SampleRequirement, ...] | None = None,
) -> EvaluationDataset:
    """Create the deterministic, deliberately unlabeled Step 4.1 dataset."""

    source_requirements = requirements or load_sample_requirements()
    return EvaluationDataset(
        cases=[
            EvaluationCase(
                case_id=case_id,
                requirement_id=requirement.requirement_id,
                untrusted_rfp_text=requirement.text,
            )
            for case_id, requirement in zip(
                EXPECTED_CASE_IDS,
                source_requirements,
                strict=True,
            )
        ]
    )


def load_evaluation_dataset(
    path: str | Path = DEFAULT_EVALUATION_DATASET_PATH,
    requirements: tuple[SampleRequirement, ...] | None = None,
) -> EvaluationDataset:
    """Load the dataset and reject any drift from the canonical sample RFP."""

    source_path = Path(path)
    dataset = EvaluationDataset.model_validate(
        json.loads(source_path.read_text(encoding="utf-8"))
    )
    source_requirements = requirements or load_sample_requirements(DEFAULT_SAMPLE_RFP_PATH)
    expected_text_by_id = {
        item.requirement_id: item.text for item in source_requirements
    }
    for case in dataset.cases:
        if expected_text_by_id.get(case.requirement_id) != case.untrusted_rfp_text:
            raise ValueError(
                f"evaluation text does not match sample RFP for {case.requirement_id}"
            )
    return dataset


def _validate_unique(values: list[object], label: str) -> None:
    if len(values) != len(set(values)):
        raise ValueError(f"{label} cannot contain duplicates")


def _validate_unique_nonblank(values: list[str], label: str) -> None:
    if any(not value.strip() for value in values):
        raise ValueError(f"{label} cannot contain blank values")
    _validate_unique(values, label)
