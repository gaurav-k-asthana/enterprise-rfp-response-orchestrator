"""Deterministic post-evidence risk and organizational-authority gate."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.commitment_consistency import (
    CommitmentConflictKind,
    CommitmentConsistencyResult,
)
from rfp_orchestrator.commitment_ledger import ProposedCommitment
from rfp_orchestrator.models import (
    Claim,
    Requirement,
    RequirementStatus,
    RiskClass,
    SpecialistOutput,
    SupportStatus,
    aggregate_support,
)
from rfp_orchestrator.state import GraphState
from rfp_orchestrator.strategy import immediate_hitl, strategy_state_update


class RiskAuthorityError(ValueError):
    """Raised when the post-evidence authority gate cannot evaluate safely."""


class AuthorityGateStatus(str, Enum):
    CLEAR = "CLEAR"
    NEEDS_HUMAN = "NEEDS_HUMAN"


class RiskFindingSource(str, Enum):
    INITIAL_REQUIREMENT = "INITIAL_REQUIREMENT"
    EVIDENCE_JUDGMENT = "EVIDENCE_JUDGMENT"
    GRAPH_STATE = "GRAPH_STATE"


class AuthorityOwner(str, Enum):
    PRODUCT_OWNER = "PRODUCT_OWNER"
    SECURITY_LEGAL = "SECURITY_LEGAL"
    DELIVERY_OWNER = "DELIVERY_OWNER"
    COMMERCIAL_LEGAL = "COMMERCIAL_LEGAL"
    PROPOSAL_REVIEWER = "PROPOSAL_REVIEWER"


class RiskFinding(BaseModel):
    risk_class: RiskClass
    source: RiskFindingSource
    reason: str = Field(min_length=1)
    authority_owners: list[AuthorityOwner] = Field(min_length=1)

    @model_validator(mode="after")
    def owners_are_unique(self) -> RiskFinding:
        if len(self.authority_owners) != len(set(self.authority_owners)):
            raise ValueError("risk finding authority owners cannot repeat")
        return self


class RiskAuthorityAssessment(BaseModel):
    status: AuthorityGateStatus
    evidence_checks_passed: bool
    requires_human: bool
    risk_classes: list[RiskClass] = Field(default_factory=list)
    authority_owners: list[AuthorityOwner] = Field(default_factory=list)
    findings: list[RiskFinding] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def aggregate_matches_findings(self) -> RiskAuthorityAssessment:
        finding_classes = [item.risk_class for item in self.findings]
        finding_owners = list(
            dict.fromkeys(
                owner for item in self.findings for owner in item.authority_owners
            )
        )
        if self.risk_classes != finding_classes:
            raise ValueError("assessment risk classes must match its ordered findings")
        if self.authority_owners != finding_owners:
            raise ValueError("assessment authority owners must match its findings")
        if self.requires_human != bool(self.findings):
            raise ValueError("human review is required exactly when a risk is found")
        expected = (
            AuthorityGateStatus.NEEDS_HUMAN
            if self.requires_human
            else AuthorityGateStatus.CLEAR
        )
        if self.status is not expected:
            raise ValueError("authority status must match requires_human")
        if not self.evidence_checks_passed and not self.requires_human:
            raise ValueError("incomplete evidence checks cannot produce a clear decision")
        return self


class PreflightSafetyAssessment(BaseModel):
    """Architecture-neutral decision made before either arm may retrieve."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: AuthorityGateStatus
    requires_human: bool
    prompt_injection_detected: bool
    risk_classes: list[RiskClass] = Field(default_factory=list)
    authority_owners: list[AuthorityOwner] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def decision_is_consistent(self) -> PreflightSafetyAssessment:
        if len(self.risk_classes) != len(set(self.risk_classes)):
            raise ValueError("preflight risk classes cannot repeat")
        if len(self.authority_owners) != len(set(self.authority_owners)):
            raise ValueError("preflight authority owners cannot repeat")
        expected = (
            AuthorityGateStatus.NEEDS_HUMAN
            if self.requires_human
            else AuthorityGateStatus.CLEAR
        )
        if self.status is not expected:
            raise ValueError("preflight status must match requires_human")
        if self.prompt_injection_detected and not self.requires_human:
            raise ValueError("prompt injection cannot clear preflight")
        if not self.requires_human and (self.risk_classes or self.authority_owners):
            raise ValueError("clear preflight cannot carry authority findings")
        return self


