from enum import Enum

from pydantic import BaseModel, Field, model_validator


class Domain(str, Enum):
    PRODUCT = "product"
    SECURITY = "security"
    IMPLEMENTATION = "implementation"


class SupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIAL = "PARTIAL"
    UNSUPPORTED = "UNSUPPORTED"


class RequirementStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    NEEDS_HUMAN = "NEEDS_HUMAN"
    FINALIZED = "FINALIZED"
    REJECTED = "REJECTED"


class StrategyType(str, Enum):
    SINGLE_SPECIALIST = "SINGLE_SPECIALIST"
    PARALLEL_SPECIALISTS = "PARALLEL_SPECIALISTS"
    RETRIEVAL_RECOVERY = "RETRIEVAL_RECOVERY"
    TARGETED_CONFLICT_RESOLUTION = "TARGETED_CONFLICT_RESOLUTION"
    IMMEDIATE_HITL = "IMMEDIATE_HITL"
    FINALIZE = "FINALIZE"


class RiskClass(str, Enum):
    UNSUPPORTED_CATEGORICAL_YES = "UNSUPPORTED_CATEGORICAL_YES"
    ROADMAP_COMMITMENT = "ROADMAP_COMMITMENT"
    PRICING_OR_DISCOUNT = "PRICING_OR_DISCOUNT"
    SLA_OR_SERVICE_CREDIT = "SLA_OR_SERVICE_CREDIT"
    WARRANTY_OR_INDEMNITY = "WARRANTY_OR_INDEMNITY"
    SECURITY_EXCEPTION = "SECURITY_EXCEPTION"
    DATA_RESIDENCY_AMBIGUITY = "DATA_RESIDENCY_AMBIGUITY"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    SPECIALIST_DISAGREEMENT = "SPECIALIST_DISAGREEMENT"
    RETRY_BUDGET_EXHAUSTED = "RETRY_BUDGET_EXHAUSTED"


class CommitmentType(str, Enum):
    DATA_RESIDENCY = "DATA_RESIDENCY"
    RETENTION_PERIOD = "RETENTION_PERIOD"
    UPTIME_SLA = "UPTIME_SLA"
    DEPLOYMENT_MODEL = "DEPLOYMENT_MODEL"
    SUPPORTED_INTEGRATION = "SUPPORTED_INTEGRATION"
    PRODUCT_AVAILABILITY = "PRODUCT_AVAILABILITY"
    ROADMAP_COMMITMENT = "ROADMAP_COMMITMENT"


class ApprovalDecision(str, Enum):
    APPROVE = "APPROVE"
    EDIT_AND_APPROVE = "EDIT_AND_APPROVE"
    REJECT = "REJECT"
    ADD_GUIDANCE = "ADD_GUIDANCE"
    REQUEST_RETRY = "REQUEST_RETRY"


class ExecutionStatus(str, Enum):
    INACTIVE = "inactive"
    ACTIVE = "active"
    COMPLETE = "complete"
    RECOVERY = "recovery"
    BLOCKED = "blocked"
    STATE_ACCESS = "state_access"


class InjectionSignalType(str, Enum):
    ROLE_MARKER = "ROLE_MARKER"
    POLICY_OVERRIDE = "POLICY_OVERRIDE"
    FORCED_RESPONSE = "FORCED_RESPONSE"
    ROLE_REASSIGNMENT = "ROLE_REASSIGNMENT"
    SENSITIVE_DISCLOSURE = "SENSITIVE_DISCLOSURE"


class RequirementAttribute(str, Enum):
    INFORMATION_REQUEST = "INFORMATION_REQUEST"
    CONFIRMATION_REQUEST = "CONFIRMATION_REQUEST"
    COMMITMENT_REQUEST = "COMMITMENT_REQUEST"
    COMPARISON_REQUEST = "COMPARISON_REQUEST"
    DELIVERABLE_REQUEST = "DELIVERABLE_REQUEST"
    ABSOLUTE_LANGUAGE = "ABSOLUTE_LANGUAGE"
    TIME_BOUND_REQUEST = "TIME_BOUND_REQUEST"
    UNTRUSTED_INSTRUCTION = "UNTRUSTED_INSTRUCTION"


class AmbiguitySignalType(str, Enum):
    RELATIVE_TIMEFRAME = "RELATIVE_TIMEFRAME"
    UNDEFINED_TIMEFRAME = "UNDEFINED_TIMEFRAME"
    UNBOUNDED_SCOPE = "UNBOUNDED_SCOPE"
    ABSOLUTE_LANGUAGE = "ABSOLUTE_LANGUAGE"


