import pytest
from langgraph.graph import END, START

from rfp_orchestrator.graph_topology import (
    PEER_TOPOLOGY_EDGES,
    SPECIALIST_NODES,
    GraphNode,
    PeerTopologyError,
    build_peer_topology_skeleton,
    validate_peer_topology,
)
from rfp_orchestrator.state import new_requirement_state


def test_locked_peer_topology_contract_is_valid() -> None:
    validate_peer_topology(PEER_TOPOLOGY_EDGES)


def test_three_specialists_share_the_same_predecessor_and_successor() -> None:
    for specialist in SPECIALIST_NODES:
        assert (
            GraphNode.STRATEGY_ORCHESTRATOR,
            specialist,
        ) in PEER_TOPOLOGY_EDGES
        assert (specialist, GraphNode.MERGE) in PEER_TOPOLOGY_EDGES


def test_no_specialist_has_an_edge_to_another_specialist() -> None:
    assert not {
        (source, target)
        for source, target in PEER_TOPOLOGY_EDGES
        if source in SPECIALIST_NODES and target in SPECIALIST_NODES
    }


@pytest.mark.parametrize(
    "forbidden_edge",
    [
        (GraphNode.PRODUCT_SPECIALIST, GraphNode.SECURITY_SPECIALIST),
        (GraphNode.SECURITY_SPECIALIST, GraphNode.IMPLEMENTATION_SPECIALIST),
        (GraphNode.IMPLEMENTATION_SPECIALIST, GraphNode.PRODUCT_SPECIALIST),
    ],
)
def test_validator_rejects_every_specialist_to_specialist_direction(
    forbidden_edge: tuple[GraphNode, GraphNode],
) -> None:
    with pytest.raises(PeerTopologyError, match="specialist-to-specialist"):
        validate_peer_topology({*PEER_TOPOLOGY_EDGES, forbidden_edge})


def test_validator_rejects_specialist_bypassing_merge() -> None:
    with pytest.raises(PeerTopologyError, match="fan in directly to merge"):
        validate_peer_topology(
            {
                *PEER_TOPOLOGY_EDGES,
                (GraphNode.PRODUCT_SPECIALIST, GraphNode.STRATEGY_ORCHESTRATOR),
            }
        )


def test_validator_rejects_work_from_an_invalid_predecessor() -> None:
    with pytest.raises(PeerTopologyError, match="orchestration-controlled"):
        validate_peer_topology(
            {
                *PEER_TOPOLOGY_EDGES,
                (GraphNode.MERGE, GraphNode.PRODUCT_SPECIALIST),
            }
        )


def test_validator_rejects_a_missing_peer_edge() -> None:
    incomplete = PEER_TOPOLOGY_EDGES - {
        (GraphNode.IMPLEMENTATION_SPECIALIST, GraphNode.MERGE)
    }

    with pytest.raises(PeerTopologyError, match="missing required edges"):
        validate_peer_topology(incomplete)


def test_compiled_skeleton_contains_only_the_locked_structural_nodes() -> None:
    graph = build_peer_topology_skeleton().get_graph()

    assert set(graph.nodes) == {START, END, *(node.value for node in GraphNode)}


def test_compiled_skeleton_exposes_possible_peer_edges_without_cross_edges() -> None:
    graph = build_peer_topology_skeleton().get_graph()
    compiled_edges = {(edge.source, edge.target) for edge in graph.edges}

    for source, target in PEER_TOPOLOGY_EDGES:
        assert (source.value, target.value) in compiled_edges
    for source in SPECIALIST_NODES:
        for target in SPECIALIST_NODES:
            assert (source.value, target.value) not in compiled_edges


def test_step_2_7_skeleton_stops_before_specialist_execution() -> None:
    graph = build_peer_topology_skeleton()
    initial = new_requirement_state("case-1", "RFP-001", "Confirm SAML support.")

    result = graph.invoke(initial)

    assert result["specialist_outputs"] == {}
    assert result["strategy"] is None
