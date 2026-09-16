"""UI-only attempt counters for bounded recovery nodes."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.models import ExecutionEvent, ExecutionStatus

ATTEMPT_COUNTER_LIMITS = {
    GraphNode.RECOVERY_ATTEMPT.value: 2,
    GraphNode.CONFLICT_REANALYSIS_ATTEMPT.value: 1,
}
ATTEMPT_COUNTER_NODES = tuple(ATTEMPT_COUNTER_LIMITS)


class AttemptCounterError(ValueError):
    """Raised when bounded-attempt telemetry violates the UI counter contract."""


def initial_attempt_counts() -> dict[str, int]:
    """Return fresh zeroed counters in canonical display order."""

    return {node: 0 for node in ATTEMPT_COUNTER_NODES}


def validate_attempt_counts(current: Mapping[str, int]) -> None:
    """Validate exact counter membership and the locked attempt limits."""

    if tuple(current) != ATTEMPT_COUNTER_NODES:
        raise AttemptCounterError(
            "attempt counter keys must exactly match bounded recovery nodes"
        )
    for node, count in current.items():
        if not isinstance(count, int) or isinstance(count, bool):
            raise AttemptCounterError("attempt counter values must be integers")
        if not 0 <= count <= ATTEMPT_COUNTER_LIMITS[node]:
            raise AttemptCounterError("attempt counter exceeds its locked limit")


def _validated_event(raw_event: object) -> ExecutionEvent:
    try:
        return ExecutionEvent.model_validate(raw_event)
    except (TypeError, ValueError) as error:
        raise AttemptCounterError("execution event is malformed") from error


def apply_attempt_event(
    current: Mapping[str, int],
    raw_event: object,
) -> dict[str, int]:
    """Increment once when a bounded recovery node emits its start event."""

    validate_attempt_counts(current)
    event = _validated_event(raw_event)
    updated = dict(current)
    if (
        event.node in ATTEMPT_COUNTER_LIMITS
        and event.status is ExecutionStatus.RECOVERY
    ):
        next_count = updated[event.node] + 1
        if next_count > ATTEMPT_COUNTER_LIMITS[event.node]:
            raise AttemptCounterError("attempt counter exceeds its locked limit")
        updated[event.node] = next_count
    return updated


def reduce_attempt_counts(events: Iterable[object]) -> dict[str, int]:
    """Reduce one requirement's ordered execution events into attempt counts."""

    counts = initial_attempt_counts()
    requirement_id: str | None = None
    for raw_event in events:
        event = _validated_event(raw_event)
        if requirement_id is None:
            requirement_id = event.requirement_id
        elif event.requirement_id != requirement_id:
            raise AttemptCounterError(
                "execution events from different requirements cannot share counters"
            )
        counts = apply_attempt_event(counts, event)
    return counts
