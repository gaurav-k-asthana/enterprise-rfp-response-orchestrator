"""Checkpoint-ready human-review request and LangGraph interrupt boundary."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from langgraph.config import get_stream_writer
from langgraph.types import interrupt
from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.execution_events import EventClock, utc_event_timestamp
from rfp_orchestrator.models import (
    ApprovalDecision,
    Domain,
    ExecutionEvent,
    ExecutionStatus,
    HumanApproval,
    RequirementStatus,
    RiskClass,
)
from rfp_orchestrator.state import GraphState


class HumanReviewError(ValueError):
    """Raised when a human-review checkpoint or interrupt is unsafe."""


class HumanReviewReason(str, Enum):
    PROMPT_INJECTION = "PROMPT_INJECTION"
    ORGANIZATIONAL_AUTHORITY = "ORGANIZATIONAL_AUTHORITY"
    RETRY_BUDGET_EXHAUSTED = "RETRY_BUDGET_EXHAUSTED"
    UNRESOLVED_CONFLICT = "UNRESOLVED_CONFLICT"
    NO_SAFE_ROUTE = "NO_SAFE_ROUTE"


class EvidenceCheckpointSummary(BaseModel):
    citation_valid: bool | None = None
    source_metadata_valid: bool | None = None
    claim_support_valid: bool | None = None
    commitment_consistent: bool | None = None


class HumanReviewRequest(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    requirement_id: str = Field(min_length=1)
    original_text: str = Field(min_length=1)
    reason: HumanReviewReason
    strategy: Literal["IMMEDIATE_HITL"] = "IMMEDIATE_HITL"
    status: Literal["NEEDS_HUMAN"] = "NEEDS_HUMAN"
    rationale: str = Field(min_length=1)
    risk_classes: list[RiskClass] = Field(default_factory=list)
    authority_owners: list[str] = Field(default_factory=list)
    unresolved_conflict_ids: list[str] = Field(default_factory=list)
    retry_count: int = Field(ge=0, le=2)
    evidence: EvidenceCheckpointSummary
    proposed_answers: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    allowed_decisions: list[ApprovalDecision]

    @model_validator(mode="after")
    def request_is_complete_and_unique(self) -> HumanReviewRequest:
        collection_fields = {
            "risk classes": self.risk_classes,
            "authority owners": self.authority_owners,
            "conflict IDs": self.unresolved_conflict_ids,
            "proposed answers": self.proposed_answers,
            "evidence IDs": self.evidence_ids,
            "allowed decisions": self.allowed_decisions,
        }
        if any(len(values) != len(set(values)) for values in collection_fields.values()):
            raise ValueError("human-review request collections cannot contain duplicates")
        if any(not value.strip() for value in self.authority_owners):
            raise ValueError("human-review authority owners cannot be blank")
        if any(not value.strip() for value in self.unresolved_conflict_ids):
            raise ValueError("human-review conflict IDs cannot be blank")
        if any(not value.strip() for value in self.proposed_answers):
            raise ValueError("human-review proposed answers cannot be blank")
        if any(not value.strip() for value in self.evidence_ids):
            raise ValueError("human-review evidence IDs cannot be blank")
        if self.allowed_decisions != list(ApprovalDecision):
            raise ValueError("human review must expose all five locked decisions")
        return self


class HumanReviewDecision(BaseModel):
    """Strict, auditable payload used to resume exactly one saved requirement."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    requirement_id: str = Field(min_length=1)
    decision: ApprovalDecision
    reviewer: str = Field(min_length=1)
    timestamp: str = Field(min_length=1)
    edited_answer: str | None = None
    guidance: str | None = None
    approved_proposal_ids: list[str] = Field(default_factory=list)
    target_specialists: list[Domain] = Field(default_factory=list)

    @model_validator(mode="after")
    def decision_payload_matches_action(self) -> HumanReviewDecision:
        text_fields = {
            "requirement_id": self.requirement_id,
            "reviewer": self.reviewer,
            "timestamp": self.timestamp,
        }
        if any(not value.strip() for value in text_fields.values()):
            raise ValueError("human-review identity and audit fields cannot be blank")
        optional_text = {
            "edited_answer": self.edited_answer,
            "guidance": self.guidance,
        }
        if any(value is not None and not value.strip() for value in optional_text.values()):
            raise ValueError("human-review optional text cannot be blank")
        if len(self.approved_proposal_ids) != len(set(self.approved_proposal_ids)):
            raise ValueError("approved proposal IDs cannot repeat")
        if any(not value.strip() for value in self.approved_proposal_ids):
            raise ValueError("approved proposal IDs cannot be blank")
        if len(self.target_specialists) != len(set(self.target_specialists)):
            raise ValueError("target specialists cannot repeat")

        if self.decision is ApprovalDecision.APPROVE:
            if self.edited_answer is not None or self.guidance is not None:
                raise ValueError("APPROVE cannot include edited_answer or guidance")
            if self.target_specialists:
                raise ValueError("APPROVE cannot select rework specialists")
        elif self.decision is ApprovalDecision.EDIT_AND_APPROVE:
            if self.edited_answer is None:
                raise ValueError("EDIT_AND_APPROVE requires edited_answer")
            if self.guidance is not None or self.target_specialists:
                raise ValueError("EDIT_AND_APPROVE accepts only edited answer content")
        elif self.decision is ApprovalDecision.REJECT:
            if any(
                (
                    self.edited_answer is not None,
                    self.guidance is not None,
                    bool(self.approved_proposal_ids),
                    bool(self.target_specialists),
                )
            ):
                raise ValueError("REJECT cannot approve, edit, guide, or retry work")
        elif self.decision is ApprovalDecision.ADD_GUIDANCE:
            if self.guidance is None:
                raise ValueError("ADD_GUIDANCE requires guidance")
            if self.edited_answer is not None or self.approved_proposal_ids:
                raise ValueError("ADD_GUIDANCE cannot approve an answer or proposal")
        elif self.decision is ApprovalDecision.REQUEST_RETRY:
            if self.edited_answer is not None or self.approved_proposal_ids:
                raise ValueError("REQUEST_RETRY cannot approve an answer or proposal")
        return self


