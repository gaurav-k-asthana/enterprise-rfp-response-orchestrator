"""Provider-backed single-generalist executor for the fair comparison."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from time import perf_counter
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.comparison_safety import (
    PostEvidenceSafetyFacts,
    assess_comparison_preflight,
    assess_generalist_risk_authority,
)
from rfp_orchestrator.evaluation_runner import (
    EvaluationCaseInput,
    EvaluationModelUsage,
    EvaluationRunRecord,
    RetrievalCallRecord,
)
from rfp_orchestrator.fair_comparison import ComparisonArchitecture
from rfp_orchestrator.generalist_baseline import (
    GENERALIST_SYSTEM_PROMPT,
    GeneralistBaselineResult,
    GeneralistDraft,
    GeneralistReasoningRequest,
    GeneralistToolCall,
    GeneralistToolName,
    GeneralistToolSession,
    SingleGeneralistBaseline,
)
from rfp_orchestrator.models import (
    Claim,
    Requirement,
    RequirementStatus,
    RiskClass,
    SupportStatus,
    aggregate_support,
)
from rfp_orchestrator.openai_generation import (
    OpenAIStructuredGenerationGateway,
    ProviderTokenUsage,
    StructuredGenerationRequest,
)
from rfp_orchestrator.provider_config import OPENAI_GENERATION_MODEL
from rfp_orchestrator.provider_retrieval import (
    METHOD_BY_DOMAIN,
    ProviderRetrievalSession,
)
from rfp_orchestrator.requirement_classification import analyze_requirement_input
from rfp_orchestrator.retrieval import EvidenceChunk
from rfp_orchestrator.source_validation import validate_source_metadata


class ProviderGeneralistToolIntent(BaseModel):
    """One provider-selected call to an existing domain-locked retrieval tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: GeneralistToolName
    query: str = Field(min_length=1)
    requested_k: Literal[5]

    @model_validator(mode="after")
    def query_is_not_whitespace(self) -> ProviderGeneralistToolIntent:
        if not self.query.strip():
            raise ValueError("provider retrieval query cannot be blank")
        return self


class ProviderGeneralistRetrievalPlan(BaseModel):
    """Strict first-call output: at most one call to each available tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    calls: list[ProviderGeneralistToolIntent] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def tools_do_not_repeat(self) -> ProviderGeneralistRetrievalPlan:
        names = [call.tool_name for call in self.calls]
        if len(names) != len(set(names)):
            raise ValueError("provider generalist cannot repeat a retrieval tool")
        return self


class ProviderGeneralistClaim(BaseModel):
    """Strict provider-facing version of the shared atomic Claim contract."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    evidence_ids: list[str]
    supported: bool

    @model_validator(mode="after")
    def support_and_citations_agree(self) -> ProviderGeneralistClaim:
        if not self.claim_id.strip() or not self.text.strip():
            raise ValueError("provider claim fields cannot be blank")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("provider claim citations cannot repeat")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("provider claim citations cannot be blank")
        if self.supported != bool(self.evidence_ids):
            raise ValueError("supported claims require citations and unsupported claims forbid them")
        return self

    def to_claim(self) -> Claim:
        return Claim.model_validate(self.model_dump())


