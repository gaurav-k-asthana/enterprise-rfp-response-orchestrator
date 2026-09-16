"""Step 2.7 peer-only LangGraph topology contract and structural skeleton."""

from __future__ import annotations

from collections.abc import Iterable
from enum import Enum

from langgraph.graph import END, START, StateGraph

from rfp_orchestrator.state import GraphState


class GraphNode(str, Enum):
    REQUIREMENT_ANALYZER = "requirement_analyzer"
    STRATEGY_ORCHESTRATOR = "strategy_orchestrator"
    PRODUCT_SPECIALIST = "product_specialist"
    SECURITY_SPECIALIST = "security_specialist"
    IMPLEMENTATION_SPECIALIST = "implementation_specialist"
    MERGE = "merge"
    CITATION_VALIDATION = "citation_validation"
    SOURCE_VALIDATION = "source_validation"
    CLAIM_SUPPORT_VALIDATION = "claim_support_validation"
    RECOVERY_PLANNING = "recovery_planning"
    RECOVERY_ATTEMPT = "recovery_attempt"
    COMMITMENT_LEDGER = "commitment_ledger"
    COMMITMENT_CONSISTENCY = "commitment_consistency"
    CONFLICT_RESOLUTION = "conflict_resolution"
    CONFLICT_REANALYSIS_ATTEMPT = "conflict_reanalysis_attempt"
    RISK_AUTHORITY = "risk_authority"
    FINALIZATION_GUARD = "finalization_guard"
    COMMITMENT_PROMOTION = "commitment_promotion"
    HUMAN_REVIEW_CHECKPOINT = "human_review_checkpoint"
    HUMAN_REVIEW_INTERRUPT = "human_review_interrupt"
    HUMAN_REWORK_ATTEMPT = "human_rework_attempt"


class PeerTopologyError(ValueError):
    """Raised when graph structure violates the locked peer-specialist design."""


SPECIALIST_NODES = frozenset(
    {
        GraphNode.PRODUCT_SPECIALIST,
        GraphNode.SECURITY_SPECIALIST,
        GraphNode.IMPLEMENTATION_SPECIALIST,
    }
)

