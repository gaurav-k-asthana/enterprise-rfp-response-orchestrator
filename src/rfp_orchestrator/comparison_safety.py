"""Step 4.10 bindings that give both comparison arms one safety policy."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_freeze import file_sha256, text_sha256
from rfp_orchestrator.fair_comparison import (
    COMPARISON_ID,
    DEFAULT_FAIR_COMPARISON_PATH,
    ComparisonArchitecture,
)
from rfp_orchestrator.generalist_baseline import GeneralistBaselineResult
from rfp_orchestrator.models import Requirement, RiskClass
from rfp_orchestrator.risk_authority import (
    IMMEDIATE_AUTHORITY_RISKS,
    RISK_AUTHORITY_RULES,
    AuthorityOwner,
    PreflightSafetyAssessment,
    RiskAuthorityAssessment,
    RiskAuthorityInput,
    RiskConflictFact,
    RiskResponse,
    assess_preflight_safety,
    assess_risk_authority_input,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
POLICY_ID = "northstar-rfp-shared-safety-v1"
POLICY_FROZEN_AT = "2026-09-03T23:22:25-04:00"
DEFAULT_SHARED_SAFETY_POLICY_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "shared_safety_policy_v1.json"
)
DEFAULT_SHARED_SAFETY_POLICY_DIGEST_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "shared_safety_policy_v1.sha256"
)

POST_EVIDENCE_CHECKS = (
    "citation_valid",
    "source_metadata_valid",
    "claim_support_valid",
    "commitment_consistent",
    "recovery_not_exhausted",
    "conflict_resolved",
)


class PostEvidenceSafetyFacts(BaseModel):
    """Architecture-independent validations supplied after an answer is produced."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    citation_valid: bool | None
    source_metadata_valid: bool | None
    claim_support_valid: bool | None
    commitment_consistent: bool | None
    conflicts: list[RiskConflictFact] = Field(default_factory=list)
    recovery_exhausted: bool = False
    conflict_unresolved: bool = False


class FrozenRiskRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    risk_class: RiskClass
    evaluation_stage: Literal["preflight_and_post_evidence", "post_evidence"]
    reason: str = Field(min_length=1)
    authority_owners: list[AuthorityOwner] = Field(min_length=1)


class FrozenPreflightPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    prompt_injection_action: Literal["NEEDS_HUMAN_BEFORE_RETRIEVAL"]
    prompt_injection_bypass_allowed: Literal[False] = False
    immediate_authority_risks: list[RiskClass]
    other_initial_risks_continue_to_evidence: Literal[True] = True


class FrozenPostEvidencePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    required_clear_checks: list[str]
    affirmative_unsupported_action: Literal["NEEDS_HUMAN"]
    unresolved_conflict_action: Literal["NEEDS_HUMAN"]
    multi_contributor_conflict_adds_specialist_disagreement: Literal[True] = True
    exhausted_recovery_action: Literal["NEEDS_HUMAN"]
    incomplete_unclassified_facts_action: Literal["FAIL_CLOSED"]
    no_risk_and_all_checks_pass_action: Literal["CLEAR"]

    @model_validator(mode="after")
    def checks_are_exact(self) -> FrozenPostEvidencePolicy:
        if tuple(self.required_clear_checks) != POST_EVIDENCE_CHECKS:
            raise ValueError("shared post-evidence checks drifted")
        return self


