"""One-pass targeted commitment-conflict reanalysis for Step 2.19."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from rfp_orchestrator.commitment_consistency import (
    CommitmentConflict,
    CommitmentConsistencyResult,
)
from rfp_orchestrator.commitment_ledger import ProposedCommitment
from rfp_orchestrator.models import Domain, RequirementStatus
from rfp_orchestrator.state import GraphState
from rfp_orchestrator.strategy import immediate_hitl, strategy_state_update


class ConflictResolutionError(ValueError):
    """Raised when targeted conflict reanalysis cannot proceed safely."""


class ConflictResolutionStatus(str, Enum):
    NOT_NEEDED = "NOT_NEEDED"
    REANALYSIS_REQUIRED = "REANALYSIS_REQUIRED"
    UNRESOLVED_NEEDS_HUMAN = "UNRESOLVED_NEEDS_HUMAN"


class ConflictReanalysisQuery(BaseModel):
    specialist: Domain
    original_query: str = Field(min_length=1)
    reanalysis_query: str = Field(min_length=1, max_length=800)
    conflict_ids: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def query_is_targeted_and_changed(self) -> ConflictReanalysisQuery:
        if len(self.conflict_ids) != len(set(self.conflict_ids)):
            raise ValueError("conflict query IDs cannot repeat")
        if any(not conflict_id.strip() for conflict_id in self.conflict_ids):
            raise ValueError("conflict query IDs cannot be blank")
        original = " ".join(self.original_query.casefold().split())
        reanalysis = " ".join(self.reanalysis_query.casefold().split())
        if original == reanalysis:
            raise ValueError("conflict reanalysis query must change the original")
        return self


class ConflictResolutionPlan(BaseModel):
    status: ConflictResolutionStatus
    conflicts: list[CommitmentConflict] = Field(default_factory=list)
    specialists: list[Domain] = Field(default_factory=list)
    queries: dict[str, ConflictReanalysisQuery] = Field(default_factory=dict)
    unresolved_conflict_ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def plan_matches_status(self) -> ConflictResolutionPlan:
        conflict_ids = [item.conflict_id for item in self.conflicts]
        if len(conflict_ids) != len(set(conflict_ids)):
            raise ValueError("conflict plan IDs cannot repeat")
        if len(self.specialists) != len(set(self.specialists)):
            raise ValueError("conflict specialists cannot repeat")
        if self.status is ConflictResolutionStatus.NOT_NEEDED:
            if self.conflicts or self.specialists or self.queries:
                raise ValueError("no-conflict plan cannot contain reanalysis work")
        elif self.status is ConflictResolutionStatus.REANALYSIS_REQUIRED:
            if not self.conflicts or not self.specialists:
                raise ValueError("reanalysis requires conflicts and specialists")
            if set(self.queries) != {
                specialist.value for specialist in self.specialists
            }:
                raise ValueError("every conflict specialist requires one query")
            if self.unresolved_conflict_ids:
                raise ValueError("first reanalysis cannot already be unresolved")
        else:
            if self.specialists or self.queries:
                raise ValueError("unresolved plan cannot schedule another reanalysis")
            if self.unresolved_conflict_ids != conflict_ids:
                raise ValueError("unresolved IDs must match detected conflicts")
        return self


class ConflictReanalysisAttempt(BaseModel):
    attempt_number: int = Field(ge=1, le=1)
    specialists: list[Domain] = Field(min_length=1)
    conflict_ids: list[str] = Field(min_length=1)
    queries: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def attempt_is_complete(self) -> ConflictReanalysisAttempt:
        if len(self.specialists) != len(set(self.specialists)):
            raise ValueError("conflict attempt specialists cannot repeat")
        if len(self.conflict_ids) != len(set(self.conflict_ids)):
            raise ValueError("conflict attempt IDs cannot repeat")
        if any(not conflict_id.strip() for conflict_id in self.conflict_ids):
            raise ValueError("conflict attempt IDs cannot be blank")
        if set(self.queries) != {
            specialist.value for specialist in self.specialists
        }:
            raise ValueError("conflict attempt requires one query per specialist")
        if any(not query.strip() for query in self.queries.values()):
            raise ValueError("conflict attempt queries cannot be blank")
        return self


_DOMAIN_FOCUS = {
    Domain.PRODUCT: (
        "current approved product availability deployment integration scope and "
        "explicit limitations"
    ),
    Domain.SECURITY: (
        "current approved security compliance data handling retention scope authority "
        "and explicit limitations"
    ),
    Domain.IMPLEMENTATION: (
        "current approved implementation prerequisites timeline scope dependencies "
        "and explicit limitations"
    ),
}


def _validated_inputs(
    state: GraphState,
) -> tuple[CommitmentConsistencyResult, dict[str, ProposedCommitment], int]:
    raw_result = state.get("commitment_consistency")
    if not isinstance(raw_result, dict):
        raise ConflictResolutionError("commitment consistency result is missing")
    try:
        result = CommitmentConsistencyResult.model_validate(raw_result)
        proposals = [
            ProposedCommitment.model_validate(item)
            for item in state.get("proposed_commitments", [])
        ]
    except (TypeError, ValueError) as error:
        raise ConflictResolutionError(
            "conflict resolution received malformed consistency or proposal state"
        ) from error
    proposals_by_id = {item.proposal_id: item for item in proposals}
    if len(proposals_by_id) != len(proposals):
        raise ConflictResolutionError("conflict proposal IDs cannot repeat")
    referenced_ids = {
        proposal_id
        for conflict in result.conflicts
        for proposal_id in conflict.proposal_ids
    }
    if not referenced_ids.issubset(proposals_by_id):
        raise ConflictResolutionError("conflict references an unknown proposal")
    count = state.get("conflict_reanalysis_count", 0)
    if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= 1:
        raise ConflictResolutionError("conflict reanalysis count must be 0 or 1")
    return result, proposals_by_id, count


def _query_for_specialist(
    state: GraphState,
    specialist: Domain,
    conflicts: list[CommitmentConflict],
) -> ConflictReanalysisQuery:
    original = " ".join(state.get("atomic_requirements", []))
    if not original:
        original = " ".join(str(state.get("original_text", "")).split())
    if not original:
        raise ConflictResolutionError("conflict reanalysis requires original text")
    conflict_ids = [item.conflict_id for item in conflicts]
    value_focus = list(
        dict.fromkeys(
            value
            for item in conflicts
            for value in [*item.proposed_values, *item.prior_values]
        )
    )
    additions = (
        f"Conflict reanalysis: {'; '.join(conflict_ids)}. "
        f"Reconcile exact values: {'; '.join(value_focus)}. "
        f"Evidence focus: {_DOMAIN_FOCUS[specialist]}."
    )
    query = f"{original} {additions}"
    if len(query) > 800:
        query = query[:800].rsplit(" ", 1)[0]
    return ConflictReanalysisQuery(
        specialist=specialist,
        original_query=original,
        reanalysis_query=query,
        conflict_ids=conflict_ids,
    )


def plan_conflict_resolution(state: GraphState) -> ConflictResolutionPlan:
    """Schedule one affected-peer reanalysis or stop for human review."""

    result, proposals_by_id, count = _validated_inputs(state)
    if result.consistent:
        return ConflictResolutionPlan(
            status=ConflictResolutionStatus.NOT_NEEDED,
            reason="No commitment contradiction requires reanalysis.",
        )
    if count >= 1:
        return ConflictResolutionPlan(
            status=ConflictResolutionStatus.UNRESOLVED_NEEDS_HUMAN,
            conflicts=result.conflicts,
            unresolved_conflict_ids=[
                item.conflict_id for item in result.conflicts
            ],
            reason=(
                "Commitment contradiction remains after one targeted reanalysis."
            ),
        )

    conflicts_by_specialist: dict[Domain, list[CommitmentConflict]] = {}
    for conflict in result.conflicts:
        affected = list(
            dict.fromkeys(
                proposals_by_id[proposal_id].specialist
                for proposal_id in conflict.proposal_ids
            )
        )
        for specialist in affected:
            conflicts_by_specialist.setdefault(specialist, []).append(conflict)
    specialists = list(conflicts_by_specialist)
    queries = {
        specialist.value: _query_for_specialist(
            state,
            specialist,
            conflicts_by_specialist[specialist],
        )
        for specialist in specialists
    }
    return ConflictResolutionPlan(
        status=ConflictResolutionStatus.REANALYSIS_REQUIRED,
        conflicts=result.conflicts,
        specialists=specialists,
        queries=queries,
        reason="One targeted reanalysis is required for affected peer specialists.",
    )


def conflict_resolution_node(state: GraphState) -> GraphState:
    plan = plan_conflict_resolution(state)
    conflict_ids = [item.conflict_id for item in plan.conflicts]
    update: GraphState = {
        "conflicts": [item.model_dump(mode="json") for item in plan.conflicts],
        "conflict_resolution": plan.model_dump(mode="json"),
        "conflict_reanalysis_needed": (
            plan.status is ConflictResolutionStatus.REANALYSIS_REQUIRED
        ),
        "conflict_specialists": [item.value for item in plan.specialists],
        "conflict_reanalysis_queries": {
            key: query.model_dump(mode="json") for key, query in plan.queries.items()
        },
        "conflict_unresolved": (
            plan.status is ConflictResolutionStatus.UNRESOLVED_NEEDS_HUMAN
        ),
        "unresolved_conflict_ids": list(plan.unresolved_conflict_ids),
        "target_conflict_ids": (
            conflict_ids
            if plan.status is ConflictResolutionStatus.REANALYSIS_REQUIRED
            else []
        ),
    }
    if plan.status is ConflictResolutionStatus.UNRESOLVED_NEEDS_HUMAN:
        update.update(
            strategy_state_update(
                immediate_hitl(
                    "Commitment contradiction remains after targeted reanalysis; "
                    "human review is required."
                )
            )
        )
        update["final_status"] = RequirementStatus.NEEDS_HUMAN.value
        update["final_answer"] = None
    return update


def conflict_reanalysis_attempt_node(state: GraphState) -> GraphState:
    """Execute the one allowed conflict-reanalysis round and snapshot its inputs."""

    if state.get("strategy") != "TARGETED_CONFLICT_RESOLUTION":
        raise ConflictResolutionError(
            "conflict attempt requires TARGETED_CONFLICT_RESOLUTION strategy"
        )
    count = state.get("conflict_reanalysis_count", 0)
    if not isinstance(count, int) or isinstance(count, bool) or count != 0:
        raise ConflictResolutionError("only one conflict reanalysis is allowed")
    specialists = [Domain(value) for value in state.get("selected_specialists", [])]
    conflict_ids = [str(value) for value in state.get("target_conflict_ids", [])]
    raw_queries = state.get("conflict_reanalysis_queries", {})
    queries = {
        specialist.value: str(
            raw_queries.get(specialist.value, {}).get("reanalysis_query", "")
        )
        for specialist in specialists
    }
    attempt = ConflictReanalysisAttempt(
        attempt_number=1,
        specialists=specialists,
        conflict_ids=conflict_ids,
        queries=queries,
    )
    return {
        "conflict_reanalysis_count": 1,
        "conflict_resolution_attempts": [
            *state.get("conflict_resolution_attempts", []),
            attempt.model_dump(mode="json"),
        ],
    }