class HumanReworkAttempt(BaseModel):
    attempt_number: int = Field(ge=1)
    decision: Literal[ApprovalDecision.ADD_GUIDANCE]
    specialists: list[Domain] = Field(min_length=1)
    queries: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def attempt_has_one_query_per_specialist(self) -> HumanReworkAttempt:
        if len(self.specialists) != len(set(self.specialists)):
            raise ValueError("human rework specialists cannot repeat")
        if set(self.queries) != {item.value for item in self.specialists}:
            raise ValueError("human rework requires one query per specialist")
        if any(not value.strip() for value in self.queries.values()):
            raise ValueError("human rework queries cannot be blank")
        return self


def _human_review_reason(state: GraphState) -> HumanReviewReason:
    if state.get("prompt_injection_detected"):
        return HumanReviewReason.PROMPT_INJECTION
    if state.get("recovery_exhausted"):
        return HumanReviewReason.RETRY_BUDGET_EXHAUSTED
    if state.get("conflict_unresolved"):
        return HumanReviewReason.UNRESOLVED_CONFLICT
    authority_risks = {
        RiskClass.PRICING_OR_DISCOUNT.value,
        RiskClass.WARRANTY_OR_INDEMNITY.value,
    }
    if state.get("authority_required") or authority_risks.intersection(
        state.get("initial_risk_flags", [])
    ):
        return HumanReviewReason.ORGANIZATIONAL_AUTHORITY
    return HumanReviewReason.NO_SAFE_ROUTE


