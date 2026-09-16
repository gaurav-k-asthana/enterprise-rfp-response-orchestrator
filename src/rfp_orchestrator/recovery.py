"""Structured evidence-failure context and query reformulation for Step 2.14."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from rfp_orchestrator.models import Domain, RequirementStatus
from rfp_orchestrator.state import GraphState
from rfp_orchestrator.strategy import immediate_hitl, strategy_state_update


class EvidenceFailureType(str, Enum):
    EMPTY_RETRIEVAL = "EMPTY_RETRIEVAL"
    MISSING_DIRECT_EVIDENCE = "MISSING_DIRECT_EVIDENCE"
    WEAK_EVIDENCE = "WEAK_EVIDENCE"
    INELIGIBLE_EVIDENCE = "INELIGIBLE_EVIDENCE"
    TOOL_EXCEPTION = "TOOL_EXCEPTION"
    INVALID_STRUCTURED_OUTPUT = "INVALID_STRUCTURED_OUTPUT"


class EvidenceFailureContext(BaseModel):
    failure_id: str = Field(min_length=1)
    failure_type: EvidenceFailureType
    specialist: Domain
    claim_ids: list[str] = Field(default_factory=list)
    failed_claim_texts: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    retry_count: int = Field(ge=0, le=2)
    recoverable: bool
    reason: str = Field(min_length=1)
    exception_type: str | None = None

    @model_validator(mode="after")
    def context_is_consistent(self) -> EvidenceFailureContext:
        for values, label in (
            (self.claim_ids, "claim_ids"),
            (self.failed_claim_texts, "failed_claim_texts"),
            (self.evidence_ids, "evidence_ids"),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"{label} cannot contain duplicates")
            if any(not value.strip() for value in values):
                raise ValueError(f"{label} cannot contain blank values")
        if self.failure_type is EvidenceFailureType.TOOL_EXCEPTION:
            if not self.exception_type or not self.exception_type.strip():
                raise ValueError("tool exception context requires exception_type")
        elif self.exception_type is not None:
            raise ValueError("exception_type is valid only for TOOL_EXCEPTION")
        return self


class ReformulatedQuery(BaseModel):
    specialist: Domain
    original_query: str = Field(min_length=1)
    reformulated_query: str = Field(min_length=1, max_length=800)
    failure_types: list[EvidenceFailureType] = Field(min_length=1)

    @model_validator(mode="after")
    def query_is_meaningfully_changed(self) -> ReformulatedQuery:
        if not self.original_query.strip() or not self.reformulated_query.strip():
            raise ValueError("recovery queries cannot be blank")
        if " ".join(self.original_query.casefold().split()) == " ".join(
            self.reformulated_query.casefold().split()
        ):
            raise ValueError("reformulated query must differ from the original")
        if len(self.failure_types) != len(set(self.failure_types)):
            raise ValueError("failure_types cannot contain duplicates")
        return self


class EvidenceRecoveryPlan(BaseModel):
    recovery_needed: bool
    failure_contexts: list[EvidenceFailureContext] = Field(default_factory=list)
    recovery_specialists: list[Domain] = Field(default_factory=list)
    reformulated_queries: dict[str, ReformulatedQuery] = Field(default_factory=dict)
    recovery_context: str | None = None

    @model_validator(mode="after")
    def plan_is_consistent(self) -> EvidenceRecoveryPlan:
        recoverable = [item for item in self.failure_contexts if item.recoverable]
        if self.recovery_needed != bool(recoverable):
            raise ValueError("recovery_needed must match recoverable failure contexts")
        expected_specialists = list(
            dict.fromkeys(item.specialist for item in recoverable)
        )
        if self.recovery_specialists != expected_specialists:
            raise ValueError("recovery specialists must match recoverable contexts")
        expected_keys = {specialist.value for specialist in expected_specialists}
        if set(self.reformulated_queries) != expected_keys:
            raise ValueError("every recovery specialist requires one reformulated query")
        if self.recovery_needed != bool(self.recovery_context):
            raise ValueError("recovery context is required exactly when recovery is needed")
        return self


class RecoveryPlanningError(ValueError):
    """Raised when a safe deterministic recovery plan cannot be constructed."""


class RecoveryAttempt(BaseModel):
    attempt_number: int = Field(ge=1, le=2)
    specialists: list[Domain] = Field(min_length=1)
    queries: dict[str, str] = Field(min_length=1)

    @model_validator(mode="after")
    def attempt_is_consistent(self) -> RecoveryAttempt:
        if len(self.specialists) != len(set(self.specialists)):
            raise ValueError("recovery attempt specialists cannot contain duplicates")
        expected_keys = {specialist.value for specialist in self.specialists}
        if set(self.queries) != expected_keys:
            raise ValueError("recovery attempt requires one query per specialist")
        if any(not query.strip() for query in self.queries.values()):
            raise ValueError("recovery attempt queries cannot be blank")
        return self


_DOMAIN_FOCUS = {
    Domain.PRODUCT: (
        "current product capability availability deployment tier integration "
        "GA roadmap unsupported limitations"
    ),
    Domain.SECURITY: (
        "current approved security compliance control certification authorization "
        "protocol scope limitations"
    ),
    Domain.IMPLEMENTATION: (
        "current implementation plan prerequisites timeline responsibilities "
        "dependencies scope limitations"
    ),
}

_FAILURE_FOCUS = {
    EvidenceFailureType.EMPTY_RETRIEVAL: "official direct documentary evidence",
    EvidenceFailureType.MISSING_DIRECT_EVIDENCE: (
        "explicit direct statement not adjacent or inferred evidence"
    ),
    EvidenceFailureType.WEAK_EVIDENCE: (
        "exact supported scope qualifiers exclusions and contradictory terms"
    ),
    EvidenceFailureType.INELIGIBLE_EVIDENCE: (
        "current effective approved replacement source"
    ),
    EvidenceFailureType.TOOL_EXCEPTION: "same evidence target with explicit terminology",
    EvidenceFailureType.INVALID_STRUCTURED_OUTPUT: "",
}

_STRUCTURED_OUTPUT_ISSUES = frozenset(
    {
        "MISSING_SPECIALIST_OUTPUT",
        "SPECIALIST_MISMATCH",
        "MISSING_ATOMIC_CLAIMS",
        "BLANK_CLAIM_ID",
        "DUPLICATE_CLAIM_ID",
        "BLANK_CLAIM_TEXT",
        "DUPLICATE_CLAIM_TEXT",
        "INVALID_PROVISIONAL_SUPPORT",
        "PROVISIONAL_SUPPORT_MISMATCH",
        "AGGREGATE_STATUS_MISMATCH",
    }
)


def _unique_nonblank(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def build_tool_failure_context(
    specialist: Domain,
    error: Exception,
    *,
    retry_count: int,
) -> EvidenceFailureContext:
    """Create retry context without retaining a potentially sensitive error message."""

    exception_type = type(error).__name__
    return EvidenceFailureContext(
        failure_id=f"{specialist.value}-tool-exception-retry-{retry_count}",
        failure_type=EvidenceFailureType.TOOL_EXCEPTION,
        specialist=specialist,
        retry_count=retry_count,
        recoverable=True,
        reason=f"{specialist.value} retrieval failed with {exception_type}.",
        exception_type=exception_type,
    )


def reformulate_search_query(
    original_query: str,
    failure_contexts: list[EvidenceFailureContext],
) -> ReformulatedQuery:
    """Create one deterministic specialist query from recorded recoverable failures."""

    original = " ".join(original_query.split())
    if not original:
        raise RecoveryPlanningError("original query cannot be blank")
    if not failure_contexts:
        raise RecoveryPlanningError("query reformulation requires failure context")
    if any(not item.recoverable for item in failure_contexts):
        raise RecoveryPlanningError("query reformulation accepts only recoverable failures")
    specialists = {item.specialist for item in failure_contexts}
    if len(specialists) != 1:
        raise RecoveryPlanningError("one reformulated query can target only one specialist")

    specialist = next(iter(specialists))
    claim_focus = _unique_nonblank(
        [text for item in failure_contexts for text in item.failed_claim_texts]
    )
    failure_types = list(
        dict.fromkeys(item.failure_type for item in failure_contexts)
    )
    failure_focus = _unique_nonblank(
        [_FAILURE_FOCUS[failure_type] for failure_type in failure_types]
    )
    additions = [*claim_focus, _DOMAIN_FOCUS[specialist], *failure_focus]
    reformulated = f"{original} Evidence focus: {'; '.join(additions)}"
    if len(reformulated) > 800:
        reformulated = reformulated[:800].rsplit(" ", 1)[0]

    return ReformulatedQuery(
        specialist=specialist,
        original_query=original,
        reformulated_query=reformulated,
        failure_types=failure_types,
    )


def _failure_context_for_claim(
    *,
    specialist: Domain,
    claim: dict,
    branch_evidence: list[dict],
    current_ids: set[str],
    retry_count: int,
) -> EvidenceFailureContext:
    claim_id = str(claim.get("claim_id", "")).strip()
    claim_text = str(claim.get("text", "")).strip()
    evidence_ids = _unique_nonblank(
        [str(value) for value in claim.get("evidence_ids", [])]
    )
    branch_ids = {
        str(item.get("chunk_id", "")) for item in branch_evidence
    }
    if not branch_evidence:
        failure_type = EvidenceFailureType.EMPTY_RETRIEVAL
        reason = "The specialist retrieval returned no evidence."
    elif evidence_ids and any(item not in current_ids for item in evidence_ids):
        failure_type = EvidenceFailureType.INELIGIBLE_EVIDENCE
        reason = "The claim cites evidence that is not eligible current support."
    elif not evidence_ids:
        failure_type = EvidenceFailureType.MISSING_DIRECT_EVIDENCE
        reason = "Retrieved evidence does not directly establish the atomic claim."
    else:
        failure_type = EvidenceFailureType.WEAK_EVIDENCE
        reason = "Cited current evidence does not sufficiently support the atomic claim."

    known_evidence_ids = [item for item in evidence_ids if item in branch_ids]
    return EvidenceFailureContext(
        failure_id=f"{specialist.value}-{failure_type.value.casefold()}-{claim_id}",
        failure_type=failure_type,
        specialist=specialist,
        claim_ids=[claim_id] if claim_id else [],
        failed_claim_texts=[claim_text] if claim_text else [],
        evidence_ids=known_evidence_ids,
        retry_count=retry_count,
        recoverable=True,
        reason=reason,
    )


def plan_evidence_recovery(state: GraphState) -> EvidenceRecoveryPlan:
    """Record evidence failures and prepare queries without executing a retry."""

    if state.get("prompt_injection_detected"):
        raise RecoveryPlanningError(
            "prompt-injection content cannot enter automatic query reformulation"
        )
    retry_count = state.get("retry_count", 0)
    if not isinstance(retry_count, int) or isinstance(retry_count, bool):
        raise RecoveryPlanningError("retry_count must be an integer")
    if not 0 <= retry_count <= 2:
        raise RecoveryPlanningError("retry_count must remain within the locked 0-2 range")

    assessments = {
        str(item.get("specialist", "")): item
        for item in (state.get("claim_support_validation") or {}).get(
            "assessments", []
        )
    }
    current_ids = set(
        (state.get("source_validation") or {}).get("current_evidence_ids", [])
    )
    failure_contexts: list[EvidenceFailureContext] = []
    for specialist_key in state.get("merge_order", []):
        specialist = Domain(specialist_key)
        branch_evidence = state.get("specialist_evidence", {}).get(
            specialist_key, []
        )
        assessment = assessments.get(specialist_key, {})
        for claim in assessment.get("claims", []):
            if claim.get("supported") is True:
                continue
            failure_contexts.append(
                _failure_context_for_claim(
                    specialist=specialist,
                    claim=claim,
                    branch_evidence=branch_evidence,
                    current_ids=current_ids,
                    retry_count=retry_count,
                )
            )

    existing_specialists = {
        (item.specialist, item.failure_type) for item in failure_contexts
    }
    for raw_issue in (state.get("claim_support_validation") or {}).get("issues", []):
        issue_type = str(raw_issue.get("issue_type", ""))
        specialist_key = raw_issue.get("specialist")
        if issue_type not in _STRUCTURED_OUTPUT_ISSUES or not specialist_key:
            continue
        specialist = Domain(str(specialist_key))
        marker = (specialist, EvidenceFailureType.INVALID_STRUCTURED_OUTPUT)
        if marker in existing_specialists:
            continue
        failure_contexts.append(
            EvidenceFailureContext(
                failure_id=f"{specialist.value}-invalid-structured-output",
                failure_type=EvidenceFailureType.INVALID_STRUCTURED_OUTPUT,
                specialist=specialist,
                claim_ids=_unique_nonblank([str(raw_issue.get("claim_id", ""))]),
                retry_count=retry_count,
                recoverable=False,
                reason="Specialist output is malformed or internally inconsistent.",
            )
        )
        existing_specialists.add(marker)

    for raw_failure in state.get("tool_failures", []):
        specialist = Domain(str(raw_failure["specialist"]))
        exception_type = str(raw_failure.get("exception_type", "ToolError"))
        failure_contexts.append(
            EvidenceFailureContext(
                failure_id=f"{specialist.value}-tool-exception-retry-{retry_count}",
                failure_type=EvidenceFailureType.TOOL_EXCEPTION,
                specialist=specialist,
                retry_count=retry_count,
                recoverable=True,
                reason=f"{specialist.value} retrieval failed with {exception_type}.",
                exception_type=exception_type,
            )
        )

    recoverable = [item for item in failure_contexts if item.recoverable]
    recovery_specialists = list(
        dict.fromkeys(item.specialist for item in recoverable)
    )
    base_query = " ".join(state.get("atomic_requirements", []))
    if not base_query:
        base_query = state.get("original_text", "")
    reformulated_queries = {
        specialist.value: reformulate_search_query(
            base_query,
            [item for item in recoverable if item.specialist is specialist],
        )
        for specialist in recovery_specialists
    }
    recovery_context = None
    if recoverable:
        labels = ", ".join(
            f"{item.specialist.value}:{item.failure_type.value}"
            for item in recoverable
        )
        recovery_context = (
            f"Retry {len(recovery_specialists)} affected specialist(s) from recorded "
            f"evidence failures: {labels}."
        )

    return EvidenceRecoveryPlan(
        recovery_needed=bool(recoverable),
        failure_contexts=failure_contexts,
        recovery_specialists=recovery_specialists,
        reformulated_queries=reformulated_queries,
        recovery_context=recovery_context,
    )


def evidence_recovery_planning_node(state: GraphState) -> GraphState:
    plan = plan_evidence_recovery(state)
    update: GraphState = {
        "recovery_needed": plan.recovery_needed,
        "evidence_failure_contexts": [
            item.model_dump(mode="json") for item in plan.failure_contexts
        ],
        "recovery_specialists": [
            specialist.value for specialist in plan.recovery_specialists
        ],
        "reformulated_queries": {
            key: query.model_dump(mode="json")
            for key, query in plan.reformulated_queries.items()
        },
        "recovery_context": plan.recovery_context,
    }
    if plan.recovery_needed and state.get("retry_count", 0) >= 2:
        update.update(
            strategy_state_update(
                immediate_hitl(
                    "The two-retry retrieval budget is exhausted; automated "
                    "recovery must stop."
                )
            )
        )
        update["recovery_exhausted"] = True
        update["final_status"] = RequirementStatus.NEEDS_HUMAN.value
        update["final_answer"] = None
    elif not plan.recovery_needed:
        update["recovery_exhausted"] = False
    return update


def recovery_attempt_node(state: GraphState) -> GraphState:
    """Count one executed attempt and snapshot the exact saved specialist queries."""

    if state.get("strategy") != "RETRIEVAL_RECOVERY":
        raise RecoveryPlanningError("recovery attempt requires RETRIEVAL_RECOVERY strategy")
    retry_count = state.get("retry_count", 0)
    if not isinstance(retry_count, int) or isinstance(retry_count, bool):
        raise RecoveryPlanningError("retry_count must be an integer")
    if not 0 <= retry_count < 2:
        raise RecoveryPlanningError("recovery attempt cannot exceed the two-retry limit")
    specialists = [Domain(value) for value in state.get("selected_specialists", [])]
    raw_queries = state.get("reformulated_queries", {})
    queries = {
        specialist.value: str(
            raw_queries.get(specialist.value, {}).get("reformulated_query", "")
        )
        for specialist in specialists
    }
    attempt = RecoveryAttempt(
        attempt_number=retry_count + 1,
        specialists=specialists,
        queries=queries,
    )
    return {
        "retry_count": attempt.attempt_number,
        "recovery_attempts": [
            *state.get("recovery_attempts", []),
            attempt.model_dump(mode="json"),
        ],
    }
