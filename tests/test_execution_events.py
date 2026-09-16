from itertools import count
from pathlib import Path

import pytest
from langgraph.graph import END, START, StateGraph

from rfp_orchestrator.execution_events import instrument_node
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.state import GraphState, new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


def sequence_clock():
    ticks = count(1)

    def clock() -> str:
        return f"2026-08-30T12:00:{next(ticks):02d}Z"

    return clock


def graph():
    return build_selected_fanout_graph(
        build_offline_retrievers(KB_DIRECTORY),
        event_clock=sequence_clock(),
    )


def invoke(requirement_id: str, text: str):
    return graph().invoke(new_requirement_state("case-1", requirement_id, text))


def event_pairs(events: list[dict]) -> list[tuple[str, str]]:
    return [(event["node"], event["status"]) for event in events]


def test_simple_path_records_start_and_completion_for_every_executed_node() -> None:
    result = invoke("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")

    assert event_pairs(result["execution_events"]) == [
        (GraphNode.REQUIREMENT_ANALYZER.value, "active"),
        (GraphNode.REQUIREMENT_ANALYZER.value, "complete"),
        (GraphNode.STRATEGY_ORCHESTRATOR.value, "active"),
        (GraphNode.STRATEGY_ORCHESTRATOR.value, "complete"),
        (GraphNode.PRODUCT_SPECIALIST.value, "active"),
        (GraphNode.PRODUCT_SPECIALIST.value, "complete"),
        (GraphNode.MERGE.value, "active"),
        (GraphNode.MERGE.value, "complete"),
        (GraphNode.CITATION_VALIDATION.value, "active"),
        (GraphNode.CITATION_VALIDATION.value, "complete"),
        (GraphNode.SOURCE_VALIDATION.value, "active"),
        (GraphNode.SOURCE_VALIDATION.value, "complete"),
        (GraphNode.CLAIM_SUPPORT_VALIDATION.value, "active"),
        (GraphNode.CLAIM_SUPPORT_VALIDATION.value, "complete"),
        (GraphNode.RECOVERY_PLANNING.value, "active"),
        (GraphNode.RECOVERY_PLANNING.value, "complete"),
        (GraphNode.COMMITMENT_LEDGER.value, "active"),
        (GraphNode.COMMITMENT_LEDGER.value, "complete"),
        (GraphNode.COMMITMENT_CONSISTENCY.value, "active"),
        (GraphNode.COMMITMENT_CONSISTENCY.value, "complete"),
        (GraphNode.CONFLICT_RESOLUTION.value, "active"),
        (GraphNode.CONFLICT_RESOLUTION.value, "complete"),
        (GraphNode.RISK_AUTHORITY.value, "active"),
        (GraphNode.RISK_AUTHORITY.value, "complete"),
        (GraphNode.FINALIZATION_GUARD.value, "active"),
        (GraphNode.FINALIZATION_GUARD.value, "complete"),
        (GraphNode.COMMITMENT_PROMOTION.value, "active"),
        (GraphNode.COMMITMENT_PROMOTION.value, "complete"),
    ]


def test_parallel_path_records_both_selected_peers_before_merge() -> None:
    result = invoke(
        "RFP-002",
        (
            "Describe customer-managed encryption keys and identify supported "
            "deployment environments."
        ),
    )
    events = result["execution_events"]
    pairs = event_pairs(events)

    for specialist in (
        GraphNode.PRODUCT_SPECIALIST.value,
        GraphNode.SECURITY_SPECIALIST.value,
    ):
        assert (specialist, "active") in pairs
        assert (specialist, "complete") in pairs
        assert pairs.index((specialist, "active")) < pairs.index(
            (specialist, "complete")
        )
    assert not any(
        event["node"] == GraphNode.IMPLEMENTATION_SPECIALIST.value for event in events
    )
    merge_start = pairs.index((GraphNode.MERGE.value, "active"))
    assert merge_start > pairs.index((GraphNode.PRODUCT_SPECIALIST.value, "complete"))
    assert merge_start > pairs.index((GraphNode.SECURITY_SPECIALIST.value, "complete"))


def test_terminal_path_records_only_analyzer_and_orchestrator() -> None:
    result = invoke(
        "RFP-023",
        "Accept a 20% subscription discount and unlimited indemnity.",
    )

    assert event_pairs(result["execution_events"]) == [
        (GraphNode.REQUIREMENT_ANALYZER.value, "active"),
        (GraphNode.REQUIREMENT_ANALYZER.value, "complete"),
        (GraphNode.STRATEGY_ORCHESTRATOR.value, "active"),
        (GraphNode.STRATEGY_ORCHESTRATOR.value, "complete"),
    ]