PEER_TOPOLOGY_EDGES = frozenset(
    {
        (GraphNode.REQUIREMENT_ANALYZER, GraphNode.STRATEGY_ORCHESTRATOR),
        (GraphNode.STRATEGY_ORCHESTRATOR, GraphNode.PRODUCT_SPECIALIST),
        (GraphNode.STRATEGY_ORCHESTRATOR, GraphNode.SECURITY_SPECIALIST),
        (GraphNode.STRATEGY_ORCHESTRATOR, GraphNode.IMPLEMENTATION_SPECIALIST),
        (GraphNode.PRODUCT_SPECIALIST, GraphNode.MERGE),
        (GraphNode.SECURITY_SPECIALIST, GraphNode.MERGE),
        (GraphNode.IMPLEMENTATION_SPECIALIST, GraphNode.MERGE),
        (GraphNode.MERGE, GraphNode.CITATION_VALIDATION),
        (GraphNode.CITATION_VALIDATION, GraphNode.SOURCE_VALIDATION),
        (GraphNode.SOURCE_VALIDATION, GraphNode.CLAIM_SUPPORT_VALIDATION),
        (GraphNode.CLAIM_SUPPORT_VALIDATION, GraphNode.RECOVERY_PLANNING),
        (GraphNode.RECOVERY_PLANNING, GraphNode.STRATEGY_ORCHESTRATOR),
        (GraphNode.RECOVERY_PLANNING, GraphNode.COMMITMENT_LEDGER),
        (GraphNode.COMMITMENT_LEDGER, GraphNode.COMMITMENT_CONSISTENCY),
        (GraphNode.COMMITMENT_CONSISTENCY, GraphNode.CONFLICT_RESOLUTION),
        (GraphNode.CONFLICT_RESOLUTION, GraphNode.RISK_AUTHORITY),
        (GraphNode.RISK_AUTHORITY, GraphNode.FINALIZATION_GUARD),
        (GraphNode.FINALIZATION_GUARD, GraphNode.COMMITMENT_PROMOTION),
        (GraphNode.FINALIZATION_GUARD, GraphNode.HUMAN_REVIEW_CHECKPOINT),
        (GraphNode.STRATEGY_ORCHESTRATOR, GraphNode.HUMAN_REVIEW_CHECKPOINT),
        (GraphNode.RECOVERY_PLANNING, GraphNode.HUMAN_REVIEW_CHECKPOINT),
        (GraphNode.CONFLICT_RESOLUTION, GraphNode.HUMAN_REVIEW_CHECKPOINT),
        (GraphNode.RISK_AUTHORITY, GraphNode.HUMAN_REVIEW_CHECKPOINT),
        (GraphNode.HUMAN_REVIEW_CHECKPOINT, GraphNode.HUMAN_REVIEW_INTERRUPT),
        (GraphNode.HUMAN_REVIEW_INTERRUPT, GraphNode.FINALIZATION_GUARD),
        (GraphNode.HUMAN_REVIEW_INTERRUPT, GraphNode.RECOVERY_ATTEMPT),
        (GraphNode.HUMAN_REVIEW_INTERRUPT, GraphNode.HUMAN_REWORK_ATTEMPT),
        (GraphNode.CONFLICT_RESOLUTION, GraphNode.STRATEGY_ORCHESTRATOR),
        (GraphNode.STRATEGY_ORCHESTRATOR, GraphNode.RECOVERY_ATTEMPT),
        (GraphNode.STRATEGY_ORCHESTRATOR, GraphNode.CONFLICT_REANALYSIS_ATTEMPT),
        (GraphNode.RECOVERY_ATTEMPT, GraphNode.PRODUCT_SPECIALIST),
        (GraphNode.RECOVERY_ATTEMPT, GraphNode.SECURITY_SPECIALIST),
        (GraphNode.RECOVERY_ATTEMPT, GraphNode.IMPLEMENTATION_SPECIALIST),
        (GraphNode.CONFLICT_REANALYSIS_ATTEMPT, GraphNode.PRODUCT_SPECIALIST),
        (GraphNode.CONFLICT_REANALYSIS_ATTEMPT, GraphNode.SECURITY_SPECIALIST),
        (GraphNode.CONFLICT_REANALYSIS_ATTEMPT, GraphNode.IMPLEMENTATION_SPECIALIST),
        (GraphNode.HUMAN_REWORK_ATTEMPT, GraphNode.PRODUCT_SPECIALIST),
        (GraphNode.HUMAN_REWORK_ATTEMPT, GraphNode.SECURITY_SPECIALIST),
        (GraphNode.HUMAN_REWORK_ATTEMPT, GraphNode.IMPLEMENTATION_SPECIALIST),
    }
)


def validate_peer_topology(
    edges: Iterable[tuple[GraphNode, GraphNode]],
) -> None:
    """Fail if specialists delegate to peers or bypass deterministic merge."""

    edge_set = set(edges)
    missing = PEER_TOPOLOGY_EDGES - edge_set
    if missing:
        formatted = ", ".join(
            f"{source.value}->{target.value}"
            for source, target in sorted(
                missing,
                key=lambda edge: (edge[0].value, edge[1].value),
            )
        )
        raise PeerTopologyError(f"peer topology is missing required edges: {formatted}")

    specialist_to_specialist = {
        (source, target)
        for source, target in edge_set
        if source in SPECIALIST_NODES and target in SPECIALIST_NODES
    }
    if specialist_to_specialist:
        raise PeerTopologyError("specialist-to-specialist edges are forbidden")

    invalid_specialist_successors = {
        (source, target)
        for source, target in edge_set
        if source in SPECIALIST_NODES and target is not GraphNode.MERGE
    }
    if invalid_specialist_successors:
        raise PeerTopologyError("every specialist must fan in directly to merge")

    invalid_specialist_predecessors = {
        (source, target)
        for source, target in edge_set
        if target in SPECIALIST_NODES
        and source
        not in {
            GraphNode.STRATEGY_ORCHESTRATOR,
            GraphNode.RECOVERY_ATTEMPT,
            GraphNode.CONFLICT_REANALYSIS_ATTEMPT,
            GraphNode.HUMAN_REWORK_ATTEMPT,
        }
    }
    if invalid_specialist_predecessors:
        raise PeerTopologyError(
            "specialists may receive work only from orchestration-controlled attempts"
        )


