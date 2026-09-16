"""Hard evidence, consistency, authority, and candidate guard for Step 2.23."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from rfp_orchestrator.commitment_consistency import CommitmentConsistencyResult
from rfp_orchestrator.models import (
    ApprovalDecision,
    HumanApproval,
    RequirementStatus,
    SpecialistOutput,
    SupportStatus,
)
from rfp_orchestrator.risk_authority import (
    AuthorityGateStatus,
    RiskAuthorityAssessment,
)
from rfp_orchestrator.state import GraphState
from rfp_orchestrator.strategy import immediate_hitl, strategy_state_update


class FinalizationError(ValueError):
    """Raised when finalization receives malformed or contradictory state."""


class FinalizationStatus(str, Enum):
    FINALIZED = "FINALIZED"
    BLOCKED = "BLOCKED"


class FinalAnswerSource(str, Enum):
    GENERATED = "GENERATED"
    HUMAN_APPROVED = "HUMAN_APPROVED"
    HUMAN_EDITED = "HUMAN_EDITED"


class FinalizationResult(BaseModel):
    status: FinalizationStatus
    evidence_acceptable: bool
    consistency_clear: bool
    authority_resolved: bool
    candidate_integrity_passed: bool
    answer_source: FinalAnswerSource | None = None
    final_answer: str | None = None
    blocking_reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def result_matches_status(self) -> FinalizationResult:
        checks = (
            self.evidence_acceptable,
            self.consistency_clear,
            self.authority_resolved,
            self.candidate_integrity_passed,
        )
        if self.status is FinalizationStatus.FINALIZED:
            if not all(checks):
                raise ValueError("finalized result requires every guard to pass")
            if not self.final_answer or not self.final_answer.strip():
                raise ValueError("finalized result requires a nonblank answer")
            if self.answer_source is None:
                raise ValueError("finalized result requires an answer source")
            if self.blocking_reasons:
                raise ValueError("finalized result cannot contain blocking reasons")
        else:
            if all(checks):
                raise ValueError("blocked result requires at least one failed guard")
            if self.final_answer is not None or self.answer_source is not None:
                raise ValueError("blocked result cannot expose a final answer")
            if not self.blocking_reasons:
                raise ValueError("blocked result requires an auditable reason")
        if len(self.blocking_reasons) != len(set(self.blocking_reasons)):
            raise ValueError("finalization blocking reasons cannot repeat")
        return self


_NUMBER = re.compile(r"\b\d+(?:[.,]\d+)*(?:%|\b)")
_WORD = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", re.IGNORECASE)
_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "in",
        "is",
        "it",
        "no",
        "not",
        "of",
        "on",
        "or",
        "our",
        "the",
        "this",
        "to",
        "we",
        "with",
    }
)


def _material_terms(text: str) -> set[str]:
    return {
        token.casefold()
        for token in _WORD.findall(text)
        if token.casefold() not in _STOPWORDS and len(token) > 2
    }


def _validated_outputs(state: GraphState) -> list[SpecialistOutput]:
    raw_outputs = state.get("merged_specialist_outputs", [])
    if not isinstance(raw_outputs, list):
        raise FinalizationError("finalization received malformed specialist output")
    try:
        outputs = [SpecialistOutput.model_validate(item) for item in raw_outputs]
    except (TypeError, ValueError) as error:
        raise FinalizationError("finalization received malformed specialist output") from error
    return outputs


def _validated_consistency(
    state: GraphState,
) -> CommitmentConsistencyResult | None:
    raw_result = state.get("commitment_consistency")
    if raw_result is None:
        if state.get("commitment_consistent") is not None:
            raise FinalizationError("finalization consistency fields disagree")
        return None
    if not isinstance(raw_result, dict):
        raise FinalizationError("finalization received malformed consistency state")
    try:
        result = CommitmentConsistencyResult.model_validate(raw_result)
    except (TypeError, ValueError) as error:
        raise FinalizationError("finalization received malformed consistency state") from error
    if state.get("commitment_consistent") is not result.consistent:
        raise FinalizationError("finalization consistency fields disagree")
    return result


def _validated_authority(state: GraphState) -> RiskAuthorityAssessment | None:
    raw_assessment = state.get("risk_assessment")
    if raw_assessment is None:
        if (
            state.get("authority_gate_passed") is not None
            or state.get("authority_required") is True
            or state.get("risk_classes", [])
            or state.get("authority_owners", [])
        ):
            raise FinalizationError("finalization authority fields lack an assessment")
        return None
    if not isinstance(raw_assessment, dict):
        raise FinalizationError("finalization received malformed authority state")
    try:
        assessment = RiskAuthorityAssessment.model_validate(raw_assessment)
    except (TypeError, ValueError) as error:
        raise FinalizationError("finalization received malformed authority state") from error
    if state.get("risk_classes", []) != [item.value for item in assessment.risk_classes]:
        raise FinalizationError("finalization risk classes disagree with the assessment")
    if state.get("authority_owners", []) != [
        item.value for item in assessment.authority_owners
    ]:
        raise FinalizationError("finalization authority owners disagree with assessment")
    if state.get("authority_required") is not assessment.requires_human:
        raise FinalizationError("finalization authority-required fields disagree")
    if state.get("authority_gate_passed") is not (not assessment.requires_human):
        raise FinalizationError("finalization authority-gate fields disagree")
    return assessment


def _approval(state: GraphState) -> HumanApproval | None:
    raw_approval = state.get("approval")
    if raw_approval is None:
        return None
    try:
        approval = HumanApproval.model_validate(raw_approval)
    except (TypeError, ValueError) as error:
        raise FinalizationError("finalization received malformed approval state") from error
    if approval.requirement_id != state.get("requirement_id"):
        raise FinalizationError("finalization approval belongs to another requirement")
    return approval


def _evidence_acceptable(
    state: GraphState,
    outputs: list[SpecialistOutput],
) -> bool:
    return (
        state.get("prompt_injection_detected") is False
        and bool(outputs)
        and state.get("citation_valid") is True
        and state.get("source_metadata_valid") is True
        and state.get("claim_support_valid") is True
        and all(output.support_status is SupportStatus.SUPPORTED for output in outputs)
        and all(claim.supported for output in outputs for claim in output.claims)
        and all(claim.evidence_ids for output in outputs for claim in output.claims)
        and state.get("recovery_needed") is False
        and state.get("recovery_exhausted") is False
    )


def _consistency_clear(
    state: GraphState,
    consistency: CommitmentConsistencyResult | None,
) -> bool:
    return (
        consistency is not None
        and consistency.consistent
        and not consistency.conflicts
        and state.get("conflict_unresolved") is False
        and state.get("conflict_reanalysis_needed") is False
        and not state.get("unresolved_conflict_ids", [])
    )


def _authority_resolved(
    assessment: RiskAuthorityAssessment | None,
    approval: HumanApproval | None,
) -> bool:
    if assessment is None:
        return False
    if assessment.status is AuthorityGateStatus.CLEAR:
        return approval is None or approval.decision in {
            ApprovalDecision.APPROVE,
            ApprovalDecision.EDIT_AND_APPROVE,
        }
    return approval is not None and approval.decision in {
        ApprovalDecision.APPROVE,
        ApprovalDecision.EDIT_AND_APPROVE,
    }


def _generated_answer(outputs: list[SpecialistOutput]) -> str:
    return "\n\n".join(output.proposed_answer.strip() for output in outputs)


def _answer_candidate(
    state: GraphState,
    outputs: list[SpecialistOutput],
    approval: HumanApproval | None,
) -> tuple[str, FinalAnswerSource, bool]:
    generated = _generated_answer(outputs)
    reviewed = state.get("reviewed_answer")
    if approval is None:
        return generated, FinalAnswerSource.GENERATED, reviewed is None
    if approval.decision is ApprovalDecision.APPROVE:
        return (
            generated,
            FinalAnswerSource.HUMAN_APPROVED,
            isinstance(reviewed, str) and reviewed == generated,
        )
    if approval.decision is ApprovalDecision.EDIT_AND_APPROVE:
        edited = approval.edited_answer or ""
        if not isinstance(reviewed, str) or reviewed != edited:
            return edited, FinalAnswerSource.HUMAN_EDITED, False
        generated_numbers = set(_NUMBER.findall(generated))
        edited_numbers = set(_NUMBER.findall(edited))
        edit_terms = _material_terms(edited)
        shared_terms = edit_terms.intersection(_material_terms(generated))
        overlap = len(shared_terms) / len(edit_terms) if edit_terms else 0.0
        integrity = edited_numbers.issubset(generated_numbers) and overlap >= 0.5
        return edited, FinalAnswerSource.HUMAN_EDITED, integrity
    return "", FinalAnswerSource.GENERATED, False


def evaluate_finalization(state: GraphState) -> FinalizationResult:
    """Evaluate every hard guard without mutating graph state."""

    outputs = _validated_outputs(state)
    consistency = _validated_consistency(state)
    assessment = _validated_authority(state)
    approval = _approval(state)
    evidence_ok = _evidence_acceptable(state, outputs)
    consistency_ok = _consistency_clear(state, consistency)
    authority_ok = _authority_resolved(assessment, approval)
    candidate, answer_source, candidate_ok = _answer_candidate(
        state,
        outputs,
        approval,
    )

    if state.get("awaiting_human_review") is True:
        authority_ok = False
    if state.get("final_status") == RequirementStatus.REJECTED.value:
        authority_ok = False
        candidate_ok = False
    if state.get("final_answer") is not None:
        candidate_ok = False

    reasons: list[str] = []
    if not evidence_ok:
        reasons.append("Evidence, citation, source, claim-support, or recovery state is unsafe.")
    if not consistency_ok:
        reasons.append("Commitment consistency or conflict state is unresolved.")
    if not authority_ok:
        reasons.append("Organizational authority is unresolved or the decision is non-approving.")
    if not candidate_ok:
        reasons.append("The answer candidate is missing, altered, rejected, or insufficiently grounded.")

    if reasons:
        return FinalizationResult(
            status=FinalizationStatus.BLOCKED,
            evidence_acceptable=evidence_ok,
            consistency_clear=consistency_ok,
            authority_resolved=authority_ok,
            candidate_integrity_passed=candidate_ok,
            blocking_reasons=reasons,
        )
    return FinalizationResult(
        status=FinalizationStatus.FINALIZED,
        evidence_acceptable=True,
        consistency_clear=True,
        authority_resolved=True,
        candidate_integrity_passed=True,
        answer_source=answer_source,
        final_answer=candidate,
    )


def finalization_guard_node(state: GraphState) -> GraphState:
    """Write a final answer only after every deterministic guard passes."""

    result = evaluate_finalization(state)
    update: GraphState = {
        "finalization_result": result.model_dump(mode="json"),
        "finalization_passed": result.status is FinalizationStatus.FINALIZED,
    }
    if result.status is FinalizationStatus.FINALIZED:
        update.update(
            {
                "final_status": RequirementStatus.FINALIZED.value,
                "final_answer": result.final_answer,
                "awaiting_human_review": False,
            }
        )
        return update

    update["final_answer"] = None
    if state.get("final_status") == RequirementStatus.REJECTED.value:
        update["final_status"] = RequirementStatus.REJECTED.value
        return update
    update.update(
        strategy_state_update(
            immediate_hitl("Finalization blocked: " + " ".join(result.blocking_reasons))
        )
    )
    update["final_status"] = RequirementStatus.NEEDS_HUMAN.value
    return update
