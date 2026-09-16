"""Normalized commitment comparison without conflict routing for Step 2.18."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from rfp_orchestrator.commitment_ledger import ProposedCommitment
from rfp_orchestrator.commitment_promotion import AuthoritativeCommitment
from rfp_orchestrator.models import CommitmentType
from rfp_orchestrator.state import GraphState


class CommitmentConsistencyError(ValueError):
    """Raised when commitment state cannot be compared safely."""


class CommitmentComparisonStatus(str, Enum):
    NEW = "NEW"
    CONSISTENT = "CONSISTENT"
    CONFLICT = "CONFLICT"


class CommitmentConflictKind(str, Enum):
    PRIOR_AUTHORITATIVE = "PRIOR_AUTHORITATIVE"
    CURRENT_PROPOSALS = "CURRENT_PROPOSALS"


class CommitmentConflict(BaseModel):
    conflict_id: str = Field(min_length=1)
    conflict_kind: CommitmentConflictKind
    commitment_type: CommitmentType
    comparison_key: str = Field(min_length=1)
    proposal_ids: list[str] = Field(min_length=1)
    proposed_values: list[str] = Field(min_length=1)
    prior_commitment_ids: list[str] = Field(default_factory=list)
    prior_values: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def conflict_has_distinct_values(self) -> CommitmentConflict:
        list_fields = {
            "proposal_ids": self.proposal_ids,
            "proposed_values": self.proposed_values,
            "prior_commitment_ids": self.prior_commitment_ids,
            "prior_values": self.prior_values,
        }
        if any(len(values) != len(set(values)) for values in list_fields.values()):
            raise ValueError("commitment conflict lists cannot contain duplicates")
        if self.conflict_kind is CommitmentConflictKind.PRIOR_AUTHORITATIVE:
            if not self.prior_commitment_ids or not self.prior_values:
                raise ValueError("prior conflict requires authoritative provenance")
        elif len(self.proposed_values) < 2:
            raise ValueError("current-proposal conflict requires two distinct values")
        return self


class CommitmentComparison(BaseModel):
    proposal_id: str = Field(min_length=1)
    commitment_type: CommitmentType
    comparison_key: str = Field(min_length=1)
    proposed_value: str = Field(min_length=1)
    status: CommitmentComparisonStatus
    prior_commitment_ids: list[str] = Field(default_factory=list)
    prior_values: list[str] = Field(default_factory=list)
    sibling_proposal_ids: list[str] = Field(default_factory=list)
    sibling_values: list[str] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def comparison_status_matches_conflicts(self) -> CommitmentComparison:
        if len(self.conflict_ids) != len(set(self.conflict_ids)):
            raise ValueError("comparison conflict IDs cannot repeat")
        if self.status is CommitmentComparisonStatus.CONFLICT:
            if not self.conflict_ids:
                raise ValueError("conflict comparison requires a conflict ID")
        elif self.conflict_ids:
            raise ValueError("non-conflict comparison cannot reference conflicts")
        if self.status is CommitmentComparisonStatus.CONSISTENT:
            if not self.prior_commitment_ids:
                raise ValueError("consistent comparison requires prior commitments")
            if set(self.prior_values) != {self.proposed_value}:
                raise ValueError("consistent prior values must equal the proposal")
        if (
            self.status is CommitmentComparisonStatus.NEW
            and self.prior_commitment_ids
        ):
            raise ValueError("new comparison cannot have prior commitments")
        return self


class CommitmentConsistencyResult(BaseModel):
    consistent: bool
    comparisons: list[CommitmentComparison] = Field(default_factory=list)
    conflicts: list[CommitmentConflict] = Field(default_factory=list)

    @model_validator(mode="after")
    def aggregate_matches_conflicts(self) -> CommitmentConsistencyResult:
        if self.consistent != (not self.conflicts):
            raise ValueError("consistency is true exactly when conflicts are absent")
        proposal_ids = [item.proposal_id for item in self.comparisons]
        conflict_ids = [item.conflict_id for item in self.conflicts]
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("commitment comparisons cannot repeat proposal IDs")
        if len(conflict_ids) != len(set(conflict_ids)):
            raise ValueError("commitment conflicts cannot repeat IDs")
        known_conflicts = set(conflict_ids)
        if any(
            conflict_id not in known_conflicts
            for comparison in self.comparisons
            for conflict_id in comparison.conflict_ids
        ):
            raise ValueError("comparison references an unknown conflict")
        return self


_CANONICAL_VALUE = re.compile(r"^[a-z0-9][a-z0-9.,-]*(?::[a-z0-9][a-z0-9.,-]*)+$")


def commitment_comparison_key(
    commitment_type: CommitmentType,
    normalized_value: str,
) -> str:
    """Return the material subject whose values must remain consistent."""

    if not _CANONICAL_VALUE.fullmatch(normalized_value):
        raise CommitmentConsistencyError(
            "normalized commitment value is not in canonical comparison form"
        )
    subject = normalized_value.split(":", 1)[0]
    if commitment_type is CommitmentType.RETENTION_PERIOD:
        subject = "customer-content-post-termination"
    return f"{commitment_type.value}:{subject}"


def _validated_state(
    state: GraphState,
) -> tuple[list[ProposedCommitment], list[AuthoritativeCommitment]]:
    try:
        proposals = [
            ProposedCommitment.model_validate(item)
            for item in state.get("proposed_commitments", [])
        ]
        prior = [
            AuthoritativeCommitment.model_validate(item)
            for item in state.get("commitments", [])
        ]
    except (TypeError, ValueError) as error:
        raise CommitmentConsistencyError(
            "commitment comparison received malformed proposal or authoritative state"
        ) from error
    proposal_ids = [item.proposal_id for item in proposals]
    prior_ids = [item.proposal_id for item in prior]
    if len(proposal_ids) != len(set(proposal_ids)):
        raise CommitmentConsistencyError("proposed commitment IDs cannot repeat")
    if len(prior_ids) != len(set(prior_ids)):
        raise CommitmentConsistencyError("authoritative commitment IDs cannot repeat")
    requirement_id = state.get("requirement_id")
    if any(item.source_requirement_id != requirement_id for item in proposals):
        raise CommitmentConsistencyError(
            "proposed commitment belongs to another requirement"
        )
    return proposals, prior


def compare_commitments(state: GraphState) -> CommitmentConsistencyResult:
    """Compare current proposals with prior approved values and current siblings."""

    proposals, prior = _validated_state(state)
    proposal_keys = {
        item.proposal_id: commitment_comparison_key(
            item.commitment_type,
            item.normalized_value,
        )
        for item in proposals
    }
    prior_keys = {
        item.proposal_id: commitment_comparison_key(
            item.commitment_type,
            item.normalized_value,
        )
        for item in prior
    }

    conflicts: list[CommitmentConflict] = []
    conflict_ids_by_proposal: dict[str, list[str]] = {
        item.proposal_id: [] for item in proposals
    }

    proposals_by_key: dict[str, list[ProposedCommitment]] = {}
    for proposal in proposals:
        proposals_by_key.setdefault(proposal_keys[proposal.proposal_id], []).append(
            proposal
        )
    for comparison_key, siblings in proposals_by_key.items():
        values = list(dict.fromkeys(item.normalized_value for item in siblings))
        if len(values) < 2:
            continue
        proposal_ids = [item.proposal_id for item in siblings]
        conflict_id = f"commitment-current:{comparison_key}"
        conflict = CommitmentConflict(
            conflict_id=conflict_id,
            conflict_kind=CommitmentConflictKind.CURRENT_PROPOSALS,
            commitment_type=siblings[0].commitment_type,
            comparison_key=comparison_key,
            proposal_ids=proposal_ids,
            proposed_values=values,
            reason="Current proposals contain different values for the same subject.",
        )
        conflicts.append(conflict)
        for proposal_id in proposal_ids:
            conflict_ids_by_proposal[proposal_id].append(conflict_id)

    comparisons: list[CommitmentComparison] = []
    for proposal in proposals:
        comparison_key = proposal_keys[proposal.proposal_id]
        same_key_prior = [
            item
            for item in prior
            if prior_keys[item.proposal_id] == comparison_key
        ]
        differing_prior = [
            item
            for item in same_key_prior
            if item.normalized_value != proposal.normalized_value
        ]
        if differing_prior:
            conflict_id = f"commitment-prior:{proposal.proposal_id}"
            conflict = CommitmentConflict(
                conflict_id=conflict_id,
                conflict_kind=CommitmentConflictKind.PRIOR_AUTHORITATIVE,
                commitment_type=proposal.commitment_type,
                comparison_key=comparison_key,
                proposal_ids=[proposal.proposal_id],
                proposed_values=[proposal.normalized_value],
                prior_commitment_ids=[item.proposal_id for item in differing_prior],
                prior_values=list(
                    dict.fromkeys(item.normalized_value for item in differing_prior)
                ),
                reason=(
                    "Proposed value differs from prior approved authoritative memory."
                ),
            )
            conflicts.append(conflict)
            conflict_ids_by_proposal[proposal.proposal_id].append(conflict_id)

        siblings = [
            item
            for item in proposals_by_key[comparison_key]
            if item.proposal_id != proposal.proposal_id
        ]
        proposal_conflict_ids = conflict_ids_by_proposal[proposal.proposal_id]
        if proposal_conflict_ids:
            status = CommitmentComparisonStatus.CONFLICT
        elif same_key_prior:
            status = CommitmentComparisonStatus.CONSISTENT
        else:
            status = CommitmentComparisonStatus.NEW
        comparisons.append(
            CommitmentComparison(
                proposal_id=proposal.proposal_id,
                commitment_type=proposal.commitment_type,
                comparison_key=comparison_key,
                proposed_value=proposal.normalized_value,
                status=status,
                prior_commitment_ids=[item.proposal_id for item in same_key_prior],
                prior_values=list(
                    dict.fromkeys(item.normalized_value for item in same_key_prior)
                ),
                sibling_proposal_ids=[item.proposal_id for item in siblings],
                sibling_values=list(
                    dict.fromkeys(item.normalized_value for item in siblings)
                ),
                conflict_ids=proposal_conflict_ids,
            )
        )

    return CommitmentConsistencyResult(
        consistent=not conflicts,
        comparisons=comparisons,
        conflicts=conflicts,
    )


def commitment_consistency_node(state: GraphState) -> GraphState:
    """Persist comparison output without routing or mutating either ledger."""

    result = compare_commitments(state)
    return {
        "commitment_consistent": result.consistent,
        "commitment_consistency": result.model_dump(mode="json"),
    }