def build_human_review_request(state: GraphState) -> HumanReviewRequest:
    """Build a compact review packet while full business state stays checkpointed."""

    if state.get("strategy") != "IMMEDIATE_HITL":
        raise HumanReviewError("human review requires IMMEDIATE_HITL strategy")
    requirement_id = str(state.get("requirement_id", "")).strip()
    original_text = str(state.get("original_text", "")).strip()
    rationale = str(state.get("strategy_rationale", "")).strip()
    if not requirement_id or not original_text or not rationale:
        raise HumanReviewError(
            "human review requires requirement text, ID, and routing rationale"
        )
    try:
        risk_classes = [RiskClass(value) for value in state.get("risk_classes", [])]
    except (TypeError, ValueError) as error:
        raise HumanReviewError("human review received an unknown risk class") from error

    proposed_answers = list(
        dict.fromkeys(
            str(item.get("proposed_answer", "")).strip()
            for item in state.get("merged_specialist_outputs", [])
            if str(item.get("proposed_answer", "")).strip()
        )
    )
    evidence_ids = list(
        dict.fromkeys(
            str(item.get("chunk_id", "")).strip()
            for item in state.get("evidence", [])
            if str(item.get("chunk_id", "")).strip()
        )
    )
    return HumanReviewRequest(
        requirement_id=requirement_id,
        original_text=original_text,
        reason=_human_review_reason(state),
        rationale=rationale,
        risk_classes=risk_classes,
        authority_owners=[str(value) for value in state.get("authority_owners", [])],
        unresolved_conflict_ids=[
            str(value) for value in state.get("unresolved_conflict_ids", [])
        ],
        retry_count=state.get("retry_count", 0),
        evidence=EvidenceCheckpointSummary(
            citation_valid=state.get("citation_valid"),
            source_metadata_valid=state.get("source_metadata_valid"),
            claim_support_valid=state.get("claim_support_valid"),
            commitment_consistent=state.get("commitment_consistent"),
        ),
        proposed_answers=proposed_answers,
        evidence_ids=evidence_ids,
        allowed_decisions=list(ApprovalDecision),
    )


def prepare_human_review_node(state: GraphState) -> GraphState:
    request = build_human_review_request(state)
    return {
        "human_review_request": request.model_dump(mode="json"),
        "awaiting_human_review": True,
        "human_resume_route": None,
        "human_rework_active": False,
        "final_status": RequirementStatus.NEEDS_HUMAN.value,
        "final_answer": None,
    }


def _available_rework_specialists(state: GraphState) -> list[Domain]:
    available: list[Domain] = []
    for field in (
        "initial_specialists",
        "recovery_specialists",
        "conflict_specialists",
        "assigned_domains",
    ):
        for raw_value in state.get(field, []):
            try:
                specialist = Domain(raw_value)
            except ValueError as error:
                raise HumanReviewError(
                    "checkpoint contains an unknown rework specialist"
                ) from error
            if specialist not in available:
                available.append(specialist)
    return available


def _selected_rework_specialists(
    state: GraphState,
    decision: HumanReviewDecision,
) -> list[Domain]:
    available = _available_rework_specialists(state)
    selected = decision.target_specialists or available
    if not selected:
        raise HumanReviewError(
            f"{decision.decision.value} requires at least one relevant specialist"
        )
    unavailable = [item.value for item in selected if item not in available]
    if unavailable:
        raise HumanReviewError(
            "resume payload selected a specialist outside the saved requirement scope"
        )
    return selected


def _validate_selected_proposals(
    state: GraphState,
    decision: HumanReviewDecision,
) -> list[str]:
    raw_proposals = state.get("proposed_commitments", [])
    if not isinstance(raw_proposals, list):
        raise HumanReviewError("checkpointed proposal state is malformed")
    proposal_ids: list[str] = []
    for proposal in raw_proposals:
        if not isinstance(proposal, dict):
            raise HumanReviewError("checkpointed proposal state is malformed")
        proposal_id = str(proposal.get("proposal_id", "")).strip()
        requirement_id = str(proposal.get("source_requirement_id", "")).strip()
        if not proposal_id or requirement_id != decision.requirement_id:
            raise HumanReviewError("checkpointed proposal provenance is invalid")
        proposal_ids.append(proposal_id)
    if len(proposal_ids) != len(set(proposal_ids)):
        raise HumanReviewError("checkpointed proposal IDs cannot repeat")
    unknown = [
        item for item in decision.approved_proposal_ids if item not in proposal_ids
    ]
    if unknown:
        raise HumanReviewError(
            "resume payload selected a proposal outside the saved requirement"
        )
    return list(decision.approved_proposal_ids)


