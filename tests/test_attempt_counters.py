from copy import deepcopy
from xml.etree import ElementTree

import pytest

from rfp_orchestrator.architecture_map import render_architecture_html
from rfp_orchestrator.attempt_counters import (
    ATTEMPT_COUNTER_NODES,
    AttemptCounterError,
    apply_attempt_event,
    initial_attempt_counts,
    reduce_attempt_counts,
)
from rfp_orchestrator.node_status import initial_node_status


def event(
    node: str,
    status: str,
    requirement_id: str = "RFP-003",
) -> dict:
    return {
        "requirement_id": requirement_id,
        "node": node,
        "status": status,
        "timestamp": "2026-08-31T18:00:00Z",
        "detail": f"{node} {status}",
    }


def test_initial_attempt_counts_are_zeroed_and_fresh() -> None:
    counts = initial_attempt_counts()

    assert tuple(counts) == ATTEMPT_COUNTER_NODES
    assert counts == {
        "recovery_attempt": 0,
        "conflict_reanalysis_attempt": 0,
    }
    assert initial_attempt_counts() is not counts


def test_retrieval_counter_increments_only_on_each_recovery_start() -> None:
    events = [
        event("recovery_attempt", "recovery"),
        event("recovery_attempt", "complete"),
        event("recovery_attempt", "recovery"),
        event("recovery_attempt", "complete"),
    ]
    original = deepcopy(events)

    counts = reduce_attempt_counts(events)

    assert counts["recovery_attempt"] == 2
    assert counts["conflict_reanalysis_attempt"] == 0
    assert events == original


def test_conflict_counter_increments_once_on_its_recovery_start() -> None:
    counts = reduce_attempt_counts(
        [
            event("conflict_reanalysis_attempt", "recovery", "RFP-014"),
            event("conflict_reanalysis_attempt", "complete", "RFP-014"),
        ]
    )

    assert counts == {
        "recovery_attempt": 0,
        "conflict_reanalysis_attempt": 1,
    }


def test_unrelated_events_do_not_change_attempt_counts() -> None:
    initial = initial_attempt_counts()

    updated = apply_attempt_event(initial, event("product_specialist", "active"))

    assert updated == initial
    assert updated is not initial


@pytest.mark.parametrize(
    "events",
    [
        [
            event("recovery_attempt", "recovery"),
            event("recovery_attempt", "recovery"),
            event("recovery_attempt", "recovery"),
        ],
        [
            event("conflict_reanalysis_attempt", "recovery"),
            event("conflict_reanalysis_attempt", "recovery"),
        ],
    ],
)
def test_counter_limits_fail_closed(events: list[dict]) -> None:
    with pytest.raises(AttemptCounterError, match="locked limit"):
        reduce_attempt_counts(events)


def test_mixed_requirement_events_cannot_share_attempt_counters() -> None:
    with pytest.raises(AttemptCounterError, match="different requirements"):
        reduce_attempt_counts(
            [
                event("recovery_attempt", "recovery", "RFP-003"),
                event("recovery_attempt", "complete", "RFP-014"),
            ]
        )


def test_renderer_shows_bounded_counters_only_on_the_two_attempt_nodes() -> None:
    counts = {
        "recovery_attempt": 2,
        "conflict_reanalysis_attempt": 1,
    }
    fragment = render_architecture_html(
        initial_node_status(),
        attempt_counts=counts,
    )
    root = ElementTree.fromstring(f"<root>{fragment}</root>")
    nodes = root.findall("div/svg/g")
    by_name = {node.attrib["data-node"]: node for node in nodes}

    recovery = by_name["recovery_attempt"]
    conflict = by_name["conflict_reanalysis_attempt"]
    assert recovery.find("text[@class='rfp-map-attempt']").text == "Attempts: 2/2"
    assert conflict.find("text[@class='rfp-map-attempt']").text == "Attempts: 1/1"
    assert "attempts: 2 of 2" in recovery.attrib["aria-label"]
    assert "attempts: 1 of 1" in conflict.attrib["aria-label"]
    assert all(
        node.find("text[@class='rfp-map-attempt']") is None
        for name, node in by_name.items()
        if name not in ATTEMPT_COUNTER_NODES
    )
