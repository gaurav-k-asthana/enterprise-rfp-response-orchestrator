"""Append-only and streamable execution-event instrumentation for graph nodes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

from langgraph.config import get_stream_writer

from rfp_orchestrator.models import ExecutionEvent, ExecutionStatus
from rfp_orchestrator.state import GraphState

EventClock = Callable[[], str]
GraphNodeFunction = Callable[[GraphState], GraphState]


def utc_event_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _event(
    state: GraphState,
    *,
    node: str,
    status: ExecutionStatus,
    clock: EventClock,
    detail: str,
) -> dict:
    return ExecutionEvent(
        requirement_id=state["requirement_id"],
        node=node,
        status=status,
        timestamp=clock(),
        detail=detail,
    ).model_dump(mode="json")


def instrument_node(
    node: str,
    function: GraphNodeFunction,
    *,
    clock: EventClock = utc_event_timestamp,
    start_status: ExecutionStatus = ExecutionStatus.ACTIVE,
) -> GraphNodeFunction:
    """Stream start/terminal events and append successful events to graph state."""

    def run(state: GraphState) -> GraphState:
        writer = get_stream_writer()
        started = _event(
            state,
            node=node,
            status=start_status,
            clock=clock,
            detail=(
                f"{node} recovery started"
                if start_status is ExecutionStatus.RECOVERY
                else f"{node} started"
            ),
        )
        writer(started)
        try:
            update = function(state)
        except Exception as error:
            blocked = _event(
                state,
                node=node,
                status=ExecutionStatus.BLOCKED,
                clock=clock,
                detail=f"{node} failed: {type(error).__name__}",
            )
            writer(blocked)
            raise

        completed = _event(
            state,
            node=node,
            status=ExecutionStatus.COMPLETE,
            clock=clock,
            detail=f"{node} completed",
        )
        writer(completed)
        node_events = [started, *update.get("execution_events", []), completed]
        return {**update, "execution_events": node_events}

    return run