def _reviewed_answer(
    request: HumanReviewRequest,
    decision: HumanReviewDecision,
) -> str:
    if decision.decision is ApprovalDecision.EDIT_AND_APPROVE:
        return decision.edited_answer or ""
    if not request.proposed_answers:
        raise HumanReviewError(
            "APPROVE requires a checkpointed proposed answer; use EDIT_AND_APPROVE "
            "to supply a safe reviewed answer"
        )
    return "\n\n".join(request.proposed_answers)


def _approval_record(decision: HumanReviewDecision) -> dict:
    return HumanApproval(
        requirement_id=decision.requirement_id,
        decision=decision.decision,
        reviewer=decision.reviewer,
        timestamp=decision.timestamp,
        edited_answer=decision.edited_answer,
        guidance=decision.guidance,
    ).model_dump(mode="json", exclude_none=True)


def _decision_history_record(
    request: HumanReviewRequest,
    decision: HumanReviewDecision,
) -> dict:
    record = decision.model_dump(mode="json", exclude_none=True)
    record["review_reason"] = request.reason.value
    return record


def _guided_queries(
    state: GraphState,
    decision: HumanReviewDecision,
    specialists: list[Domain],
) -> dict[str, dict]:
    guidance = decision.guidance or "Perform one fresh evidence pass requested by the reviewer."
    original = " ".join(state.get("atomic_requirements", [])) or str(
        state.get("original_text", "")
    )
    queries: dict[str, dict] = {}
    for specialist in specialists:
        revised = (
            f"{original} Human reviewer direction: {guidance} "
            f"Recheck only the {specialist.value} evidence scope."
        )
        queries[specialist.value] = {
            "specialist": specialist.value,
            "original_query": original,
            "reformulated_query": revised[:800],
            "rework_query": revised[:800],
            "failure_types": ["MISSING_DIRECT_EVIDENCE"],
        }
    return queries


def apply_human_review_decision(
    state: GraphState,
    raw_decision: object,
) -> GraphState:
    """Validate one resume payload and translate it into an explicit next route."""

    raw_request = state.get("human_review_request")
    if not isinstance(raw_request, dict):
        raise HumanReviewError("resume requires a checkpointed review request")
    try:
        request = HumanReviewRequest.model_validate(raw_request)
        decision = HumanReviewDecision.model_validate(raw_decision)
    except (TypeError, ValueError) as error:
        raise HumanReviewError("human-review resume payload is invalid") from error
    if decision.requirement_id != request.requirement_id:
        raise HumanReviewError(
            "resume decision requirement does not match the saved checkpoint"
        )
    if decision.decision not in request.allowed_decisions:
        raise HumanReviewError("resume decision is not allowed by this checkpoint")

    history = [
        *state.get("human_decision_history", []),
        _decision_history_record(request, decision),
    ]
    base: GraphState = {
        "approval": _approval_record(decision),
        "human_decision_history": history,
        "awaiting_human_review": False,
        "final_answer": None,
        "approved_proposal_ids": [],
    }

    if decision.decision in {
        ApprovalDecision.APPROVE,
        ApprovalDecision.EDIT_AND_APPROVE,
    }:
        base.update(
            {
                "approved_proposal_ids": _validate_selected_proposals(state, decision),
                "reviewed_answer": _reviewed_answer(request, decision),
                "human_resume_route": "finalization_guard",
                "strategy": "FINALIZE",
                "selected_specialists": [],
                "strategy_rationale": (
                    "A human accepted the reviewed candidate; the separate finalization "
                    "guard must still validate it."
                ),
                "final_status": RequirementStatus.PENDING.value,
            }
        )
        return base

    if decision.decision is ApprovalDecision.REJECT:
        base.update(
            {
                "human_resume_route": "end",
                "reviewed_answer": None,
                "selected_specialists": [],
                "final_status": RequirementStatus.REJECTED.value,
            }
        )
        return base

    specialists = _selected_rework_specialists(state, decision)
    queries = _guided_queries(state, decision, specialists)
    base.update(
        {
            "selected_specialists": [item.value for item in specialists],
            "reviewed_answer": None,
            "final_status": RequirementStatus.IN_PROGRESS.value,
        }
    )
    if decision.decision is ApprovalDecision.ADD_GUIDANCE:
        base.update(
            {
                "human_resume_route": "human_rework_attempt",
                "human_rework_active": True,
                "human_rework_queries": queries,
                "strategy": (
                    "SINGLE_SPECIALIST"
                    if len(specialists) == 1
                    else "PARALLEL_SPECIALISTS"
                ),
                "strategy_rationale": (
                    "A human supplied trusted guidance for the relevant peer specialists."
                ),
            }
        )
        return base

    retry_count = state.get("retry_count", 0)
    if not isinstance(retry_count, int) or isinstance(retry_count, bool):
        raise HumanReviewError("checkpointed retry count is invalid")
    if retry_count >= 2:
        raise HumanReviewError(
            "REQUEST_RETRY cannot exceed the locked two-retry retrieval budget"
        )
    base.update(
        {
            "human_resume_route": "recovery_attempt",
            "human_rework_active": False,
            "strategy": "RETRIEVAL_RECOVERY",
            "strategy_rationale": (
                "A human requested one bounded evidence-retrieval retry."
            ),
            "recovery_needed": True,
            "recovery_exhausted": False,
            "recovery_specialists": [item.value for item in specialists],
            "recovery_context": (
                "Human reviewer requested a bounded retry for: "
                + ", ".join(item.value for item in specialists)
                + "."
            ),
            "reformulated_queries": queries,
        }
    )
    return base