class ProviderGeneralistAnswer(BaseModel):
    """Strict second-call output converted into the approved baseline draft."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    claims: list[ProviderGeneralistClaim] = Field(min_length=1)
    proposed_answer: str = Field(min_length=1)
    support_status: SupportStatus

    @model_validator(mode="after")
    def answer_is_internally_consistent(self) -> ProviderGeneralistAnswer:
        if not self.proposed_answer.strip():
            raise ValueError("provider generalist answer cannot be blank")
        claims = [claim.to_claim() for claim in self.claims]
        if self.support_status is not aggregate_support(claims):
            raise ValueError("provider support status must aggregate from claim Booleans")
        return self

    def to_draft(self) -> GeneralistDraft:
        claims = [claim.to_claim() for claim in self.claims]
        return GeneralistDraft(
            claims=claims,
            proposed_answer=self.proposed_answer,
            support_status=self.support_status,
        )


class ProviderGeneralistReasoner:
    """Use one provider identity to choose tools and then synthesize one answer."""

    def __init__(
        self,
        gateway: OpenAIStructuredGenerationGateway,
        *,
        case_id: str,
    ) -> None:
        self._gateway = gateway
        self._case_id = case_id
        self._usage: list[ProviderTokenUsage] = []

    @property
    def usage(self) -> tuple[ProviderTokenUsage, ...]:
        return tuple(self._usage)

    def respond(
        self,
        request: GeneralistReasoningRequest,
        tools: GeneralistToolSession,
    ) -> GeneralistDraft:
        plan_result = self._gateway.generate(
            StructuredGenerationRequest(
                request_id=f"{self._case_id}-generalist-plan",
                schema_name="rfp_generalist_retrieval_plan",
                instructions=GENERALIST_SYSTEM_PROMPT,
                input_text=_render_plan_input(request),
            ),
            output_model=ProviderGeneralistRetrievalPlan,
        )
        self._usage.append(plan_result.usage)
        for intent in plan_result.output.calls:
            tools.call(
                intent.tool_name,
                intent.query,
                k=intent.requested_k,
            )

        answer_result = self._gateway.generate(
            StructuredGenerationRequest(
                request_id=f"{self._case_id}-generalist-answer",
                schema_name="rfp_generalist_answer",
                instructions=GENERALIST_SYSTEM_PROMPT,
                input_text=_render_answer_input(request, tools.calls),
            ),
            output_model=ProviderGeneralistAnswer,
        )
        self._usage.append(answer_result.usage)
        return answer_result.output.to_draft()


class ProviderRetrievalSessionFactory(Protocol):
    def __call__(self) -> ProviderRetrievalSession: ...


class ProviderSingleGeneralistExecutor:
    """Produce one normalized provider record without exposing evaluation gold."""

    architecture = ComparisonArchitecture.SINGLE_GENERALIST

    def __init__(
        self,
        *,
        generation_gateway: OpenAIStructuredGenerationGateway,
        retrieval_session_factory: ProviderRetrievalSessionFactory,
        as_of: date,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        self._generation_gateway = generation_gateway
        self._retrieval_session_factory = retrieval_session_factory
        self._as_of = as_of
        self._timer = timer

    def execute(self, case: EvaluationCaseInput) -> EvaluationRunRecord:
        started = self._timer()
        requirement = analyze_requirement_input(
            Requirement(
                requirement_id=case.requirement_id,
                original_text=case.untrusted_rfp_text,
            )
        )
        preflight = assess_comparison_preflight(self.architecture, requirement)
        if preflight.requires_human:
            return _preflight_record(
                case,
                requirement,
                risk_classes=preflight.risk_classes,
                latency_ms=self._elapsed_ms(started),
            )

        provider_session = self._retrieval_session_factory()
        reasoner = ProviderGeneralistReasoner(
            self._generation_gateway,
            case_id=case.case_id,
        )
        baseline = SingleGeneralistBaseline(
            provider_session.domain_retrievers,
            reasoner=reasoner,
        )
        try:
            result = baseline.run(requirement)
        finally:
            provider_session.close()

        evidence = _unique_evidence(result.tool_calls)
        cited_ids = list(
            dict.fromkeys(
                evidence_id
                for claim in result.claims
                for evidence_id in claim.evidence_ids
            )
        )
        source_validation = validate_source_metadata(
            {
                "citation_valid": True,
                "citation_validation": {"cited_evidence_ids": cited_ids},
                "evidence": [item.model_dump(mode="json") for item in evidence],
            },
            as_of=self._as_of,
        )
        safety_facts = PostEvidenceSafetyFacts(
            citation_valid=True,
            source_metadata_valid=source_validation.valid,
            claim_support_valid=True,
            commitment_consistent=True,
        )
        assessment = assess_generalist_risk_authority(
            requirement,
            result,
            safety_facts,
        )
        awaiting = assessment.requires_human
        return EvaluationRunRecord(
            case_id=case.case_id,
            requirement_id=case.requirement_id,
            architecture=self.architecture,
            atomic_requirements=requirement.atomic_requirements,
            consulted_domains=list(dict.fromkeys(call.domain for call in result.tool_calls)),
            retrieval_calls=_normalized_retrieval_calls(case, result),
            evidence=evidence,
            claims=result.claims,
            proposed_answer=result.proposed_answer,
            support_status=result.support_status,
            citation_valid=True,
            source_metadata_valid=source_validation.valid,
            conflicts=[],
            retry_count=0,
            risk_classes=assessment.risk_classes,
            authority_required=assessment.requires_human,
            awaiting_human_review=awaiting,
            final_status=(
                RequirementStatus.NEEDS_HUMAN
                if awaiting
                else RequirementStatus.FINALIZED
            ),
            final_answer=None if awaiting else result.proposed_answer,
            errors=[],
            model_usage=_model_usage(reasoner.usage),
            latency_ms=self._elapsed_ms(started),
        )

    def _elapsed_ms(self, started: float) -> float:
        return max(0.0, (self._timer() - started) * 1_000)


def _render_plan_input(request: GeneralistReasoningRequest) -> str:
    payload = {
        "requirement_id": request.requirement_id,
        "untrusted_rfp_text": request.untrusted_rfp_text,
        "atomic_requirements": request.atomic_requirements,
        "available_tools": [tool.model_dump(mode="json") for tool in request.available_tools],
        "task": "Select the minimum relevant evidence tools. Return retrieval calls only.",
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _render_answer_input(
    request: GeneralistReasoningRequest,
    calls: tuple[GeneralistToolCall, ...],
) -> str:
    payload = {
        "requirement_id": request.requirement_id,
        "untrusted_rfp_text": request.untrusted_rfp_text,
        "atomic_requirements": request.atomic_requirements,
        "retrieval_calls": [call.model_dump(mode="json") for call in calls],
        "task": "Answer using only the evidence returned by these recorded calls.",
    }
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _unique_evidence(calls: list[GeneralistToolCall]) -> list[EvidenceChunk]:
    evidence_by_id: dict[str, EvidenceChunk] = {}
    for call in calls:
        for item in call.evidence:
            evidence_by_id.setdefault(item.chunk_id, item)
    return list(evidence_by_id.values())


def _normalized_retrieval_calls(
    case: EvaluationCaseInput,
    result: GeneralistBaselineResult,
) -> list[RetrievalCallRecord]:
    return [
        RetrievalCallRecord(
            call_id=f"{case.case_id}:generalist:{index}",
            tool_name=call.tool_name.value,
            domain=call.domain,
            query=call.query,
            requested_k=call.requested_k,
            retrieval_methods=[METHOD_BY_DOMAIN[call.domain].value],
            result_ids=[item.chunk_id for item in call.evidence],
        )
        for index, call in enumerate(result.tool_calls, start=1)
    ]


def _model_usage(usages: tuple[ProviderTokenUsage, ...]) -> EvaluationModelUsage:
    return EvaluationModelUsage(
        provider="openai",
        model=OPENAI_GENERATION_MODEL,
        provider_calls=len(usages),
        input_tokens=sum(item.input_tokens for item in usages),
        output_tokens=sum(item.output_tokens for item in usages),
        total_tokens=sum(item.total_tokens for item in usages),
        estimated_cost_usd=None,
    )


def _preflight_record(
    case: EvaluationCaseInput,
    requirement: Requirement,
    *,
    risk_classes: list[RiskClass],
    latency_ms: float,
) -> EvaluationRunRecord:
    return EvaluationRunRecord(
        case_id=case.case_id,
        requirement_id=case.requirement_id,
        architecture=ComparisonArchitecture.SINGLE_GENERALIST,
        atomic_requirements=requirement.atomic_requirements,
        consulted_domains=[],
        retrieval_calls=[],
        evidence=[],
        claims=[],
        proposed_answer=None,
        support_status=SupportStatus.UNSUPPORTED,
        citation_valid=None,
        source_metadata_valid=None,
        conflicts=[],
        retry_count=0,
        risk_classes=risk_classes,
        authority_required=True,
        awaiting_human_review=True,
        final_status=RequirementStatus.NEEDS_HUMAN,
        final_answer=None,
        errors=[],
        model_usage=EvaluationModelUsage(
            provider="openai",
            model=OPENAI_GENERATION_MODEL,
            provider_calls=0,
            input_tokens=0,
            output_tokens=0,
            total_tokens=0,
            estimated_cost_usd=0.0,
        ),
        latency_ms=latency_ms,
    )
