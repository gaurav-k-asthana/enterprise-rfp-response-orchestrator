from typing import Annotated, Literal, TypedDict


def merge_dicts(left: dict, right: dict) -> dict:
    return {**left, **right}


def append_events(left: list[dict], right: list[dict]) -> list[dict]:
    return [*left, *right]


class GraphState(TypedDict, total=False):
    case_id: str
    requirement_id: str
    original_text: str
    atomic_requirements: list[str]
    prompt_injection_detected: bool
    prompt_injection_signals: list[dict]
    assigned_domains: list[Literal["product", "security", "implementation"]]
    requirement_attributes: list[str]
    ambiguity_signals: list[dict]
    initial_risk_flags: list[str]
    strategy: Literal[
        "SINGLE_SPECIALIST",
        "PARALLEL_SPECIALISTS",
        "RETRIEVAL_RECOVERY",
        "TARGETED_CONFLICT_RESOLUTION",
        "IMMEDIATE_HITL",
        "FINALIZE",
    ] | None
    selected_specialists: list[Literal["product", "security", "implementation"]]
    initial_specialists: list[Literal["product", "security", "implementation"]]
    strategy_rationale: str | None
    recovery_context: str | None
    target_conflict_ids: list[str]
    specialist_outputs: Annotated[dict, merge_dicts]
    specialist_evidence: Annotated[dict, merge_dicts]
    merged_specialist_outputs: list[dict]
    merge_order: list[Literal["product", "security", "implementation"]]
    evidence: list[dict]
    citation_valid: bool | None
    citation_validation: dict | None
    source_metadata_valid: bool | None
    source_validation: dict | None
    claim_support_valid: bool | None
    claim_support_validation: dict | None
    recovery_needed: bool
    evidence_failure_contexts: list[dict]
    recovery_specialists: list[Literal["product", "security", "implementation"]]
    reformulated_queries: dict[str, dict]
    tool_failures: list[dict]
    retry_count: int
    recovery_attempts: list[dict]
    recovery_exhausted: bool
    conflicts: list[dict]
    conflict_resolution: dict | None
    conflict_reanalysis_needed: bool
    conflict_specialists: list[Literal["product", "security", "implementation"]]
    conflict_reanalysis_queries: dict[str, dict]
    conflict_reanalysis_count: int
    conflict_resolution_attempts: list[dict]
    conflict_unresolved: bool
    unresolved_conflict_ids: list[str]
    risk_classes: list[str]
    risk_assessment: dict | None
    authority_required: bool
    authority_owners: list[str]
    authority_gate_passed: bool | None
    human_review_request: dict | None
    awaiting_human_review: bool
    human_resume_route: str | None
    human_decision_history: list[dict]
    human_rework_active: bool
    human_rework_queries: dict[str, dict]
    human_rework_count: int
    human_rework_attempts: list[dict]
    reviewed_answer: str | None
    finalization_result: dict | None
    finalization_passed: bool | None
    proposed_commitments: list[dict]
    commitment_extraction: dict | None
    commitment_consistent: bool | None
    commitment_consistency: dict | None
    approved_proposal_ids: list[str]
    commitment_promotion: dict | None
    commitments: list[dict]
    approval: dict | None
    final_answer: str | None
    final_status: str | None
    execution_events: Annotated[list[dict], append_events]


def new_requirement_state(case_id: str, requirement_id: str, text: str) -> GraphState:
    return {
        "case_id": case_id,
        "requirement_id": requirement_id,
        "original_text": text,
        "atomic_requirements": [],
        "prompt_injection_detected": False,
        "prompt_injection_signals": [],
        "assigned_domains": [],
        "requirement_attributes": [],
        "ambiguity_signals": [],
        "initial_risk_flags": [],
        "strategy": None,
        "selected_specialists": [],
        "initial_specialists": [],
        "strategy_rationale": None,
        "recovery_context": None,
        "target_conflict_ids": [],
        "specialist_outputs": {},
        "specialist_evidence": {},
        "merged_specialist_outputs": [],
        "merge_order": [],
        "evidence": [],
        "citation_valid": None,
        "citation_validation": None,
        "source_metadata_valid": None,
        "source_validation": None,
        "claim_support_valid": None,
        "claim_support_validation": None,
        "recovery_needed": False,
        "evidence_failure_contexts": [],
        "recovery_specialists": [],
        "reformulated_queries": {},
        "tool_failures": [],
        "retry_count": 0,
        "recovery_attempts": [],
        "recovery_exhausted": False,
        "conflicts": [],
        "conflict_resolution": None,
        "conflict_reanalysis_needed": False,
        "conflict_specialists": [],
        "conflict_reanalysis_queries": {},
        "conflict_reanalysis_count": 0,
        "conflict_resolution_attempts": [],
        "conflict_unresolved": False,
        "unresolved_conflict_ids": [],
        "risk_classes": [],
        "risk_assessment": None,
        "authority_required": False,
        "authority_owners": [],
        "authority_gate_passed": None,
        "human_review_request": None,
        "awaiting_human_review": False,
        "human_resume_route": None,
        "human_decision_history": [],
        "human_rework_active": False,
        "human_rework_queries": {},
        "human_rework_count": 0,
        "human_rework_attempts": [],
        "reviewed_answer": None,
        "finalization_result": None,
        "finalization_passed": None,
        "proposed_commitments": [],
        "commitment_extraction": None,
        "commitment_consistent": None,
        "commitment_consistency": None,
        "approved_proposal_ids": [],
        "commitment_promotion": None,
        "commitments": [],
        "approval": None,
        "final_answer": None,
        "final_status": None,
        "execution_events": [],
    }