def human_rework_attempt_node(state: GraphState) -> GraphState:
    """Snapshot one guided rework pass before peer-specialist fan-out."""

    if state.get("human_rework_active") is not True:
        raise HumanReviewError("human rework attempt requires active guidance")
    specialists = [Domain(value) for value in state.get("selected_specialists", [])]
    raw_queries = state.get("human_rework_queries", {})
    attempt = HumanReworkAttempt(
        attempt_number=state.get("human_rework_count", 0) + 1,
        decision=ApprovalDecision.ADD_GUIDANCE,
        specialists=specialists,
        queries={
            specialist.value: str(
                raw_queries.get(specialist.value, {}).get("rework_query", "")
            )
            for specialist in specialists
        },
    )
    return {
        "human_rework_count": attempt.attempt_number,
        "human_rework_attempts": [
            *state.get("human_rework_attempts", []),
            attempt.model_dump(mode="json"),
        ],
    }


def human_review_interrupt_node(
    state: GraphState,
    *,
    clock: EventClock = utc_event_timestamp,
) -> GraphState:
    """Stream the pause boundary, then validate and apply one resume decision."""

    if state.get("awaiting_human_review") is not True:
        raise HumanReviewError("interrupt requires an awaiting human-review state")
    raw_request = state.get("human_review_request")
    if not isinstance(raw_request, dict):
        raise HumanReviewError("interrupt requires a checkpointed review request")
    try:
        request = HumanReviewRequest.model_validate(raw_request)
    except (TypeError, ValueError) as error:
        raise HumanReviewError("interrupt received a malformed review request") from error
    writer = get_stream_writer()
    waiting = ExecutionEvent(
        requirement_id=request.requirement_id,
        node="human_review_interrupt",
        status=ExecutionStatus.BLOCKED,
        timestamp=clock(),
        detail="human_review_interrupt is awaiting a human decision",
    ).model_dump(mode="json")
    writer(waiting)

    raw_decision = interrupt(request.model_dump(mode="json"))

    completed = ExecutionEvent(
        requirement_id=request.requirement_id,
        node="human_review_interrupt",
        status=ExecutionStatus.COMPLETE,
        timestamp=clock(),
        detail="human_review_interrupt applied a validated human decision",
    ).model_dump(mode="json")
    writer(completed)
    return {
        **apply_human_review_decision(state, raw_decision),
        "execution_events": [waiting, completed],
    }
