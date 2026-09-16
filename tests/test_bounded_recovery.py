from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.models import Domain
from rfp_orchestrator.recovery import (
    RecoveryAttempt,
    RecoveryPlanningError,
    recovery_attempt_node,
)
from rfp_orchestrator.retrieval import (
    OfflineSpecialistRetrievers,
    SpecialistRetriever,
    build_offline_retrievers,
)
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


class RecordingRetriever:
    def __init__(
        self,
        wrapped: SpecialistRetriever,
        *,
        empty_calls: int = 0,
    ) -> None:
        self._wrapped = wrapped
        self._empty_calls = empty_calls
        self.queries: list[str] = []

    @property
    def domain(self) -> Domain:
        return self._wrapped.domain

    def search(self, query: str, *, k: int = 5):
        self.queries.append(query)
        if len(self.queries) <= self._empty_calls:
            return []
        return self._wrapped.search(query, k=k)


def recording_bundle(
    *,
    empty_product_calls: int = 0,
    empty_security_calls: int = 0,
    empty_implementation_calls: int = 0,
):
    offline = build_offline_retrievers(KB_DIRECTORY)
    product = RecordingRetriever(
        offline.product,
        empty_calls=empty_product_calls,
    )
    security = RecordingRetriever(
        offline.security,
        empty_calls=empty_security_calls,
    )
    implementation = RecordingRetriever(
        offline.implementation,
        empty_calls=empty_implementation_calls,
    )
    return (
        OfflineSpecialistRetrievers(
            product=product,
            security=security,
            implementation=implementation,
        ),
        {
            "product": product,
            "security": security,
            "implementation": implementation,
        },
    )


def invoke(requirement_id: str, text: str, retrievers):
    graph = build_selected_fanout_graph(retrievers, event_clock=lambda: "fixed")
    return graph.invoke(new_requirement_state("case-1", requirement_id, text))


def test_missing_fedramp_executes_exactly_two_security_retries_then_stops() -> None:
    bundle, recorders = recording_bundle()

    state = invoke(
        "RFP-021",
        "Confirm that Northstar is authorized for FedRAMP High.",
        bundle,
    )

    assert state["retry_count"] == 2
    assert state["recovery_exhausted"] is True
    assert state["strategy"] == "IMMEDIATE_HITL"
    assert state["selected_specialists"] == []
    assert [item["attempt_number"] for item in state["recovery_attempts"]] == [1, 2]
    assert len(recorders["security"].queries) == 3
    assert recorders["product"].queries == []
    assert recorders["implementation"].queries == []
    assert state["final_answer"] is None


def test_retries_use_the_exact_saved_reformulated_query() -> None:
    bundle, recorders = recording_bundle()

    state = invoke(
        "RFP-021",
        "Confirm that Northstar is authorized for FedRAMP High.",
        bundle,
    )

    retry_queries = recorders["security"].queries[1:]
    saved_queries = [
        attempt["queries"]["security"] for attempt in state["recovery_attempts"]
    ]
    assert retry_queries == saved_queries
    assert all("Evidence focus:" in query for query in retry_queries)
    assert recorders["security"].queries[0] != retry_queries[0]


def test_supported_path_executes_no_recovery_attempt() -> None:
    bundle, recorders = recording_bundle()

    state = invoke(
        "RFP-001",
        "Confirm support for SAML 2.0 and SCIM 2.0.",
        bundle,
    )

    assert state["retry_count"] == 0
    assert state["recovery_attempts"] == []
    assert state["recovery_exhausted"] is False
    assert len(recorders["product"].queries) == 1
    assert recorders["security"].queries == []


def test_security_only_retry_preserves_successful_product_branch() -> None:
    bundle, recorders = recording_bundle(empty_security_calls=1)

    state = invoke(
        "RFP-002",
        (
            "Describe customer-managed encryption keys and identify supported "
            "deployment environments."
        ),
        bundle,
    )

    assert state["retry_count"] == 1
    assert state["recovery_needed"] is False
    assert state["initial_specialists"] == ["product", "security"]
    assert state["selected_specialists"] == ["security"]
    assert len(recorders["product"].queries) == 1
    assert len(recorders["security"].queries) == 2
    assert recorders["implementation"].queries == []
    assert set(state["specialist_outputs"]) == {"product", "security"}
    assert set(state["merge_order"]) == {"product", "security"}
    assert state["claim_support_validation"]["support_status_by_specialist"] == {
        "product": "SUPPORTED",
        "security": "SUPPORTED",
    }


