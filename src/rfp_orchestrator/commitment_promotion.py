"""Approved-and-finalized commitment promotion boundary for Step 2.17."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from rfp_orchestrator.commitment_ledger import ProposedCommitment
from rfp_orchestrator.models import (
    ApprovalDecision,
    Commitment,
    Domain,
    HumanApproval,
    RequirementStatus,
)
from rfp_orchestrator.state import GraphState


class CommitmentPromotionError(ValueError):
    """Raised when authoritative-ledger promotion would be unsafe."""


class CommitmentPromotionStatus(str, Enum):
    NO_SELECTION = "NO_SELECTION"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    AWAITING_FINALIZATION = "AWAITING_FINALIZATION"
    BLOCKED = "BLOCKED"
    PROMOTED = "PROMOTED"


class AuthoritativeCommitment(Commitment):
    """A finalized commitment with explicit human-approval provenance."""

    proposal_id: str = Field(min_length=1)
    source_claim_id: str = Field(min_length=1)
    specialist: Domain
    evidence_ids: list[str] = Field(min_length=1)
    approved: Literal[True] = True
    approval_decision: ApprovalDecision
    approved_by: str = Field(min_length=1)
    approved_at: str = Field(min_length=1)
    final_status: Literal[RequirementStatus.FINALIZED] = RequirementStatus.FINALIZED

    @model_validator(mode="after")
    def authoritative_record_has_approval_provenance(
        self,
    ) -> AuthoritativeCommitment:
        if self.approval_decision not in {
            ApprovalDecision.APPROVE,
            ApprovalDecision.EDIT_AND_APPROVE,
        }:
            raise ValueError("authoritative commitment requires an approving decision")
        text_fields = {
            "proposal_id": self.proposal_id,
            "normalized_value": self.normalized_value,
            "source_requirement_id": self.source_requirement_id,
            "source_claim_id": self.source_claim_id,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }
        if any(not value.strip() for value in text_fields.values()):
            raise ValueError("authoritative commitment fields cannot be blank")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("authoritative commitment evidence IDs cannot repeat")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("authoritative commitment evidence IDs cannot be blank")
        return self


class CommitmentPromotionResult(BaseModel):
    """Auditable outcome of one authoritative-ledger promotion decision."""

    status: CommitmentPromotionStatus
    selected_proposal_ids: list[str] = Field(default_factory=list)
    promoted_commitments: list[AuthoritativeCommitment] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def result_matches_status(self) -> CommitmentPromotionResult:
        if len(self.selected_proposal_ids) != len(set(self.selected_proposal_ids)):
            raise ValueError("selected proposal IDs cannot repeat")
        if any(not proposal_id.strip() for proposal_id in self.selected_proposal_ids):
            raise ValueError("selected proposal IDs cannot be blank")
        if self.status is CommitmentPromotionStatus.PROMOTED:
            promoted_ids = [item.proposal_id for item in self.promoted_commitments]
            if promoted_ids != self.selected_proposal_ids:
                raise ValueError(
                    "promoted commitments must exactly match selected proposal IDs"
                )
        elif self.promoted_commitments:
            raise ValueError("non-promoted results cannot contain commitments")
        return self


_APPROVING_DECISIONS = {
    ApprovalDecision.APPROVE,
    ApprovalDecision.EDIT_AND_APPROVE,
}


def _existing_authoritative_ledger(state: GraphState) -> list[AuthoritativeCommitment]:
    try:
        ledger = [
            AuthoritativeCommitment.model_validate(item)
            for item in state.get("commitments", [])
        ]
    except (TypeError, ValueError) as error:
        raise CommitmentPromotionError(
            "authoritative ledger contains an invalid or unapproved record"
        ) from error
    proposal_ids = [item.proposal_id for item in ledger]
    if len(proposal_ids) != len(set(proposal_ids)):
        raise CommitmentPromotionError(
            "authoritative ledger contains duplicate proposal IDs"
        )
    return ledger


def _selected_proposals(state: GraphState) -> list[ProposedCommitment]:
    raw_ids = state.get("approved_proposal_ids", [])
    if not isinstance(raw_ids, list) or any(
        not isinstance(item, str) or not item.strip() for item in raw_ids
    ):
        raise CommitmentPromotionError(
            "approved_proposal_ids must be a list of nonblank strings"
        )
    if len(raw_ids) != len(set(raw_ids)):
        raise CommitmentPromotionError("approved_proposal_ids cannot repeat")

    try:
        proposals = [
            ProposedCommitment.model_validate(item)
            for item in state.get("proposed_commitments", [])
        ]
    except (TypeError, ValueError) as error:
        raise CommitmentPromotionError("proposed commitment state is malformed") from error
    proposals_by_id = {item.proposal_id: item for item in proposals}
    if len(proposals_by_id) != len(proposals):
        raise CommitmentPromotionError("proposed commitment IDs cannot repeat")
    unknown = [proposal_id for proposal_id in raw_ids if proposal_id not in proposals_by_id]
    if unknown:
        raise CommitmentPromotionError(
            "approved_proposal_ids contains a proposal not present in draft state"
        )
    return [proposals_by_id[proposal_id] for proposal_id in raw_ids]


def _approval_from_state(state: GraphState) -> HumanApproval | None:
    raw_approval = state.get("approval")
    if raw_approval is None:
        return None
    try:
        approval = HumanApproval.model_validate(raw_approval)
    except (TypeError, ValueError) as error:
        raise CommitmentPromotionError("approval state is malformed") from error
    if approval.requirement_id != state.get("requirement_id"):
        raise CommitmentPromotionError(
            "approval requirement does not match the current requirement"
        )
    return approval


def promote_approved_commitments(
    state: GraphState,
) -> tuple[CommitmentPromotionResult, list[AuthoritativeCommitment]]:
    """Promote only explicitly selected, approved, and finalized proposals."""

    existing = _existing_authoritative_ledger(state)
    selected = _selected_proposals(state)
    selected_ids = [item.proposal_id for item in selected]
    if not selected:
        return (
            CommitmentPromotionResult(
                status=CommitmentPromotionStatus.NO_SELECTION,
                reason="No draft commitment proposal was selected for promotion.",
            ),
            existing,
        )

    approval = _approval_from_state(state)
    if approval is None:
        return (
            CommitmentPromotionResult(
                status=CommitmentPromotionStatus.AWAITING_APPROVAL,
                selected_proposal_ids=selected_ids,
                reason="Selected proposals require an explicit human approval.",
            ),
            existing,
        )
    if approval.decision not in _APPROVING_DECISIONS:
        return (
            CommitmentPromotionResult(
                status=CommitmentPromotionStatus.BLOCKED,
                selected_proposal_ids=selected_ids,
                reason=(
                    f"Human decision {approval.decision.value} does not authorize "
                    "commitment promotion."
                ),
            ),
            existing,
        )

    final_status = state.get("final_status")
    if final_status is not None:
        try:
            parsed_status = RequirementStatus(final_status)
        except ValueError as error:
            raise CommitmentPromotionError("final_status is invalid") from error
    else:
        parsed_status = None
    if parsed_status is not RequirementStatus.FINALIZED:
        return (
            CommitmentPromotionResult(
                status=CommitmentPromotionStatus.AWAITING_FINALIZATION,
                selected_proposal_ids=selected_ids,
                reason="Approved proposals cannot enter memory before finalization.",
            ),
            existing,
        )

    existing_by_id = {item.proposal_id: item for item in existing}
    promoted: list[AuthoritativeCommitment] = []
    for proposal in selected:
        authoritative = AuthoritativeCommitment(
            proposal_id=proposal.proposal_id,
            commitment_type=proposal.commitment_type,
            normalized_value=proposal.normalized_value,
            source_requirement_id=proposal.source_requirement_id,
            source_claim_id=proposal.source_claim_id,
            specialist=proposal.specialist,
            evidence_ids=list(proposal.evidence_ids),
            approval_decision=approval.decision,
            approved_by=approval.reviewer,
            approved_at=approval.timestamp,
        )
        prior = existing_by_id.get(proposal.proposal_id)
        if prior is not None and prior != authoritative:
            raise CommitmentPromotionError(
                "an authoritative record conflicts with the selected proposal"
            )
        if prior is None:
            existing.append(authoritative)
            existing_by_id[proposal.proposal_id] = authoritative
        promoted.append(existing_by_id[proposal.proposal_id])

    return (
        CommitmentPromotionResult(
            status=CommitmentPromotionStatus.PROMOTED,
            selected_proposal_ids=selected_ids,
            promoted_commitments=promoted,
            reason="Selected proposals were approved and finalized.",
        ),
        existing,
    )


def commitment_promotion_node(state: GraphState) -> GraphState:
    """Record promotion status and mutate authoritative memory only on success."""

    result, ledger = promote_approved_commitments(state)
    update: GraphState = {
        "commitment_promotion": result.model_dump(mode="json"),
    }
    if result.status is CommitmentPromotionStatus.PROMOTED:
        update["commitments"] = [item.model_dump(mode="json") for item in ledger]
    return update