class RiskResponse(BaseModel):
    """One answer contribution normalized without inventing an agent role."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contributor_id: str = Field(min_length=1)
    claims: list[Claim]
    proposed_answer: str = Field(min_length=1)
    support_status: SupportStatus

    @model_validator(mode="after")
    def response_is_valid(self) -> RiskResponse:
        if not self.contributor_id.strip() or not self.proposed_answer.strip():
            raise ValueError("risk response text fields cannot be blank")
        if self.support_status is not aggregate_support(self.claims):
            raise ValueError("risk response support status must aggregate from claims")
        return self


class RiskConflictFact(BaseModel):
    """Conflict facts needed by the shared gate, independent of graph shape."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    conflict_id: str = Field(min_length=1)
    conflict_kind: CommitmentConflictKind
    proposal_ids: list[str] = Field(min_length=1)
    contributor_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def conflict_is_valid(self) -> RiskConflictFact:
        collections = (self.proposal_ids, self.contributor_ids)
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("risk conflict facts cannot contain duplicate IDs")
        if any(not value.strip() for values in collections for value in values):
            raise ValueError("risk conflict IDs cannot be blank")
        return self


class RiskAuthorityInput(BaseModel):
    """The sole architecture-neutral input accepted by the shared rule engine."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    initial_risk_flags: list[RiskClass] = Field(default_factory=list)
    responses: list[RiskResponse] = Field(default_factory=list)
    citation_valid: bool | None
    source_metadata_valid: bool | None
    claim_support_valid: bool | None
    commitment_consistent: bool | None
    conflicts: list[RiskConflictFact] = Field(default_factory=list)
    recovery_exhausted: bool = False
    conflict_unresolved: bool = False

    @model_validator(mode="after")
    def facts_are_consistent(self) -> RiskAuthorityInput:
        if len(self.initial_risk_flags) != len(set(self.initial_risk_flags)):
            raise ValueError("authority gate initial risks cannot repeat")
        contributor_ids = [item.contributor_id for item in self.responses]
        if len(contributor_ids) != len(set(contributor_ids)):
            raise ValueError("risk response contributor IDs cannot repeat")
        conflict_ids = [item.conflict_id for item in self.conflicts]
        if len(conflict_ids) != len(set(conflict_ids)):
            raise ValueError("risk conflict IDs cannot repeat")
        if self.commitment_consistent is None and not self.recovery_exhausted:
            raise ValueError("authority gate requires commitment consistency state")
        if self.commitment_consistent is True and self.conflicts:
            raise ValueError("consistent commitment facts cannot contain conflicts")
        if self.commitment_consistent is False and not self.conflicts:
            raise ValueError("inconsistent commitment facts require conflicts")
        if self.conflict_unresolved != bool(self.conflicts):
            raise ValueError("conflict_unresolved must match conflict facts")
        return self


RISK_AUTHORITY_RULES: dict[RiskClass, tuple[str, list[AuthorityOwner]]] = {
    RiskClass.UNSUPPORTED_CATEGORICAL_YES: (
        "An affirmative response is not supported by every atomic claim.",
        [AuthorityOwner.PROPOSAL_REVIEWER],
    ),
    RiskClass.ROADMAP_COMMITMENT: (
        "A roadmap date or delivery promise requires Product-owner approval.",
        [AuthorityOwner.PRODUCT_OWNER],
    ),
    RiskClass.PRICING_OR_DISCOUNT: (
        "Pricing or discount terms require Commercial or Legal approval.",
        [AuthorityOwner.COMMERCIAL_LEGAL],
    ),
    RiskClass.SLA_OR_SERVICE_CREDIT: (
        (
            "A new uptime SLA or service-credit commitment requires Commercial and "
            "Legal approval."
        ),
        [AuthorityOwner.COMMERCIAL_LEGAL],
    ),
    RiskClass.WARRANTY_OR_INDEMNITY: (
        "Warranty or indemnity terms require Commercial or Legal approval.",
        [AuthorityOwner.COMMERCIAL_LEGAL],
    ),
    RiskClass.SECURITY_EXCEPTION: (
        "A security exception or unverified assurance requires Security and Legal approval.",
        [AuthorityOwner.SECURITY_LEGAL],
    ),
    RiskClass.DATA_RESIDENCY_AMBIGUITY: (
        "A material data-residency ambiguity requires Security and Legal review.",
        [AuthorityOwner.SECURITY_LEGAL],
    ),
    RiskClass.CONFLICTING_EVIDENCE: (
        "Conflicting evidence must be presented for human review.",
        [AuthorityOwner.PROPOSAL_REVIEWER],
    ),
    RiskClass.SPECIALIST_DISAGREEMENT: (
        "Peer specialists disagree on a material current proposal.",
        [AuthorityOwner.PROPOSAL_REVIEWER],
    ),
    RiskClass.RETRY_BUDGET_EXHAUSTED: (
        "The bounded evidence-recovery budget is exhausted.",
        [AuthorityOwner.PROPOSAL_REVIEWER],
    ),
}

IMMEDIATE_AUTHORITY_RISKS = frozenset(
    {
        RiskClass.PRICING_OR_DISCOUNT,
        RiskClass.WARRANTY_OR_INDEMNITY,
    }
)

_AFFIRMATIVE_START = re.compile(
    r"^(?:yes\b|confirmed\b|we confirm\b|northstar supports\b|the platform supports\b)",
    re.IGNORECASE,
)


def _evidence_checks_passed(facts: RiskAuthorityInput) -> bool:
    return (
        facts.citation_valid is True
        and facts.source_metadata_valid is True
        and facts.claim_support_valid is True
        and facts.commitment_consistent is True
        and not facts.recovery_exhausted
        and not facts.conflict_unresolved
    )


def _validated_outputs(state: GraphState) -> list[SpecialistOutput]:
    try:
        return [
            SpecialistOutput.model_validate(item)
            for item in state.get("merged_specialist_outputs", [])
        ]
    except (TypeError, ValueError) as error:
        raise RiskAuthorityError(
            "authority gate received malformed specialist output"
        ) from error


def _unsupported_categorical_yes(outputs: list[RiskResponse]) -> bool:
    return any(
        _AFFIRMATIVE_START.search(output.proposed_answer.strip()) is not None
        and (
            output.support_status.value != "SUPPORTED"
            or any(not claim.supported for claim in output.claims)
        )
        for output in outputs
    )


def _conflict_facts(state: GraphState) -> tuple[bool | None, list[RiskConflictFact]]:
    raw = state.get("commitment_consistency")
    if not isinstance(raw, dict):
        if state.get("recovery_exhausted", False):
            return None, []
        raise RiskAuthorityError("authority gate requires commitment consistency state")
    try:
        result = CommitmentConsistencyResult.model_validate(raw)
        proposals = [
            ProposedCommitment.model_validate(item)
            for item in state.get("proposed_commitments", [])
        ]
    except (TypeError, ValueError) as error:
        raise RiskAuthorityError(
            "authority gate received malformed consistency or proposal state"
        ) from error
    by_id = {item.proposal_id: item for item in proposals}
    if len(by_id) != len(proposals):
        raise RiskAuthorityError("authority gate proposal IDs cannot repeat")
    referenced_ids = {
        proposal_id
        for conflict in result.conflicts
        for proposal_id in conflict.proposal_ids
    }
    if not referenced_ids.issubset(by_id):
        raise RiskAuthorityError("authority gate conflict references an unknown proposal")

    facts: list[RiskConflictFact] = []
    for conflict in result.conflicts:
        contributors = list(
            dict.fromkeys(
                by_id[proposal_id].specialist.value
                for proposal_id in conflict.proposal_ids
                if proposal_id in by_id
            )
        )
        facts.append(
            RiskConflictFact(
                conflict_id=conflict.conflict_id,
                conflict_kind=conflict.conflict_kind,
                proposal_ids=list(conflict.proposal_ids),
                contributor_ids=contributors,
            )
        )
    return result.consistent, facts


def risk_authority_input_from_graph_state(state: GraphState) -> RiskAuthorityInput:
    outputs = _validated_outputs(state)
    commitment_consistent, conflicts = _conflict_facts(state)
    try:
        return RiskAuthorityInput(
            initial_risk_flags=state.get("initial_risk_flags", []),
            responses=[
                RiskResponse(
                    contributor_id=output.specialist.value,
                    claims=output.claims,
                    proposed_answer=output.proposed_answer,
                    support_status=output.support_status,
                )
                for output in outputs
            ],
            citation_valid=state.get("citation_valid"),
            source_metadata_valid=state.get("source_metadata_valid"),
            claim_support_valid=state.get("claim_support_valid"),
            commitment_consistent=commitment_consistent,
            conflicts=conflicts,
            recovery_exhausted=state.get("recovery_exhausted", False),
            conflict_unresolved=state.get("conflict_unresolved", False),
        )
    except (TypeError, ValueError) as error:
        raise RiskAuthorityError("authority gate received inconsistent safety facts") from error


def assess_preflight_safety(requirement: Requirement) -> PreflightSafetyAssessment:
    """Apply identical stop-before-retrieval rules to either architecture."""

    if requirement.prompt_injection_detected:
        return PreflightSafetyAssessment(
            status=AuthorityGateStatus.NEEDS_HUMAN,
            requires_human=True,
            prompt_injection_detected=True,
            authority_owners=[AuthorityOwner.PROPOSAL_REVIEWER],
            reason="Untrusted operating instructions require human review before routing.",
        )
    risks = [
        risk
        for risk in requirement.initial_risk_flags
        if risk in IMMEDIATE_AUTHORITY_RISKS
    ]
    if risks:
        owners = list(
            dict.fromkeys(
                owner
                for risk in risks
                for owner in RISK_AUTHORITY_RULES[risk][1]
            )
        )
        labels = ", ".join(risk.value for risk in risks)
        return PreflightSafetyAssessment(
            status=AuthorityGateStatus.NEEDS_HUMAN,
            requires_human=True,
            prompt_injection_detected=False,
            risk_classes=risks,
            authority_owners=owners,
            reason=(
                "Organizational authority is required before specialist work: "
                f"{labels}."
            ),
        )
    return PreflightSafetyAssessment(
        status=AuthorityGateStatus.CLEAR,
        requires_human=False,
        prompt_injection_detected=False,
        reason="No mandatory stop-before-retrieval safety signal was found.",
    )


def _finding(
    risk_class: RiskClass,
    source: RiskFindingSource,
) -> RiskFinding:
    reason, owners = RISK_AUTHORITY_RULES[risk_class]
    return RiskFinding(
        risk_class=risk_class,
        source=source,
        reason=reason,
        authority_owners=owners,
    )


def assess_risk_authority_input(
    facts: RiskAuthorityInput,
) -> RiskAuthorityAssessment:
    """Evaluate normalized facts with the rule engine shared by both arms."""

    evidence_checks_passed = _evidence_checks_passed(facts)
    initial = facts.initial_risk_flags

    findings: list[RiskFinding] = [
        _finding(risk, RiskFindingSource.INITIAL_REQUIREMENT) for risk in initial
    ]
    if _unsupported_categorical_yes(facts.responses) and all(
        item.risk_class is not RiskClass.UNSUPPORTED_CATEGORICAL_YES
        for item in findings
    ):
        findings.append(
            _finding(
                RiskClass.UNSUPPORTED_CATEGORICAL_YES,
                RiskFindingSource.EVIDENCE_JUDGMENT,
            )
        )
    if facts.conflicts and all(
        item.risk_class is not RiskClass.CONFLICTING_EVIDENCE
        for item in findings
    ):
        findings.append(
            _finding(RiskClass.CONFLICTING_EVIDENCE, RiskFindingSource.GRAPH_STATE)
        )
    if any(
        conflict.conflict_kind is CommitmentConflictKind.CURRENT_PROPOSALS
        and len(conflict.contributor_ids) > 1
        for conflict in facts.conflicts
    ) and all(
        item.risk_class is not RiskClass.SPECIALIST_DISAGREEMENT
        for item in findings
    ):
        findings.append(
            _finding(RiskClass.SPECIALIST_DISAGREEMENT, RiskFindingSource.GRAPH_STATE)
        )
    if facts.recovery_exhausted and all(
        item.risk_class is not RiskClass.RETRY_BUDGET_EXHAUSTED
        for item in findings
    ):
        findings.append(
            _finding(
                RiskClass.RETRY_BUDGET_EXHAUSTED,
                RiskFindingSource.GRAPH_STATE,
            )
        )

    if not evidence_checks_passed and not findings:
        raise RiskAuthorityError(
            "authority gate cannot clear incomplete evidence or consistency checks"
        )

    risk_classes = [item.risk_class for item in findings]
    owners = list(
        dict.fromkeys(owner for item in findings for owner in item.authority_owners)
    )
    requires_human = bool(findings)
    return RiskAuthorityAssessment(
        status=(
            AuthorityGateStatus.NEEDS_HUMAN
            if requires_human
            else AuthorityGateStatus.CLEAR
        ),
        evidence_checks_passed=evidence_checks_passed,
        requires_human=requires_human,
        risk_classes=risk_classes,
        authority_owners=owners,
        findings=findings,
        reason=(
            "Evidence checks passed, but organizational authority is still required."
            if requires_human and evidence_checks_passed
            else (
                "Evidence or consistency remains unresolved and requires human review."
                if requires_human
                else (
                    "Evidence and consistency checks passed with no mandatory "
                    "authority risk."
                )
            )
        ),
    )


def assess_risk_authority(state: GraphState) -> RiskAuthorityAssessment:
    """Adapt graph state into the same post-evidence rule engine used by baseline."""

    return assess_risk_authority_input(risk_authority_input_from_graph_state(state))


def risk_authority_node(state: GraphState) -> GraphState:
    assessment = assess_risk_authority(state)
    update: GraphState = {
        "risk_assessment": assessment.model_dump(mode="json"),
        "risk_classes": [item.value for item in assessment.risk_classes],
        "authority_required": assessment.requires_human,
        "authority_owners": [item.value for item in assessment.authority_owners],
        "authority_gate_passed": not assessment.requires_human,
    }
    if assessment.requires_human:
        rationale_prefix = (
            "Evidence is sufficient, but organizational authority is required"
            if assessment.evidence_checks_passed
            else "Evidence or consistency remains unresolved and human review is required"
        )
        update.update(
            strategy_state_update(
                immediate_hitl(
                    rationale_prefix
                    + ": "
                    + ", ".join(item.value for item in assessment.risk_classes)
                    + "."
                )
            )
        )
        update["final_status"] = RequirementStatus.NEEDS_HUMAN.value
        update["final_answer"] = None
    return update