def test_parallel_retry_increments_counter_once_not_once_per_specialist() -> None:
    bundle, recorders = recording_bundle(
        empty_product_calls=1,
        empty_security_calls=1,
    )

    state = invoke(
        "RFP-002",
        (
            "Describe customer-managed encryption keys and identify supported "
            "deployment environments."
        ),
        bundle,
    )

    assert state["retry_count"] == 1
    assert len(state["recovery_attempts"]) == 1
    assert state["recovery_attempts"][0]["specialists"] == ["product", "security"]
    assert set(state["recovery_attempts"][0]["queries"]) == {
        "product",
        "security",
    }
    assert len(recorders["product"].queries) == 2
    assert len(recorders["security"].queries) == 2


def test_recovery_attempt_counter_transitions_from_zero_to_two() -> None:
    state = new_requirement_state("case-1", "RFP-X", "Confirm security control.")
    state.update(
        {
            "strategy": "RETRIEVAL_RECOVERY",
            "selected_specialists": ["security"],
            "reformulated_queries": {
                "security": {"reformulated_query": "Focused security query"}
            },
        }
    )

    first = recovery_attempt_node(state)
    state.update(first)
    second = recovery_attempt_node(state)
    state.update(second)

    assert state["retry_count"] == 2
    assert [item["attempt_number"] for item in state["recovery_attempts"]] == [1, 2]
    with pytest.raises(RecoveryPlanningError, match="two-retry"):
        recovery_attempt_node(state)


@pytest.mark.parametrize("retry_count", [-1, 3, True, "1"])
def test_recovery_attempt_rejects_invalid_or_excessive_counter(retry_count) -> None:
    state = new_requirement_state("case-1", "RFP-X", "Confirm security control.")
    state.update(
        {
            "strategy": "RETRIEVAL_RECOVERY",
            "selected_specialists": ["security"],
            "reformulated_queries": {
                "security": {"reformulated_query": "Focused security query"}
            },
            "retry_count": retry_count,
        }
    )

    with pytest.raises(RecoveryPlanningError):
        recovery_attempt_node(state)


def test_recovery_attempt_requires_saved_query_for_every_target() -> None:
    state = new_requirement_state("case-1", "RFP-X", "Confirm security control.")
    state.update(
        {
            "strategy": "RETRIEVAL_RECOVERY",
            "selected_specialists": ["security"],
            "reformulated_queries": {},
        }
    )

    with pytest.raises(ValidationError, match="queries cannot be blank"):
        recovery_attempt_node(state)


def test_non_recovery_strategy_cannot_execute_attempt_node() -> None:
    state = new_requirement_state("case-1", "RFP-X", "Confirm security control.")
    state["strategy"] = "SINGLE_SPECIALIST"

    with pytest.raises(RecoveryPlanningError, match="RETRIEVAL_RECOVERY"):
        recovery_attempt_node(state)


def test_attempt_model_rejects_number_above_two() -> None:
    with pytest.raises(ValidationError):
        RecoveryAttempt(
            attempt_number=3,
            specialists=[Domain.SECURITY],
            queries={"security": "Focused query"},
        )


def test_exhausted_trace_contains_two_attempt_pairs_and_three_security_pairs() -> None:
    bundle, _ = recording_bundle()
    state = invoke(
        "RFP-021",
        "Confirm that Northstar is authorized for FedRAMP High.",
        bundle,
    )
    pairs = [(item["node"], item["status"]) for item in state["execution_events"]]

    attempt_statuses = [
        status
        for node, status in pairs
        if node == GraphNode.RECOVERY_ATTEMPT.value
    ]
    security_statuses = [
        status
        for node, status in pairs
        if node == GraphNode.SECURITY_SPECIALIST.value
    ]
    assert attempt_statuses == ["recovery", "complete", "recovery", "complete"]
    assert security_statuses == [
        "active",
        "complete",
        "active",
        "complete",
        "active",
        "complete",
    ]


def test_retry_path_still_has_no_specialist_to_specialist_edge() -> None:
    bundle, _ = recording_bundle()
    graph = build_selected_fanout_graph(bundle)
    edges = {(edge.source, edge.target) for edge in graph.get_graph().edges}

    specialist_nodes = {
        GraphNode.PRODUCT_SPECIALIST.value,
        GraphNode.SECURITY_SPECIALIST.value,
        GraphNode.IMPLEMENTATION_SPECIALIST.value,
    }
    assert not {
        (source, target)
        for source, target in edges
        if source in specialist_nodes and target in specialist_nodes
    }
