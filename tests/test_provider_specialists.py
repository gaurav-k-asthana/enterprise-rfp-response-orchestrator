from __future__ import annotations

import json
from threading import Lock
from types import SimpleNamespace

import pytest
from langgraph.graph import END

from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import SPECIALIST_NODES
from rfp_orchestrator.models import Domain, Requirement, SupportStatus
from rfp_orchestrator.openai_generation import OpenAIStructuredGenerationGateway
from rfp_orchestrator.provider_specialists import (
    SPECIALIST_SYSTEM_PROMPTS,
    ProviderSpecialistAnswer,
    ProviderSpecialistReasoningSession,
    build_provider_specialist_functions,
)
from rfp_orchestrator.retrieval import (
    EvidenceChunk,
    HybridScoreComponents,
    OfflineSpecialistRetrievers,
    RetrievalMethod,
)
from rfp_orchestrator.specialists import SpecialistBoundaryError
from rfp_orchestrator.state import new_requirement_state


class RoutedFakeResponses:
    """Return a domain-correct strict answer by reading only the supplied input."""

    def __init__(self, *, unsupported_domains: set[Domain] | None = None) -> None:
        self.unsupported_domains = unsupported_domains or set()
        self.calls: list[dict[str, object]] = []
        self._lock = Lock()

    def create(self, **kwargs: object) -> SimpleNamespace:
        payload = json.loads(str(kwargs["input"]))
        domain = Domain(payload["specialist"])
        evidence = payload["evidence"]
        supported = domain not in self.unsupported_domains and bool(evidence)
        evidence_ids = [evidence[0]["chunk_id"]] if supported else []
        claim_text = (
            evidence[0]["text"]
            if supported
            else f"Available {domain.value} evidence establishes the requirement."
        )
        output = {
            "claims": [
                {
                    "claim_id": "provider-generated-id",
                    "text": claim_text,
                    "evidence_ids": evidence_ids,
                    "supported": supported,
                }
            ],
            "proposed_answer": (
                claim_text
                if supported
                else f"Available {domain.value} evidence does not establish the requirement."
            ),
            "support_status": "SUPPORTED" if supported else "UNSUPPORTED",
        }
        with self._lock:
            self.calls.append(kwargs)
            number = len(self.calls)
        return SimpleNamespace(
            id=f"resp_specialist_{number}",
            status="completed",
            model="gpt-5.6-terra-2026-08-01",
            output_text=json.dumps(output),
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=25,
                total_tokens=125,
            ),
        )


class FakeOpenAI:
    def __init__(self, responses: RoutedFakeResponses) -> None:
        self.responses = responses


class FakeRetriever:
    def __init__(self, domain: Domain) -> None:
        self.domain = domain
        self.queries: list[tuple[str, int]] = []

    def search(self, query: str, *, k: int = 5, filters=None) -> list[EvidenceChunk]:
        self.queries.append((query, k))
        return [evidence(self.domain)]


def evidence(domain: Domain) -> EvidenceChunk:
    method = (
        RetrievalMethod.HYBRID
        if domain in {Domain.PRODUCT, Domain.SECURITY}
        else RetrievalMethod.DENSE
    )
    text = {
        Domain.PRODUCT: "Customer-managed encryption keys are available for AWS Enterprise Cloud.",
        Domain.SECURITY: "Security controls support customer-managed keys for AWS Enterprise Cloud.",
        Domain.IMPLEMENTATION: "A typical implementation lasts six to eight weeks after prerequisites.",
    }[domain]
    return EvidenceChunk(
        chunk_id=f"{domain.value}-evidence-001",
        doc_id=f"{domain.value}-doc-001",
        domain=domain,
        title=f"{domain.value.title()} evidence",
        text=text,
        version="1.0",
        effective_date="2026-01-01",
        authority_rank=5,
        source_status="current",
        score=0.9,
        retrieval_method=method,
        score_components=(
            HybridScoreComponents(
                lexical_weight=0.6,
                semantic_weight=0.4,
                provider_combined_score=0.9,
                visibility="combined_only",
            )
            if method is RetrievalMethod.HYBRID
            else None
        ),
    )