class AmbiguitySignal(BaseModel):
    signal_type: AmbiguitySignalType
    matched_text: str = Field(min_length=1)
    start_index: int = Field(ge=0)
    end_index: int = Field(gt=0)
    reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def span_is_valid(self) -> "AmbiguitySignal":
        if self.end_index <= self.start_index:
            raise ValueError("ambiguity signal end must follow its start")
        return self


class PromptInjectionSignal(BaseModel):
    signal_type: InjectionSignalType
    matched_text: str = Field(min_length=1)
    start_index: int = Field(ge=0)
    end_index: int = Field(gt=0)

    @model_validator(mode="after")
    def span_is_valid(self) -> "PromptInjectionSignal":
        if self.end_index <= self.start_index:
            raise ValueError("prompt-injection signal end must follow its start")
        return self


class Requirement(BaseModel):
    requirement_id: str
    original_text: str
    atomic_requirements: list[str] = Field(default_factory=list)
    assigned_domains: list[Domain] = Field(default_factory=list)
    attributes: list[RequirementAttribute] = Field(default_factory=list)
    ambiguity_signals: list[AmbiguitySignal] = Field(default_factory=list)
    initial_risk_flags: list[RiskClass] = Field(default_factory=list)
    status: RequirementStatus = RequirementStatus.PENDING
    prompt_injection_detected: bool = False
    prompt_injection_signals: list[PromptInjectionSignal] = Field(default_factory=list)

    @model_validator(mode="after")
    def injection_flag_matches_signals(self) -> "Requirement":
        if self.prompt_injection_detected != bool(self.prompt_injection_signals):
            raise ValueError("prompt_injection_detected must match the presence of signals")
        for signal in self.prompt_injection_signals:
            if self.original_text[signal.start_index : signal.end_index] != signal.matched_text:
                raise ValueError("prompt-injection signal span must match original_text")
        return self

    @model_validator(mode="after")
    def classification_is_consistent(self) -> "Requirement":
        if len(self.assigned_domains) != len(set(self.assigned_domains)):
            raise ValueError("assigned_domains cannot contain duplicates")
        if len(self.attributes) != len(set(self.attributes)):
            raise ValueError("attributes cannot contain duplicates")
        if len(self.initial_risk_flags) != len(set(self.initial_risk_flags)):
            raise ValueError("initial_risk_flags cannot contain duplicates")
        for signal in self.ambiguity_signals:
            if self.original_text[signal.start_index : signal.end_index] != signal.matched_text:
                raise ValueError("ambiguity signal span must match original_text")
        return self


class StrategyDecision(BaseModel):
    """A validated route description; choosing the route belongs to Step 2.5."""

    strategy: StrategyType
    selected_specialists: list[Domain] = Field(default_factory=list)
    rationale: str = Field(min_length=1)
    recovery_context: str | None = None
    target_conflict_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def route_payload_is_consistent(self) -> "StrategyDecision":
        if not self.rationale.strip():
            raise ValueError("strategy rationale cannot be blank")
        if len(self.selected_specialists) != len(set(self.selected_specialists)):
            raise ValueError("selected_specialists cannot contain duplicates")
        if len(self.target_conflict_ids) != len(set(self.target_conflict_ids)):
            raise ValueError("target_conflict_ids cannot contain duplicates")
        if any(not conflict_id.strip() for conflict_id in self.target_conflict_ids):
            raise ValueError("target_conflict_ids cannot contain blank values")

        specialist_count = len(self.selected_specialists)
        if self.strategy is StrategyType.SINGLE_SPECIALIST and specialist_count != 1:
            raise ValueError("SINGLE_SPECIALIST requires exactly one specialist")
        if self.strategy is StrategyType.PARALLEL_SPECIALISTS and not 2 <= specialist_count <= 3:
            raise ValueError("PARALLEL_SPECIALISTS requires two or three specialists")
        if self.strategy is StrategyType.RETRIEVAL_RECOVERY:
            if specialist_count < 1:
                raise ValueError("RETRIEVAL_RECOVERY requires at least one specialist")
            if not self.recovery_context or not self.recovery_context.strip():
                raise ValueError("RETRIEVAL_RECOVERY requires recovery_context")
        if self.strategy is StrategyType.TARGETED_CONFLICT_RESOLUTION:
            if specialist_count < 1:
                raise ValueError(
                    "TARGETED_CONFLICT_RESOLUTION requires at least one specialist"
                )
            if not self.target_conflict_ids:
                raise ValueError(
                    "TARGETED_CONFLICT_RESOLUTION requires target_conflict_ids"
                )

        terminal_routes = {StrategyType.IMMEDIATE_HITL, StrategyType.FINALIZE}
        if self.strategy in terminal_routes and specialist_count:
            raise ValueError(f"{self.strategy.value} cannot select specialists")

        if self.strategy is not StrategyType.RETRIEVAL_RECOVERY and self.recovery_context:
            raise ValueError("recovery_context is valid only for RETRIEVAL_RECOVERY")
        if (
            self.strategy is not StrategyType.TARGETED_CONFLICT_RESOLUTION
            and self.target_conflict_ids
        ):
            raise ValueError(
                "target_conflict_ids are valid only for TARGETED_CONFLICT_RESOLUTION"
            )
        return self


