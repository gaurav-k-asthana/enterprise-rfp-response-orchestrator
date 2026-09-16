from copy import deepcopy

from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.node_status import reduce_node_status
from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.ui import stream_sample_requirement


def test_streamed_run_applies_every_custom_event_incrementally() -> None:
    frames: list[
        tuple[dict[str, str], dict[tuple[str, str], str], dict[str, int], dict]
    ] = []

    def capture(
        status: dict[str, str],
        edge_status: dict[tuple[str, str], str],
        attempt_counts: dict[str, int],
        event: dict,
    ) -> None:
        frames.append((status, edge_status, attempt_counts, event))

    result = stream_sample_requirement(
        load_sample_requirements()[0],
        1,
        "stream-test",
        on_event=capture,
    )

    assert result.thread_id == "ui-stream-test-0001-rfp-001"
    assert result.state["final_status"] == "FINALIZED"
    assert result.event_count == len(frames) == 28
    assert frames[0][3]["node"] == GraphNode.REQUIREMENT_ANALYZER.value
    assert frames[0][3]["status"] == "active"
    assert frames[0][0]["requirement_analyzer"] == "active"
    assert frames[1][3]["status"] == "complete"
    assert frames[1][0]["requirement_analyzer"] == "complete"
    assert frames[-1][3]["node"] == GraphNode.COMMITMENT_PROMOTION.value
    assert frames[-1][3]["status"] == "complete"
    assert result.node_status == reduce_node_status(result.state["execution_events"])
    assert result.edge_status[("strategy_orchestrator", "product_specialist")] == (
        "complete"
    )
    assert result.edge_status[("strategy_orchestrator", "security_specialist")] == (
        "inactive"
    )
    assert result.attempt_counts == {
        "recovery_attempt": 0,
        "conflict_reanalysis_attempt": 0,
    }
    assert result.visualization_failed is False


def test_streamed_status_frames_and_events_are_callback_safe_copies() -> None:
    received: list[tuple[dict[str, str], dict]] = []

    def capture_and_mutate(
        status: dict[str, str],
        edge_status: dict[tuple[str, str], str],
        attempt_counts: dict[str, int],
        event: dict,
    ) -> None:
        received.append((deepcopy(status), deepcopy(event)))
        status["requirement_analyzer"] = "blocked"
        edge_status[("requirement_analyzer", "strategy_orchestrator")] = "blocked"
        attempt_counts["recovery_attempt"] = 2
        event["node"] = "tampered"

    result = stream_sample_requirement(
        load_sample_requirements()[0],
        1,
        "copy-test",
        on_event=capture_and_mutate,
    )

    assert received
    assert result.node_status["requirement_analyzer"] == "complete"
    assert result.edge_status[("requirement_analyzer", "strategy_orchestrator")] == (
        "complete"
    )
    assert result.attempt_counts["recovery_attempt"] == 0
    assert result.state["execution_events"][0]["node"] == "requirement_analyzer"


def test_cross_domain_stream_completes_both_peers_before_merge() -> None:
    events: list[dict] = []

    def capture(
        _status: dict[str, str],
        _edge_status: dict[tuple[str, str], str],
        _attempt_counts: dict[str, int],
        event: dict,
    ) -> None:
        events.append(event)

    result = stream_sample_requirement(
        load_sample_requirements()[1],
        1,
        "peer-stream-test",
        on_event=capture,
    )

    merge_active = next(
        index
        for index, event in enumerate(events)
        if event["node"] == "merge" and event["status"] == "active"
    )
    for specialist in ("product_specialist", "security_specialist"):
        completed = next(
            index
            for index, event in enumerate(events)
            if event["node"] == specialist and event["status"] == "complete"
        )
        assert completed < merge_active
        assert result.node_status[specialist] == "complete"
    assert result.node_status["implementation_specialist"] == "inactive"