def test_events_have_stable_ui_contract_and_requirement_id() -> None:
    result = invoke("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")

    for event in result["execution_events"]:
        assert set(event) == {
            "requirement_id",
            "node",
            "status",
            "timestamp",
            "detail",
        }
        assert event["requirement_id"] == "RFP-001"
        assert event["timestamp"].startswith("2026-08-30T12:00:")
        assert event["detail"]


def test_custom_stream_emits_events_incrementally_in_state_order() -> None:
    compiled = graph()
    initial = new_requirement_state(
        "case-1",
        "RFP-001",
        "Confirm support for SAML 2.0 and SCIM 2.0.",
    )

    streamed = list(compiled.stream(initial, stream_mode="custom"))
    persisted = compiled.invoke(initial)["execution_events"]

    assert event_pairs(streamed) == event_pairs(persisted)
    assert streamed[0]["status"] == "active"
    assert streamed[-1]["node"] == GraphNode.COMMITMENT_PROMOTION.value
    assert streamed[-1]["status"] == "complete"


def test_existing_events_remain_at_the_front_of_append_only_state() -> None:
    initial = new_requirement_state(
        "case-1",
        "RFP-001",
        "Confirm support for SAML 2.0 and SCIM 2.0.",
    )
    prior = {
        "requirement_id": "RFP-001",
        "node": "prior_node",
        "status": "complete",
        "timestamp": "2026-08-30T11:59:59Z",
        "detail": "prior event",
    }
    initial["execution_events"] = [prior]

    result = graph().invoke(initial)

    assert result["execution_events"][0] == prior
    assert len(result["execution_events"]) == 29


def test_inactive_specialists_emit_no_events() -> None:
    result = invoke("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    nodes = {event["node"] for event in result["execution_events"]}

    assert GraphNode.PRODUCT_SPECIALIST.value in nodes
    assert GraphNode.SECURITY_SPECIALIST.value not in nodes
    assert GraphNode.IMPLEMENTATION_SPECIALIST.value not in nodes


def test_failure_streams_blocked_event_without_exposing_exception_message() -> None:
    def fail(_: GraphState) -> GraphState:
        raise RuntimeError("sensitive internal failure details")

    builder = StateGraph(GraphState)
    builder.add_node(
        "failing_node",
        instrument_node("failing_node", fail, clock=sequence_clock()),
    )
    builder.add_edge(START, "failing_node")
    builder.add_edge("failing_node", END)
    failing_graph = builder.compile()
    initial = new_requirement_state("case-1", "RFP-X", "Test failure.")
    streamed: list[dict] = []

    with pytest.raises(RuntimeError, match="sensitive internal failure details"):
        streamed.extend(failing_graph.stream(initial, stream_mode="custom"))

    assert event_pairs(streamed) == [
        ("failing_node", "active"),
        ("failing_node", "blocked"),
    ]
    assert streamed[-1]["detail"] == "failing_node failed: RuntimeError"
    assert "sensitive" not in streamed[-1]["detail"]


def test_each_successful_node_has_exactly_one_active_and_complete_event() -> None:
    result = invoke(
        "RFP-002",
        (
            "Describe customer-managed encryption keys and identify supported "
            "deployment environments."
        ),
    )
    events = result["execution_events"]

    for node in {
        GraphNode.REQUIREMENT_ANALYZER.value,
        GraphNode.STRATEGY_ORCHESTRATOR.value,
        GraphNode.PRODUCT_SPECIALIST.value,
        GraphNode.SECURITY_SPECIALIST.value,
        GraphNode.MERGE.value,
        GraphNode.CITATION_VALIDATION.value,
        GraphNode.SOURCE_VALIDATION.value,
        GraphNode.CLAIM_SUPPORT_VALIDATION.value,
        GraphNode.RECOVERY_PLANNING.value,
        GraphNode.COMMITMENT_LEDGER.value,
        GraphNode.COMMITMENT_CONSISTENCY.value,
        GraphNode.CONFLICT_RESOLUTION.value,
        GraphNode.RISK_AUTHORITY.value,
        GraphNode.COMMITMENT_PROMOTION.value,
    }:
        node_statuses = [event["status"] for event in events if event["node"] == node]
        assert node_statuses == ["active", "complete"]