def bundle() -> tuple[OfflineSpecialistRetrievers, dict[Domain, FakeRetriever]]:
    retrievers = {domain: FakeRetriever(domain) for domain in Domain}
    return (
        OfflineSpecialistRetrievers(
            product=retrievers[Domain.PRODUCT],
            security=retrievers[Domain.SECURITY],
            implementation=retrievers[Domain.IMPLEMENTATION],
        ),
        retrievers,
    )


def session(
    responses: RoutedFakeResponses | None = None,
) -> tuple[ProviderSpecialistReasoningSession, RoutedFakeResponses]:
    fake = responses or RoutedFakeResponses()
    reasoning = ProviderSpecialistReasoningSession(
        OpenAIStructuredGenerationGateway(
            api_key="test-key",
            enabled=True,
            client_factory=lambda api_key: FakeOpenAI(fake),
        )
    )
    return reasoning, fake


def selected_requirement(domain: Domain) -> Requirement:
    return Requirement(
        requirement_id="RFP-TEST",
        original_text=f"Describe the {domain.value} requirement.",
        atomic_requirements=[f"Describe the {domain.value} requirement."],
        assigned_domains=[domain],
    )


@pytest.mark.parametrize("domain", list(Domain))
def test_each_provider_adapter_preserves_domain_method_and_top_five(domain: Domain) -> None:
    reasoning, responses = session()
    retriever = FakeRetriever(domain)
    function = build_provider_specialist_functions(reasoning)[domain]

    result = function(selected_requirement(domain), retriever)

    assert result.output.specialist is domain
    assert result.output.support_status is SupportStatus.SUPPORTED
    assert result.output.claims[0].claim_id == f"{domain.value}-claim-001"
    assert result.output.claims[0].evidence_ids == [f"{domain.value}-evidence-001"]
    assert retriever.queries == [(f"Describe the {domain.value} requirement.", 5)]
    assert result.evidence[0].retrieval_method.value == (
        "dense" if domain is Domain.IMPLEMENTATION else "hybrid"
    )
    call_input = json.loads(str(responses.calls[0]["input"]))
    assert call_input["specialist"] == domain.value
    assert call_input["retrieval_policy"] == result.evidence[0].retrieval_method.value
    assert responses.calls[0]["instructions"] == SPECIALIST_SYSTEM_PROMPTS[domain]


def test_safe_generation_receipt_excludes_prompts_evidence_text_and_secrets() -> None:
    reasoning, _ = session()
    retriever = FakeRetriever(Domain.PRODUCT)

    build_provider_specialist_functions(reasoning)[Domain.PRODUCT](
        selected_requirement(Domain.PRODUCT), retriever
    )
    receipt = reasoning.operations[0]
    payload = receipt.model_dump(mode="json")
    rendered = json.dumps(payload).lower()

    assert receipt.provider_calls == 1
    assert receipt.input_tokens == 100
    assert receipt.output_tokens == 25
    assert receipt.total_tokens == 125
    assert "instructions" not in payload
    assert "evidence_text" not in payload
    assert "api_key" not in rendered
    assert "gold" not in rendered


def test_provider_peer_graph_keeps_parallel_branches_and_downstream_gates() -> None:
    retriever_bundle, retrievers = bundle()
    reasoning, responses = session()
    graph = build_selected_fanout_graph(
        retriever_bundle,
        specialist_functions=build_provider_specialist_functions(reasoning),
        event_clock=lambda: "fixed",
    )

    state = graph.invoke(
        new_requirement_state(
            "EVAL-002",
            "RFP-002",
            (
                "Describe customer-managed encryption keys and identify supported "
                "deployment environments."
            ),
        )
    )

    assert state["initial_specialists"] == ["product", "security"]
    assert set(state["specialist_outputs"]) == {"product", "security"}
    assert state["merge_order"] == ["product", "security"]
    assert state["citation_valid"] is True
    assert state["source_metadata_valid"] is True
    assert state["claim_support_valid"] is True
    assert state["commitment_consistent"] is True
    assert state["finalization_passed"] is True
    assert state["final_status"] == "FINALIZED"
    assert len(responses.calls) == 2
    assert len(reasoning.operations) == 2
    assert len(retrievers[Domain.PRODUCT].queries) == 1
    assert len(retrievers[Domain.SECURITY].queries) == 1
    assert retrievers[Domain.IMPLEMENTATION].queries == []

    compiled_edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}
    assert not {
        (source.value, target.value)
        for source in SPECIALIST_NODES
        for target in SPECIALIST_NODES
        if (source.value, target.value) in compiled_edges
    }


