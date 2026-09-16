"""Execution-event reducer for the architecture map's information-flow edges."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from rfp_orchestrator.graph_topology import (
    PEER_TOPOLOGY_EDGES,
    SPECIALIST_NODES,
    GraphNode,
)
from rfp_orchestrator.models import ExecutionEvent, ExecutionStatus
from rfp_orchestrator.node_status import apply_node_event, initial_node_status

EDGE_KEYS = tuple(
    sorted(
        ((source.value, target.value) for source, target in PEER_TOPOLOGY_EDGES),
        key=lambda edge: edge,
    )
)
VALID_EDGE_STATUSES = frozenset(status.value for status in ExecutionStatus)


class EdgeStatusError(ValueError):
    """Raised when edge-flow telemetry violates the map contract."""


def initial_edge_status() -> dict[tuple[str, str], str]:
    """Return every locked topology edge in its inactive visual state."""

    return {edge: ExecutionStatus.INACTIVE.value for edge in EDGE_KEYS}


def validate_edge_status(current: Mapping[tuple[str, str], str]) -> None:
    """Validate exact topology membership, order, and supported status values."""

    if tuple(current) != EDGE_KEYS:
        raise EdgeStatusError("edge status keys must exactly match locked topology order")
    if any(value not in VALID_EDGE_STATUSES for value in current.values()):
        raise EdgeStatusError("edge status contains an unknown status value")


def _validated_event(raw_event: object) -> ExecutionEvent:
    try:
        return ExecutionEvent.model_validate(raw_event)
    except (TypeError, ValueError) as error:
        raise EdgeStatusError("execution event is malformed") from error


def _incoming_sources(
    target: str,
    node_status: Mapping[str, str],
    completed_at: Mapping[str, int],
) -> tuple[str, ...]:
    predecessors = [
        source
        for source, edge_target in EDGE_KEYS
        if edge_target == target
        and node_status[source] != ExecutionStatus.INACTIVE.value
        and source in completed_at
    ]
    if not predecessors:
        return ()

    if target == GraphNode.MERGE.value:
        previous_merge = completed_at.get(GraphNode.MERGE.value, -1)
        return tuple(
            source
            for source in predecessors
            if GraphNode(source) in SPECIALIST_NODES
            and completed_at[source] > previous_merge
        )

    return (max(predecessors, key=lambda source: completed_at[source]),)


def reduce_edge_status(events: Iterable[object]) -> dict[tuple[str, str], str]:
    """Reduce ordered node events into actual traversed and currently active edges."""

    edge_status = initial_edge_status()
    node_status = initial_node_status()
    completed_at: dict[str, int] = {}
    active_sources: dict[str, tuple[str, ...]] = {}
    requirement_id: str | None = None

    for index, raw_event in enumerate(events):
        event = _validated_event(raw_event)
        if requirement_id is None:
            requirement_id = event.requirement_id
        elif event.requirement_id != requirement_id:
            raise EdgeStatusError(
                "execution events from different requirements cannot share one edge map"
            )

        if event.status is not ExecutionStatus.COMPLETE:
            sources = _incoming_sources(event.node, node_status, completed_at)
            if sources:
                active_sources[event.node] = sources
                for source in sources:
                    edge_status[(source, event.node)] = event.status.value
        else:
            sources = active_sources.pop(event.node, ())
            if not sources:
                sources = _incoming_sources(event.node, node_status, completed_at)
            for source in sources:
                edge_status[(source, event.node)] = ExecutionStatus.COMPLETE.value

        node_status = apply_node_event(node_status, event)
        if event.status is ExecutionStatus.COMPLETE:
            completed_at[event.node] = index

    return edge_status