class SafetyPolicyBinding(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    architecture: ComparisonArchitecture
    policy_id: Literal["northstar-rfp-shared-safety-v1"] = POLICY_ID
    preflight_callable: Literal[
        "risk_authority.assess_preflight_safety"
    ] = "risk_authority.assess_preflight_safety"
    post_evidence_engine: Literal[
        "risk_authority.assess_risk_authority_input"
    ] = "risk_authority.assess_risk_authority_input"
    architecture_specific_bypass_allowed: Literal[False] = False


class SharedSafetyPolicyFreeze(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    policy_id: Literal["northstar-rfp-shared-safety-v1"] = POLICY_ID
    status: Literal["FROZEN"] = "FROZEN"
    frozen_at: str
    comparison_id: Literal["northstar-rfp-fair-comparison-v1"] = COMPARISON_ID
    fair_comparison_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    preflight: FrozenPreflightPolicy
    post_evidence: FrozenPostEvidencePolicy
    risk_rules: list[FrozenRiskRule]
    bindings: list[SafetyPolicyBinding] = Field(min_length=2, max_length=2)
    shared_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_sha256: dict[str, str]
    verification: dict[str, bool | int]

    @model_validator(mode="after")
    def freeze_is_shared_and_complete(self) -> SharedSafetyPolicyFreeze:
        if [binding.architecture for binding in self.bindings] != list(
            ComparisonArchitecture
        ):
            raise ValueError("safety bindings must contain both architectures in order")
        if any(binding.policy_id != self.policy_id for binding in self.bindings):
            raise ValueError("comparison arms must bind the same safety policy")
        if len(self.risk_rules) != len(RiskClass):
            raise ValueError("shared safety freeze must include every risk class")
        if self.shared_policy_sha256 != shared_policy_sha256(self):
            raise ValueError("shared safety policy checksum drifted")
        return self


def assess_comparison_preflight(
    architecture: ComparisonArchitecture,
    requirement: Requirement,
) -> PreflightSafetyAssessment:
    """Use one preflight function for either named architecture."""

    ComparisonArchitecture(architecture)
    return assess_preflight_safety(requirement)


def assess_comparison_post_evidence(
    architecture: ComparisonArchitecture,
    facts: RiskAuthorityInput,
) -> RiskAuthorityAssessment:
    """Use one post-evidence rule engine for either named architecture."""

    ComparisonArchitecture(architecture)
    return assess_risk_authority_input(facts)


def build_generalist_risk_input(
    requirement: Requirement,
    result: GeneralistBaselineResult,
    facts: PostEvidenceSafetyFacts,
) -> RiskAuthorityInput:
    """Adapt one generalist result without pretending it came from specialists."""

    if result.requirement_id != requirement.requirement_id:
        raise ValueError("generalist result belongs to another requirement")
    if assess_preflight_safety(requirement).requires_human:
        raise ValueError("post-evidence baseline safety cannot bypass a preflight stop")
    return RiskAuthorityInput(
        initial_risk_flags=requirement.initial_risk_flags,
        responses=[
            RiskResponse(
                contributor_id="generalist",
                claims=result.claims,
                proposed_answer=result.proposed_answer,
                support_status=result.support_status,
            )
        ],
        **facts.model_dump(),
    )


def assess_generalist_risk_authority(
    requirement: Requirement,
    result: GeneralistBaselineResult,
    facts: PostEvidenceSafetyFacts,
) -> RiskAuthorityAssessment:
    """Run a baseline result through the same engine used by the graph."""

    normalized = build_generalist_risk_input(requirement, result, facts)
    return assess_comparison_post_evidence(
        ComparisonArchitecture.SINGLE_GENERALIST,
        normalized,
    )


def _risk_rules() -> list[FrozenRiskRule]:
    return [
        FrozenRiskRule(
            risk_class=risk_class,
            evaluation_stage=(
                "preflight_and_post_evidence"
                if risk_class in IMMEDIATE_AUTHORITY_RISKS
                else "post_evidence"
            ),
            reason=RISK_AUTHORITY_RULES[risk_class][0],
            authority_owners=RISK_AUTHORITY_RULES[risk_class][1],
        )
        for risk_class in RiskClass
    ]


def _policy_payload(freeze: SharedSafetyPolicyFreeze) -> dict[str, object]:
    return freeze.model_dump(
        mode="json",
        include={"preflight", "post_evidence", "risk_rules"},
    )


def _canonical_sha256(value: object) -> str:
    content = json.dumps(value, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return text_sha256(content)


def shared_policy_sha256(freeze: SharedSafetyPolicyFreeze) -> str:
    return _canonical_sha256(_policy_payload(freeze))


def build_shared_safety_policy_freeze() -> SharedSafetyPolicyFreeze:
    """Build the secret-free policy release that binds both comparison arms."""

    preflight = FrozenPreflightPolicy(
        prompt_injection_action="NEEDS_HUMAN_BEFORE_RETRIEVAL",
        immediate_authority_risks=[
            risk for risk in RiskClass if risk in IMMEDIATE_AUTHORITY_RISKS
        ],
        other_initial_risks_continue_to_evidence=True,
    )
    post_evidence = FrozenPostEvidencePolicy(
        required_clear_checks=list(POST_EVIDENCE_CHECKS),
        affirmative_unsupported_action="NEEDS_HUMAN",
        unresolved_conflict_action="NEEDS_HUMAN",
        exhausted_recovery_action="NEEDS_HUMAN",
        incomplete_unclassified_facts_action="FAIL_CLOSED",
        no_risk_and_all_checks_pass_action="CLEAR",
    )
    rules = _risk_rules()
    provisional = SharedSafetyPolicyFreeze.model_construct(
        frozen_at=POLICY_FROZEN_AT,
        fair_comparison_artifact_sha256=file_sha256(DEFAULT_FAIR_COMPARISON_PATH),
        preflight=preflight,
        post_evidence=post_evidence,
        risk_rules=rules,
        bindings=[
            SafetyPolicyBinding(architecture=architecture)
            for architecture in ComparisonArchitecture
        ],
        shared_policy_sha256="0" * 64,
        source_sha256={
            "src/rfp_orchestrator/risk_authority.py": file_sha256(
                PROJECT_ROOT / "src" / "rfp_orchestrator" / "risk_authority.py"
            ),
            "src/rfp_orchestrator/orchestrator.py": file_sha256(
                PROJECT_ROOT / "src" / "rfp_orchestrator" / "orchestrator.py"
            ),
            "src/rfp_orchestrator/comparison_safety.py": file_sha256(Path(__file__)),
        },
        verification={
            "same_preflight_policy": True,
            "same_post_evidence_engine": True,
            "architecture_specific_bypass_allowed": False,
            "risk_class_count": len(RiskClass),
            "comparative_cases_run": 0,
            "network_calls_made": 0,
        },
    )
    payload = provisional.model_dump(mode="json")
    payload["shared_policy_sha256"] = shared_policy_sha256(provisional)
    return SharedSafetyPolicyFreeze.model_validate(payload)


def validate_shared_safety_policy_freeze(
    freeze: SharedSafetyPolicyFreeze,
) -> None:
    if freeze != build_shared_safety_policy_freeze():
        raise ValueError("frozen shared safety policy drifted")


def serialize_shared_safety_policy_freeze(
    freeze: SharedSafetyPolicyFreeze,
) -> tuple[str, str]:
    content = json.dumps(freeze.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def write_shared_safety_policy_freeze(
    output_path: Path = DEFAULT_SHARED_SAFETY_POLICY_PATH,
) -> tuple[str, str]:
    freeze = build_shared_safety_policy_freeze()
    validate_shared_safety_policy_freeze(freeze)
    content, digest = serialize_shared_safety_policy_freeze(freeze)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != content:
        raise ValueError("refusing to overwrite a different shared safety freeze")
    output_path.write_text(content, encoding="utf-8")
    digest_path = output_path.with_suffix(".sha256")
    digest_content = f"{digest}  {output_path.name}\n"
    if digest_path.exists() and digest_path.read_text(encoding="utf-8") != digest_content:
        raise ValueError("refusing to overwrite a different safety checksum")
    digest_path.write_text(digest_content, encoding="utf-8")
    return content, digest