def test_provider_graph_uses_saved_recovery_queries_and_stops_after_two_retries() -> None:
    retriever_bundle, retrievers = bundle()
    reasoning, responses = session(RoutedFakeResponses(unsupported_domains={Domain.SECURITY}))
    graph = build_selected_fanout_graph(
        retriever_bundle,
        specialist_functions=build_provider_specialist_functions(reasoning),
        event_clock=lambda: "fixed",
    )

    state = graph.invoke(
        new_requirement_state(
            "EVAL-021",
            "RFP-021",
            "Confirm that Northstar is authorized for FedRAMP High.",
        )
    )

    assert state["retry_count"] == 2
    assert state["recovery_exhausted"] is True
    assert state["final_status"] == "NEEDS_HUMAN"
    assert len(responses.calls) == 3
    assert len(reasoning.operations) == 3
    queries = [query for query, k in retrievers[Domain.SECURITY].queries]
    assert len(queries) == 3
    assert queries[1:] == [attempt["queries"]["security"] for attempt in state["recovery_attempts"]]
    assert all("Evidence focus:" in query for query in queries[1:])


def test_immediate_hitl_never_invokes_a_provider_specialist() -> None:
    retriever_bundle, retrievers = bundle()
    reasoning, responses = session()
    graph = build_selected_fanout_graph(
        retriever_bundle,
        specialist_functions=build_provider_specialist_functions(reasoning),
        event_clock=lambda: "fixed",
    )

    state = graph.invoke(
        new_requirement_state(
            "EVAL-023",
            "RFP-023",
            "Accept a 20% subscription discount and unlimited indemnity.",
        )
    )

    assert state["final_status"] == "NEEDS_HUMAN"
    assert responses.calls == []
    assert reasoning.operations == ()
    assert all(retriever.queries == [] for retriever in retrievers.values())


def test_closed_reasoning_session_stops_before_retrieval_or_generation() -> None:
    reasoning, responses = session()
    retriever = FakeRetriever(Domain.PRODUCT)
    reasoning.close()

    with pytest.raises(RuntimeError, match="session is closed"):
        build_provider_specialist_functions(reasoning)[Domain.PRODUCT](
            selected_requirement(Domain.PRODUCT), retriever
        )

    assert retriever.queries == []
    assert responses.calls == []


def test_adapter_rejects_cross_domain_retriever_before_provider_generation() -> None:
    reasoning, responses = session()

    with pytest.raises(SpecialistBoundaryError, match="security retriever"):
        build_provider_specialist_functions(reasoning)[Domain.PRODUCT](
            selected_requirement(Domain.PRODUCT),
            FakeRetriever(Domain.SECURITY),
        )

    assert responses.calls == []


def test_provider_specialist_schema_is_strict_and_fully_required() -> None:
    schema = ProviderSpecialistAnswer.model_json_schema()
    object_definitions = [
        definition
        for definition in schema.get("$defs", {}).values()
        if definition.get("type") == "object"
    ]

    for definition in [schema, *object_definitions]:
        assert definition["additionalProperties"] is False
        assert set(definition["required"]) == set(definition["properties"])


def test_graph_builder_requires_exactly_three_provider_functions() -> None:
    retriever_bundle, _ = bundle()
    reasoning, _ = session()
    functions = dict(build_provider_specialist_functions(reasoning))
    functions.pop(Domain.IMPLEMENTATION)

    with pytest.raises(ValueError, match="all three domains"):
        build_selected_fanout_graph(
            retriever_bundle,
            specialist_functions=functions,
        )


def test_peer_edges_still_fan_in_to_merge_not_each_other() -> None:
    retriever_bundle, _ = bundle()
    reasoning, _ = session()
    graph = build_selected_fanout_graph(
        retriever_bundle,
        specialist_functions=build_provider_specialist_functions(reasoning),
    ).get_graph()
    edges = {(edge.source, edge.target) for edge in graph.edges}

    for source in SPECIALIST_NODES:
        assert (source.value, "merge") in edges
        for target in SPECIALIST_NODES:
            assert (source.value, target.value) not in edges
    assert any(edge.target == END for edge in graph.edges)
