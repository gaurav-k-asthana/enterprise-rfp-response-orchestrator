from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.node_status import (
    ARCHITECTURE_NODES,
    NodeStatusError,
    apply_node_event,
    initial_node_status,
    reduce_node_status,
)
from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.ui import SESSION_NODE_STATUS, run_sample_requirement

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"


def event(node: str, status: str, requirement_id: str = "RFP-001") -> dict:
    return {
        "requirement_id": requirement_id,
        "node": node,
        "status": status,
        "timestamp": "2026-08-30T18:00:00Z",
        "detail": f"{node} {status}",
    }


def test_initial_status_has_every_canonical_node_in_enum_order() -> None:
    status = initial_node_status()

    assert tuple(status) == ARCHITECTURE_NODES
    assert tuple(status) == tuple(node.value for node in GraphNode)
    assert len(status) == 21
    assert set(status.values()) == {"inactive"}
    assert initial_node_status() is not status


def test_real_single_specialist_trace_leaves_unselected_peers_inactive() -> None:
    state, _ = run_sample_requirement(load_sample_requirements()[0], 1)

    status = reduce_node_status(state["execution_events"])

    assert status["requirement_analyzer"] == "complete"
    assert status["strategy_orchestrator"] == "complete"
    assert status["product_specialist"] == "complete"
    assert status["security_specialist"] == "inactive"
    assert status["implementation_specialist"] == "inactive"
    assert status["merge"] == "complete"
    assert status["commitment_promotion"] == "complete"


def test_real_cross_domain_trace_marks_both_selected_peers_complete() -> None:
    state, _ = run_sample_requirement(load_sample_requirements()[1], 1)

    status = reduce_node_status(state["execution_events"])

    assert status["product_specialist"] == "complete"
    assert status["security_specialist"] == "complete"
    assert status["implementation_specialist"] == "inactive"


def test_incremental_recovery_status_is_visible_until_completion() -> None:
    status = initial_node_status()

    recovering = apply_node_event(
        status,
        event("recovery_attempt", "recovery"),
    )
    completed = apply_node_event(
        recovering,
        event("recovery_attempt", "complete"),
    )

    assert status["recovery_attempt"] == "inactive"
    assert recovering["recovery_attempt"] == "recovery"
    assert completed["recovery_attempt"] == "complete"


@pytest.mark.parametrize("status", ["active", "blocked", "state_access"])
def test_each_nonterminal_visual_status_is_preserved(status: str) -> None:
    reduced = reduce_node_status([event("human_review_checkpoint", status)])

    assert reduced["human_review_checkpoint"] == status


def test_reducer_is_last_event_wins_without_mutating_events() -> None:
    events = [
        event("requirement_analyzer", "active"),
        event("requirement_analyzer", "complete"),
    ]
    original = deepcopy(events)

    reduced = reduce_node_status(events)

    assert reduced["requirement_analyzer"] == "complete"
    assert events == original


@pytest.mark.parametrize(
    "events, message",
    [
        ([event("not_a_graph_node", "active")], "unknown architecture node"),
        ([event("requirement_analyzer", "not_a_status")], "malformed"),
        (
            [
                event("requirement_analyzer", "complete", "RFP-001"),
                event("strategy_orchestrator", "active", "RFP-002"),
            ],
            "different requirements",
        ),
    ],
)
def test_invalid_or_mixed_events_fail_closed(events: list[dict], message: str) -> None:
    with pytest.raises(NodeStatusError, match=message):
        reduce_node_status(events)


def test_ui_saves_node_status_and_clear_removes_it() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)
    app.sidebar.button[0].click().run(timeout=10)

    assert app.session_state[SESSION_NODE_STATUS]["product_specialist"] == "complete"
    assert app.session_state[SESSION_NODE_STATUS]["security_specialist"] == "inactive"

    app.sidebar.button[1].click().run(timeout=10)

    assert SESSION_NODE_STATUS not in app.session_state