class StrategySelectionContext(BaseModel):
    """The explicit signals available to the deterministic Step 2.5 orchestrator."""

    requirement: Requirement
    retry_count: int = Field(default=0, ge=0, le=2)
    recovery_specialists: list[Domain] = Field(default_factory=list)
    recovery_context: str | None = None
    conflict_specialists: list[Domain] = Field(default_factory=list)
    conflict_ids: list[str] = Field(default_factory=list)
    finalization_ready: bool = False
    human_approval_present: bool = False

    @model_validator(mode="after")
    def selection_signals_are_consistent(self) -> "StrategySelectionContext":
        if len(self.recovery_specialists) != len(set(self.recovery_specialists)):
            raise ValueError("recovery_specialists cannot contain duplicates")
        if len(self.conflict_specialists) != len(set(self.conflict_specialists)):
            raise ValueError("conflict_specialists cannot contain duplicates")
        if len(self.conflict_ids) != len(set(self.conflict_ids)):
            raise ValueError("conflict_ids cannot contain duplicates")
        if any(not conflict_id.strip() for conflict_id in self.conflict_ids):
            raise ValueError("conflict_ids cannot contain blank values")

        has_recovery_context = bool(
            self.recovery_context and self.recovery_context.strip()
        )
        if bool(self.recovery_specialists) != has_recovery_context:
            raise ValueError(
                "recovery_specialists and nonblank recovery_context must appear together"
            )
        if bool(self.conflict_specialists) != bool(self.conflict_ids):
            raise ValueError("conflict_specialists and conflict_ids must appear together")
        if self.finalization_ready and (
            self.recovery_specialists or self.conflict_specialists
        ):
            raise ValueError(
                "finalization_ready cannot coexist with recovery or conflict work"
            )
        return self


class Claim(BaseModel):
    """An atomic material claim with binary evidence support."""

    claim_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    supported: bool


def aggregate_support(claims: list[Claim]) -> SupportStatus:
    if not claims:
        return SupportStatus.UNSUPPORTED
    flags = [claim.supported for claim in claims]
    if all(flags):
        return SupportStatus.SUPPORTED
    if any(flags):
        return SupportStatus.PARTIAL
    return SupportStatus.UNSUPPORTED


class SpecialistOutput(BaseModel):
    specialist: Domain
    claims: list[Claim]
    proposed_answer: str
    support_status: SupportStatus

    @model_validator(mode="after")
    def support_status_matches_claims(self) -> "SpecialistOutput":
        expected = aggregate_support(self.claims)
        if self.support_status != expected:
            raise ValueError(f"support_status must aggregate to {expected.value}")
        return self


class ExecutionEvent(BaseModel):
    requirement_id: str
    node: str
    status: ExecutionStatus
    timestamp: str
    detail: str | None = None


class Commitment(BaseModel):
    commitment_type: CommitmentType
    normalized_value: str
    source_requirement_id: str
    evidence_ids: list[str] = Field(default_factory=list)
    approved: bool = False


class RiskAssessment(BaseModel):
    risk_classes: list[RiskClass] = Field(default_factory=list)
    requires_human: bool
    reasons: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def human_review_has_reason(self) -> "RiskAssessment":
        if self.requires_human and not self.reasons:
            raise ValueError("human review requires at least one reason")
        return self


class HumanApproval(BaseModel):
    requirement_id: str
    decision: ApprovalDecision
    reviewer: str
    timestamp: str
    edited_answer: str | None = None
    guidance: str | None = None

    @model_validator(mode="after")
    def decision_payload_is_present(self) -> "HumanApproval":
        if self.decision is ApprovalDecision.EDIT_AND_APPROVE and not self.edited_answer:
            raise ValueError("EDIT_AND_APPROVE requires edited_answer")
        if self.decision is ApprovalDecision.ADD_GUIDANCE and not self.guidance:
            raise ValueError("ADD_GUIDANCE requires guidance")
        return self