def _structural_node(_: GraphState) -> GraphState:
    """Return no state change; functional nodes are wired in later steps."""

    return {}


def _stop_before_fanout(_: GraphState) -> str:
    """Keep the Step 2.7 skeleton non-operational until Step 2.8 routing exists."""

    return END


def build_peer_topology_skeleton():
    """Compile the inspectable peer topology without executing specialist fan-out."""

    validate_peer_topology(PEER_TOPOLOGY_EDGES)
    builder = StateGraph(GraphState)
    for node in GraphNode:
        builder.add_node(node.value, _structural_node)

    builder.add_edge(START, GraphNode.REQUIREMENT_ANALYZER.value)
    builder.add_edge(
        GraphNode.REQUIREMENT_ANALYZER.value,
        GraphNode.STRATEGY_ORCHESTRATOR.value,
    )
    builder.add_conditional_edges(
        GraphNode.STRATEGY_ORCHESTRATOR.value,
        _stop_before_fanout,
        {
            GraphNode.PRODUCT_SPECIALIST.value: GraphNode.PRODUCT_SPECIALIST.value,
            GraphNode.SECURITY_SPECIALIST.value: GraphNode.SECURITY_SPECIALIST.value,
            GraphNode.IMPLEMENTATION_SPECIALIST.value: (
                GraphNode.IMPLEMENTATION_SPECIALIST.value
            ),
            GraphNode.RECOVERY_ATTEMPT.value: GraphNode.RECOVERY_ATTEMPT.value,
            GraphNode.CONFLICT_REANALYSIS_ATTEMPT.value: (
                GraphNode.CONFLICT_REANALYSIS_ATTEMPT.value
            ),
            GraphNode.HUMAN_REVIEW_CHECKPOINT.value: (
                GraphNode.HUMAN_REVIEW_CHECKPOINT.value
            ),
            END: END,
        },
    )
    for specialist in SPECIALIST_NODES:
        builder.add_edge(specialist.value, GraphNode.MERGE.value)
    builder.add_edge(GraphNode.MERGE.value, GraphNode.CITATION_VALIDATION.value)
    builder.add_edge(
        GraphNode.CITATION_VALIDATION.value,
        GraphNode.SOURCE_VALIDATION.value,
    )
    builder.add_edge(
        GraphNode.SOURCE_VALIDATION.value,
        GraphNode.CLAIM_SUPPORT_VALIDATION.value,
    )
    builder.add_edge(
        GraphNode.CLAIM_SUPPORT_VALIDATION.value,
        GraphNode.RECOVERY_PLANNING.value,
    )
    builder.add_conditional_edges(
        GraphNode.RECOVERY_PLANNING.value,
        _stop_before_fanout,
        {
            GraphNode.STRATEGY_ORCHESTRATOR.value: (
                GraphNode.STRATEGY_ORCHESTRATOR.value
            ),
            GraphNode.COMMITMENT_LEDGER.value: GraphNode.COMMITMENT_LEDGER.value,
            GraphNode.HUMAN_REVIEW_CHECKPOINT.value: (
                GraphNode.HUMAN_REVIEW_CHECKPOINT.value
            ),
            END: END,
        },
    )
    builder.add_edge(
        GraphNode.COMMITMENT_LEDGER.value,
        GraphNode.COMMITMENT_CONSISTENCY.value,
    )
    builder.add_edge(
        GraphNode.COMMITMENT_CONSISTENCY.value,
        GraphNode.CONFLICT_RESOLUTION.value,
    )
    builder.add_conditional_edges(
        GraphNode.CONFLICT_RESOLUTION.value,
        _stop_before_fanout,
        {
            GraphNode.STRATEGY_ORCHESTRATOR.value: (
                GraphNode.STRATEGY_ORCHESTRATOR.value
            ),
            GraphNode.RISK_AUTHORITY.value: GraphNode.RISK_AUTHORITY.value,
            GraphNode.HUMAN_REVIEW_CHECKPOINT.value: (
                GraphNode.HUMAN_REVIEW_CHECKPOINT.value
            ),
            END: END,
        },
    )
    builder.add_conditional_edges(
        GraphNode.RISK_AUTHORITY.value,
        _stop_before_fanout,
        {
            GraphNode.FINALIZATION_GUARD.value: GraphNode.FINALIZATION_GUARD.value,
            GraphNode.HUMAN_REVIEW_CHECKPOINT.value: (
                GraphNode.HUMAN_REVIEW_CHECKPOINT.value
            ),
            END: END,
        },
    )
    builder.add_conditional_edges(
        GraphNode.FINALIZATION_GUARD.value,
        _stop_before_fanout,
        {
            GraphNode.COMMITMENT_PROMOTION.value: GraphNode.COMMITMENT_PROMOTION.value,
            GraphNode.HUMAN_REVIEW_CHECKPOINT.value: (
                GraphNode.HUMAN_REVIEW_CHECKPOINT.value
            ),
            END: END,
        },
    )
    builder.add_edge(
        GraphNode.HUMAN_REVIEW_CHECKPOINT.value,
        GraphNode.HUMAN_REVIEW_INTERRUPT.value,
    )
    builder.add_conditional_edges(
        GraphNode.HUMAN_REVIEW_INTERRUPT.value,
        _stop_before_fanout,
        {
            GraphNode.FINALIZATION_GUARD.value: GraphNode.FINALIZATION_GUARD.value,
            GraphNode.RECOVERY_ATTEMPT.value: GraphNode.RECOVERY_ATTEMPT.value,
            GraphNode.HUMAN_REWORK_ATTEMPT.value: GraphNode.HUMAN_REWORK_ATTEMPT.value,
            END: END,
        },
    )
    builder.add_edge(GraphNode.COMMITMENT_PROMOTION.value, END)
    builder.add_conditional_edges(
        GraphNode.RECOVERY_ATTEMPT.value,
        _stop_before_fanout,
        {
            GraphNode.PRODUCT_SPECIALIST.value: GraphNode.PRODUCT_SPECIALIST.value,
            GraphNode.SECURITY_SPECIALIST.value: GraphNode.SECURITY_SPECIALIST.value,
            GraphNode.IMPLEMENTATION_SPECIALIST.value: (
                GraphNode.IMPLEMENTATION_SPECIALIST.value
            ),
            END: END,
        },
    )
    builder.add_conditional_edges(
        GraphNode.CONFLICT_REANALYSIS_ATTEMPT.value,
        _stop_before_fanout,
        {
            GraphNode.PRODUCT_SPECIALIST.value: GraphNode.PRODUCT_SPECIALIST.value,
            GraphNode.SECURITY_SPECIALIST.value: GraphNode.SECURITY_SPECIALIST.value,
            GraphNode.IMPLEMENTATION_SPECIALIST.value: (
                GraphNode.IMPLEMENTATION_SPECIALIST.value
            ),
            END: END,
        },
    )
    builder.add_conditional_edges(
        GraphNode.HUMAN_REWORK_ATTEMPT.value,
        _stop_before_fanout,
        {
            GraphNode.PRODUCT_SPECIALIST.value: GraphNode.PRODUCT_SPECIALIST.value,
            GraphNode.SECURITY_SPECIALIST.value: GraphNode.SECURITY_SPECIALIST.value,
            GraphNode.IMPLEMENTATION_SPECIALIST.value: (
                GraphNode.IMPLEMENTATION_SPECIALIST.value
            ),
            END: END,
        },
    )
    return builder.compile(name="rfp-peer-topology-step-2-7")
