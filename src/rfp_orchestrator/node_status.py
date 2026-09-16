"""Stable event-to-node-status reducer for the Streamlit architecture map."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.models import ExecutionEvent, ExecutionStatus

ARCHITECTURE_NODES = tuple(node.value for node in GraphNode)
VALID_NODE_STATUSES = frozenset(status.value for status in ExecutionStatus)
SPECIALIST_NODE_BY_DOMAIN = {
    "product": GraphNode.PRODUCT_SPECIALIST.value,
    "security": GraphNode.SECURITY_SPECIALIST.value,
    "implementation": GraphNode.IMPLEMENTATION_SPECIALIST.value,
}


class NodeStatusError(ValueError):
    """Raised when UI telemetry violates the stable architecture-map contract."""


def initial_node_status() -> dict[str, str]:
    """Return a fresh canonical status dictionary with every node inactive."""

    return {
        node: ExecutionStatus.INACTIVE.value
        for node in ARCHITECTURE_NODES
    }


def validate_node_status(current: Mapping[str, str]) -> None:
    """Validate the exact ordered dictionary contract used by map renderers."""

    if tuple(current) != ARCHITECTURE_NODES:
        raise NodeStatusError(
            "node status keys must exactly match canonical architecture order"
        )
    if any(value not in VALID_NODE_STATUSES for value in current.values()):
        raise NodeStatusError("node status contains an unknown status value")


def validate_unselected_specialists_inactive(
    current: Mapping[str, str],
    selected_specialists: Iterable[object],
) -> None:
    """Fail closed if a specialist outside the selected set is not inactive."""

    validate_node_status(current)
    if isinstance(selected_specialists, (str, bytes)):
        raise NodeStatusError("selected specialists must be a domain collection")
    try:
        selected = tuple(selected_specialists)
    except TypeError as error:
        raise NodeStatusError("selected specialists must be a domain collection") from error
    if any(
        not isinstance(domain, str) or domain not in SPECIALIST_NODE_BY_DOMAIN
        for domain in selected
    ):
        raise NodeStatusError("selected specialists contain an unknown domain")
    if len(selected) != len(set(selected)):
        raise NodeStatusError("selected specialists cannot contain duplicates")

    selected_set = set(selected)
    for domain, node in SPECIALIST_NODE_BY_DOMAIN.items():
        if (
            domain not in selected_set
            and current[node] != ExecutionStatus.INACTIVE.value
        ):
            raise NodeStatusError(
                f"unselected {domain} specialist must remain inactive"
            )


def _validated_event(raw_event: object) -> ExecutionEvent:
    try:
        event = ExecutionEvent.model_validate(raw_event)
    except (TypeError, ValueError) as error:
        raise NodeStatusError("execution event is malformed") from error
    if event.node not in ARCHITECTURE_NODES:
        raise NodeStatusError("execution event references an unknown architecture node")
    return event


def apply_node_event(
    current: Mapping[str, str],
    raw_event: object,
) -> dict[str, str]:
    """Apply one event immutably; the latest event is the node's current status."""

    validate_node_status(current)
    event = _validated_event(raw_event)
    updated = dict(current)
    updated[event.node] = event.status.value
    return updated


def reduce_node_status(events: Iterable[object]) -> dict[str, str]:
    """Reduce one requirement's ordered events into the canonical status dictionary."""

    status = initial_node_status()
    requirement_id: str | None = None
    for raw_event in events:
        event = _validated_event(raw_event)
        if requirement_id is None:
            requirement_id = event.requirement_id
        elif event.requirement_id != requirement_id:
            raise NodeStatusError(
                "execution events from different requirements cannot share one map"
            )
        status = apply_node_event(status, event)
    return status
