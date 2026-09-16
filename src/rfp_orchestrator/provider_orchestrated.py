"""Normalized provider executor for the existing peer-specialist LangGraph."""

from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Protocol

from rfp_orchestrator.evaluation_runner import (
    EvaluationCaseInput,
    EvaluationModelUsage,
    EvaluationRunRecord,
    RetrievalCallRecord,
)
from rfp_orchestrator.fair_comparison import ComparisonArchitecture
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.models import (
    Domain,
    RequirementStatus,
    RiskClass,
    SpecialistOutput,
    aggregate_support,
)
from rfp_orchestrator.openai_generation import OpenAIStructuredGenerationGateway
from rfp_orchestrator.provider_config import OPENAI_GENERATION_MODEL
from rfp_orchestrator.provider_retrieval import (
    METHOD_BY_DOMAIN,
    ProviderRetrievalSession,
)
from rfp_orchestrator.provider_specialists import (
    ProviderSpecialistReasoningSession,
    build_provider_specialist_functions,
)
from rfp_orchestrator.retrieval import EvidenceChunk
from rfp_orchestrator.state import new_requirement_state


class ProviderRetrievalSessionFactory(Protocol):
    def __call__(self) -> ProviderRetrievalSession: ...


class ProviderOrchestratedExecutor:
    """Run provider peers and normalize their existing graph state."""

    architecture = ComparisonArchitecture.ORCHESTRATED_PEERS

    def __init__(
        self,
        *,
        generation_gateway: OpenAIStructuredGenerationGateway,
        retrieval_session_factory: ProviderRetrievalSessionFactory,
        timer: Callable[[], float] = perf_counter,
        event_clock: Callable[[], str] = lambda: "provider-evaluation",
    ) -> None:
        self._generation_gateway = generation_gateway
        self._retrieval_session_factory = retrieval_session_factory
        self._timer = timer
        self._event_clock = event_clock

    def execute(self, case: EvaluationCaseInput) -> EvaluationRunRecord:
        started = self._timer()
        retrieval_session = self._retrieval_session_factory()
        reasoning_session = ProviderSpecialistReasoningSession(
            self._generation_gateway
        )
        graph = build_selected_fanout_graph(
            retrieval_session.specialist_retrievers,
            specialist_functions=build_provider_specialist_functions(
                reasoning_session
            ),
            event_clock=self._event_clock,
        )
        try:
            state = dict(
                graph.invoke(
                    new_requirement_state(
                        case.case_id,
                        case.requirement_id,
                        case.untrusted_rfp_text,
                    )
                )
            )
        finally:
            reasoning_session.close()
            retrieval_session.close()

        outputs = [
            SpecialistOutput.model_validate(item)
            for item in state.get("merged_specialist_outputs", [])
        ]
        evidence = _unique_evidence(
            [EvidenceChunk.model_validate(item) for item in state.get("evidence", [])]
        )
        claims = [claim for output in outputs for claim in output.claims]
        retrieval_calls = _retrieval_calls(case, state, retrieval_session)
        final_status = (
            RequirementStatus(state["final_status"])
            if state.get("final_status")
            else None
        )
        awaiting_human_review = bool(
            state.get("awaiting_human_review", False)
            or final_status is RequirementStatus.NEEDS_HUMAN
        )
        proposed_answer = " ".join(
            output.proposed_answer.strip()
            for output in outputs
            if output.proposed_answer.strip()
        ) or None
        operations = reasoning_session.operations
        return EvaluationRunRecord(
            case_id=case.case_id,
            requirement_id=case.requirement_id,
            architecture=self.architecture,
            atomic_requirements=list(state.get("atomic_requirements", [])),
            consulted_domains=[call.domain for call in retrieval_calls],
            retrieval_calls=retrieval_calls,
            evidence=evidence,
            claims=claims,
            proposed_answer=proposed_answer,
            support_status=aggregate_support(claims),
            citation_valid=state.get("citation_valid"),
            source_metadata_valid=state.get("source_metadata_valid"),
            conflicts=list(
                (state.get("commitment_consistency") or {}).get("conflicts", [])
            ),
            retry_count=int(state.get("retry_count", 0)),
            risk_classes=[
                RiskClass(value) for value in state.get("risk_classes", [])
            ],
            authority_required=bool(state.get("authority_required", False)),
            awaiting_human_review=awaiting_human_review,
            final_status=final_status,
            # The normalized evaluation contract never exposes a draft as final
            # while the graph is paused at the human-review boundary.
            final_answer=None if awaiting_human_review else state.get("final_answer"),
            errors=[],
            model_usage=EvaluationModelUsage(
                provider="openai",
                model=OPENAI_GENERATION_MODEL,
                provider_calls=len(operations),
                input_tokens=sum(item.input_tokens for item in operations),
                output_tokens=sum(item.output_tokens for item in operations),
                total_tokens=sum(item.total_tokens for item in operations),
                estimated_cost_usd=None,
            ),
            latency_ms=max(0.0, (self._timer() - started) * 1_000),
        )


def _unique_evidence(items: list[EvidenceChunk]) -> list[EvidenceChunk]:
    by_id: dict[str, EvidenceChunk] = {}
    for item in items:
        by_id.setdefault(item.chunk_id, item)
    return list(by_id.values())


def _retrieval_calls(
    case: EvaluationCaseInput,
    state: dict,
    session: ProviderRetrievalSession,
) -> list[RetrievalCallRecord]:
    branch_evidence = state.get("specialist_evidence", {})
    calls: list[RetrievalCallRecord] = []
    for index, domain_value in enumerate(state.get("merge_order", []), start=1):
        domain = Domain(domain_value)
        items = [
            EvidenceChunk.model_validate(item)
            for item in branch_evidence.get(domain_value, [])
        ]
        matching_operations = [
            operation for operation in session.operations if operation.domain is domain
        ]
        query = (
            matching_operations[-1].query
            if matching_operations
            else case.untrusted_rfp_text
        )
        calls.append(
            RetrievalCallRecord(
                call_id=f"{case.case_id}:orchestrated:{index}",
                tool_name=f"search_{domain.value}_evidence",
                domain=domain,
                query=query,
                requested_k=5,
                retrieval_methods=[METHOD_BY_DOMAIN[domain].value],
                result_ids=[item.chunk_id for item in items],
            )
        )
    return calls
