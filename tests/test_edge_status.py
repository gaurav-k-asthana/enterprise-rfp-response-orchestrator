import pytest

from rfp_orchestrator.edge_status import (
    EDGE_KEYS,
    EdgeStatusError,
    initial_edge_status,
    reduce_edge_status,
)


def event(node: str, status: str, requirement_id: str = "RFP-001") -> dict:
    return {
        "requirement_id": requirement_id,
        "node": node,
        "status": status,
        "timestamp": "2026-08-31T12:00:00Z",
        "detail": f"{node} {status}",
    }


def completed_path(*nodes: str) -> list[dict]:
    return [
        item
        for node in nodes
        for item in (event(node, "active"), event(node, "complete"))
    ]


def test_initial_edges_are_complete_locked_topology_and_inactive() -> None:
    status = initial_edge_status()

    assert tuple(status) == EDGE_KEYS
    assert len(status) == 39
    assert set(status.values()) == {"inactive"}
    assert initial_edge_status() is not status


def test_incoming_edge_lights_active_then_remains_soft_complete() -> None:
    prefix = completed_path("requirement_analyzer")

    active = reduce_edge_status([*prefix, event("strategy_orchestrator", "active")])
    complete = reduce_edge_status(
        [
            *prefix,
            event("strategy_orchestrator", "active"),
            event("strategy_orchestrator", "complete"),
        ]
    )

    edge = ("requirement_analyzer", "strategy_orchestrator")
    assert active[edge] == "active"
    assert complete[edge] == "complete"


def test_single_domain_path_keeps_alternate_routes_inactive() -> None:
    status = reduce_edge_status(
        completed_path(
            "requirement_analyzer",
            "strategy_orchestrator",
            "product_specialist",
            "merge",
            "citation_validation",
            "source_validation",
            "claim_support_validation",
            "recovery_planning",
            "commitment_ledger",
            "commitment_consistency",
            "conflict_resolution",
            "risk_authority",
            "finalization_guard",
            "commitment_promotion",
        )
    )

    assert status[("strategy_orchestrator", "product_specialist")] == "complete"
    assert status[("product_specialist", "merge")] == "complete"
    assert status[("strategy_orchestrator", "security_specialist")] == "inactive"
    assert status[("security_specialist", "merge")] == "inactive"
    assert status[("recovery_planning", "commitment_ledger")] == "complete"
    assert status[("recovery_planning", "strategy_orchestrator")] == "inactive"
    assert status[("conflict_resolution", "risk_authority")] == "complete"
    assert status[("conflict_resolution", "strategy_orchestrator")] == "inactive"


def test_parallel_specialists_both_fan_in_to_merge() -> None:
    events = completed_path("requirement_analyzer", "strategy_orchestrator")
    events.extend(
        [
            event("product_specialist", "active"),
            event("security_specialist", "active"),
            event("product_specialist", "complete"),
            event("security_specialist", "complete"),
            event("merge", "active"),
            event("merge", "complete"),
        ]
    )

    status = reduce_edge_status(events)

    assert status[("strategy_orchestrator", "product_specialist")] == "complete"
    assert status[("strategy_orchestrator", "security_specialist")] == "complete"
    assert status[("product_specialist", "merge")] == "complete"
    assert status[("security_specialist", "merge")] == "complete"
    assert status[("implementation_specialist", "merge")] == "inactive"


def test_recovery_edge_uses_orange_then_green_and_drives_retry() -> None:
    events = completed_path("requirement_analyzer", "strategy_orchestrator")
    recovering = reduce_edge_status([*events, event("recovery_attempt", "recovery")])
    recovered_events = [
        *events,
        event("recovery_attempt", "recovery"),
        event("recovery_attempt", "complete"),
        event("security_specialist", "active"),
    ]
    retrying = reduce_edge_status(recovered_events)

    assert recovering[("strategy_orchestrator", "recovery_attempt")] == "recovery"
    assert retrying[("strategy_orchestrator", "recovery_attempt")] == "complete"
    assert retrying[("recovery_attempt", "security_specialist")] == "active"
    assert retrying[("strategy_orchestrator", "security_specialist")] == "inactive"


def test_mixed_requirement_events_fail_closed() -> None:
    with pytest.raises(EdgeStatusError, match="different requirements"):
        reduce_edge_status(
            [
                event("requirement_analyzer", "complete", "RFP-001"),
                event("strategy_orchestrator", "active", "RFP-002"),
            ]
        )
