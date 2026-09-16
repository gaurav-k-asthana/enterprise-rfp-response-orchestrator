"""Step 2.8 selected-specialist LangGraph fan-out with keyed branch state."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Protocol

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from rfp_orchestrator.citation_validation import citation_validation_node
from rfp_orchestrator.claim_support import claim_support_validation_node
from rfp_orchestrator.commitment_consistency import commitment_consistency_node
from rfp_orchestrator.commitment_ledger import commitment_ledger_node
from rfp_orchestrator.commitment_promotion import commitment_promotion_node
from rfp_orchestrator.conflict_resolution import (
    conflict_reanalysis_attempt_node,
    conflict_resolution_node,
)
from rfp_orchestrator.execution_events import EventClock, instrument_node, utc_event_timestamp
from rfp_orchestrator.finalization import finalization_guard_node
from rfp_orchestrator.graph_topology import (
    PEER_TOPOLOGY_EDGES,
    GraphNode,
    validate_peer_topology,
)
from rfp_orchestrator.human_review import (
    human_review_interrupt_node,
    human_rework_attempt_node,
    prepare_human_review_node,
)
from rfp_orchestrator.models import (
    Domain,
    ExecutionStatus,
    Requirement,
    StrategyDecision,
    StrategySelectionContext,
)
from rfp_orchestrator.orchestrator import orchestrator_state_update
from rfp_orchestrator.recovery import (
    evidence_recovery_planning_node,
    recovery_attempt_node,
)
from rfp_orchestrator.requirement_classification import analyze_requirement_input
from rfp_orchestrator.retrieval import OfflineSpecialistRetrievers, SpecialistRetriever
from rfp_orchestrator.risk_authority import risk_authority_node
from rfp_orchestrator.source_validation import source_validation_node
from rfp_orchestrator.specialist_merge import merge_specialist_state
from rfp_orchestrator.specialists import (
    SpecialistNodeResult,
    implementation_specialist_node,
    product_specialist_node,
    security_specialist_node,
)
from rfp_orchestrator.state import GraphState

SpecialistFunction = Callable[..., SpecialistNodeResult]


class SpecialistRetrieverBundle(Protocol):
    product: SpecialistRetriever
    security: SpecialistRetriever
    implementation: SpecialistRetriever

_NODE_BY_DOMAIN = {
    Domain.PRODUCT: GraphNode.PRODUCT_SPECIALIST.value,
    Domain.SECURITY: GraphNode.SECURITY_SPECIALIST.value,
    Domain.IMPLEMENTATION: GraphNode.IMPLEMENTATION_SPECIALIST.value,
}


def _requirement_from_state(state: GraphState) -> Requirement:
    return Requirement.model_validate(
        {
            "requirement_id": state["requirement_id"],
            "original_text": state["original_text"],
            "atomic_requirements": state.get("atomic_requirements", []),
            "prompt_injection_detected": state.get(
                "prompt_injection_detected", False
            ),
            "prompt_injection_signals": state.get("prompt_injection_signals", []),
            "assigned_domains": state.get("assigned_domains", []),
            "attributes": state.get("requirement_attributes", []),
            "ambiguity_signals": state.get("ambiguity_signals", []),
            "initial_risk_flags": state.get("initial_risk_flags", []),
        }
    )


def requirement_analyzer_node(state: GraphState) -> GraphState:
    analyzed = analyze_requirement_input(
        Requirement(
            requirement_id=state["requirement_id"],
            original_text=state["original_text"],
        )
    )
    return {
        "atomic_requirements": list(analyzed.atomic_requirements),
        "prompt_injection_detected": analyzed.prompt_injection_detected,
        "prompt_injection_signals": [
            signal.model_dump(mode="json")
            for signal in analyzed.prompt_injection_signals
        ],
        "assigned_domains": [domain.value for domain in analyzed.assigned_domains],
        "requirement_attributes": [
            attribute.value for attribute in analyzed.attributes
        ],
        "ambiguity_signals": [
            signal.model_dump(mode="json") for signal in analyzed.ambiguity_signals
        ],
        "initial_risk_flags": [risk.value for risk in analyzed.initial_risk_flags],
    }


def strategy_orchestrator_node(state: GraphState) -> GraphState:
    context = StrategySelectionContext(
        requirement=_requirement_from_state(state),
        retry_count=state.get("retry_count", 0),
        recovery_specialists=[
            Domain(value) for value in state.get("recovery_specialists", [])
        ],
        recovery_context=state.get("recovery_context"),
        conflict_specialists=[
            Domain(value) for value in state.get("conflict_specialists", [])
        ]
        if state.get("conflict_reanalysis_needed")
        else [],
        conflict_ids=state.get("target_conflict_ids", [])
        if state.get("conflict_reanalysis_needed")
        else [],
    )
    update = orchestrator_state_update(context)
    if not state.get("initial_specialists") and update.get("strategy") in {
        "SINGLE_SPECIALIST",
        "PARALLEL_SPECIALISTS",
    }:
        update["initial_specialists"] = list(update["selected_specialists"])
    if update.get("strategy") == "IMMEDIATE_HITL":
        update["final_status"] = "NEEDS_HUMAN"
        update["final_answer"] = None
    return update


def route_selected_specialists(
    state: GraphState,
    *,
    human_review_route: str = END,
) -> str | list[str]:
    """Return only validated selected peer nodes, or END for a terminal strategy."""

    decision = StrategyDecision(
        strategy=state["strategy"],
        selected_specialists=state.get("selected_specialists", []),
        rationale=state.get("strategy_rationale") or "",
        recovery_context=state.get("recovery_context"),
        target_conflict_ids=state.get("target_conflict_ids", []),
    )
    if not decision.selected_specialists:
        if decision.strategy.value == "IMMEDIATE_HITL":
            return human_review_route
        return END
    if decision.strategy.value == "RETRIEVAL_RECOVERY":
        return GraphNode.RECOVERY_ATTEMPT.value
    if decision.strategy.value == "TARGETED_CONFLICT_RESOLUTION":
        return GraphNode.CONFLICT_REANALYSIS_ATTEMPT.value
    routes = [_NODE_BY_DOMAIN[domain] for domain in decision.selected_specialists]
    return routes[0] if len(routes) == 1 else routes


def route_recovery_plan(
    state: GraphState,
    *,
    human_review_route: str = END,
) -> str:
    if state.get("recovery_needed") and not state.get("recovery_exhausted"):
        return GraphNode.STRATEGY_ORCHESTRATOR.value
    if state.get("claim_support_valid") is True and not state.get(
        "recovery_exhausted"
    ):
        return GraphNode.COMMITMENT_LEDGER.value
    if state.get("recovery_exhausted"):
        return human_review_route
    return END


def route_recovery_specialists(state: GraphState) -> str | list[str]:
    specialists = [Domain(value) for value in state.get("selected_specialists", [])]
    if not specialists:
        raise ValueError("recovery attempt requires selected specialists")
    routes = [_NODE_BY_DOMAIN[domain] for domain in specialists]
    return routes[0] if len(routes) == 1 else routes


def route_conflict_plan(
    state: GraphState,
    *,
    human_review_route: str = END,
) -> str:
    if state.get("conflict_reanalysis_needed"):
        return GraphNode.STRATEGY_ORCHESTRATOR.value
    if state.get("conflict_unresolved"):
        return human_review_route
    return GraphNode.RISK_AUTHORITY.value


def route_risk_authority(
    state: GraphState,
    *,
    human_review_route: str = END,
) -> str:
    if state.get("authority_gate_passed") is True:
        return GraphNode.FINALIZATION_GUARD.value
    if state.get("authority_required") is True:
        return human_review_route
    raise ValueError("risk-authority gate did not produce a terminal decision")


def route_conflict_specialists(state: GraphState) -> str | list[str]:
    specialists = [Domain(value) for value in state.get("selected_specialists", [])]
    if not specialists:
        raise ValueError("conflict reanalysis requires selected specialists")
    routes = [_NODE_BY_DOMAIN[domain] for domain in specialists]
    return routes[0] if len(routes) == 1 else routes


def route_human_review_resume(state: GraphState) -> str:
    """Route only a validated action returned by the interrupt node."""

    route = state.get("human_resume_route")
    allowed = {
        "finalization_guard": GraphNode.FINALIZATION_GUARD.value,
        "recovery_attempt": GraphNode.RECOVERY_ATTEMPT.value,
        "human_rework_attempt": GraphNode.HUMAN_REWORK_ATTEMPT.value,
        "end": END,
    }
    if route not in allowed:
        raise ValueError("human-review resume did not produce a valid next route")
    return allowed[route]


def route_finalization(
    state: GraphState,
    *,
    human_review_route: str = END,
) -> str:
    """Permit promotion only after the hard finalization guard passes."""

    if state.get("finalization_passed") is True:
        return GraphNode.COMMITMENT_PROMOTION.value
    if state.get("finalization_passed") is False:
        if state.get("final_status") == "REJECTED":
            return END
        return human_review_route
    raise ValueError("finalization guard did not produce a routing decision")


def route_human_rework_specialists(state: GraphState) -> str | list[str]:
    specialists = [Domain(value) for value in state.get("selected_specialists", [])]
    if not specialists:
        raise ValueError("human guidance requires selected specialists")
    routes = [_NODE_BY_DOMAIN[domain] for domain in specialists]
    return routes[0] if len(routes) == 1 else routes


def _specialist_graph_node(
    specialist: SpecialistFunction,
    retriever: SpecialistRetriever,
) -> Callable[[GraphState], GraphState]:
    def run(state: GraphState) -> GraphState:
        query_override = None
        if state.get("strategy") == "RETRIEVAL_RECOVERY":
            specialist_key = retriever.domain.value
            query_override = str(
                state.get("reformulated_queries", {})
                .get(specialist_key, {})
                .get("reformulated_query", "")
            )
        elif state.get("strategy") == "TARGETED_CONFLICT_RESOLUTION":
            specialist_key = retriever.domain.value
            query_override = str(
                state.get("conflict_reanalysis_queries", {})
                .get(specialist_key, {})
                .get("reanalysis_query", "")
            )
        elif state.get("human_rework_active"):
            specialist_key = retriever.domain.value
            query_override = str(
                state.get("human_rework_queries", {})
                .get(specialist_key, {})
                .get("rework_query", "")
            )
        result = specialist(
            _requirement_from_state(state),
            retriever,
            query_override=query_override,
        )
        key = result.output.specialist.value
        return {
            "specialist_outputs": {
                key: result.output.model_dump(mode="json"),
            },
            "specialist_evidence": {
                key: [item.model_dump(mode="json") for item in result.evidence],
            },
        }

    return run


def _merge_barrier(state: GraphState) -> GraphState:
    """Merge the complete reducer-backed branch state in canonical order."""

    return merge_specialist_state(state)


def build_selected_fanout_graph(
    retrievers: OfflineSpecialistRetrievers | SpecialistRetrieverBundle,
    *,
    specialist_functions: Mapping[Domain, SpecialistFunction] | None = None,
    event_clock: EventClock = utc_event_timestamp,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Compile analyzer → orchestrator → selected peers → merge barrier."""

    validate_peer_topology(PEER_TOPOLOGY_EDGES)
    functions = dict(
        specialist_functions
        or {
            Domain.PRODUCT: product_specialist_node,
            Domain.SECURITY: security_specialist_node,
            Domain.IMPLEMENTATION: implementation_specialist_node,
        }
    )
    if set(functions) != set(Domain):
        raise ValueError("specialist function map requires all three domains")
    builder = StateGraph(GraphState)
    builder.add_node(
        GraphNode.REQUIREMENT_ANALYZER.value,
        instrument_node(
            GraphNode.REQUIREMENT_ANALYZER.value,
            requirement_analyzer_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.STRATEGY_ORCHESTRATOR.value,
        instrument_node(
            GraphNode.STRATEGY_ORCHESTRATOR.value,
            strategy_orchestrator_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.PRODUCT_SPECIALIST.value,
        instrument_node(
            GraphNode.PRODUCT_SPECIALIST.value,
            _specialist_graph_node(functions[Domain.PRODUCT], retrievers.product),
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.SECURITY_SPECIALIST.value,
        instrument_node(
            GraphNode.SECURITY_SPECIALIST.value,
            _specialist_graph_node(functions[Domain.SECURITY], retrievers.security),
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.IMPLEMENTATION_SPECIALIST.value,
        instrument_node(
            GraphNode.IMPLEMENTATION_SPECIALIST.value,
            _specialist_graph_node(
                functions[Domain.IMPLEMENTATION],
                retrievers.implementation,
            ),
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.MERGE.value,
        instrument_node(
            GraphNode.MERGE.value,
            _merge_barrier,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.CITATION_VALIDATION.value,
        instrument_node(
            GraphNode.CITATION_VALIDATION.value,
            citation_validation_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.SOURCE_VALIDATION.value,
        instrument_node(
            GraphNode.SOURCE_VALIDATION.value,
            source_validation_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.CLAIM_SUPPORT_VALIDATION.value,
        instrument_node(
            GraphNode.CLAIM_SUPPORT_VALIDATION.value,
            claim_support_validation_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.RECOVERY_PLANNING.value,
        instrument_node(
            GraphNode.RECOVERY_PLANNING.value,
            evidence_recovery_planning_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.RECOVERY_ATTEMPT.value,
        instrument_node(
            GraphNode.RECOVERY_ATTEMPT.value,
            recovery_attempt_node,
            clock=event_clock,
            start_status=ExecutionStatus.RECOVERY,
        ),
    )
    builder.add_node(
        GraphNode.COMMITMENT_LEDGER.value,
        instrument_node(
            GraphNode.COMMITMENT_LEDGER.value,
            commitment_ledger_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.COMMITMENT_PROMOTION.value,
        instrument_node(
            GraphNode.COMMITMENT_PROMOTION.value,
            commitment_promotion_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.COMMITMENT_CONSISTENCY.value,
        instrument_node(
            GraphNode.COMMITMENT_CONSISTENCY.value,
            commitment_consistency_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.CONFLICT_RESOLUTION.value,
        instrument_node(
            GraphNode.CONFLICT_RESOLUTION.value,
            conflict_resolution_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.CONFLICT_REANALYSIS_ATTEMPT.value,
        instrument_node(
            GraphNode.CONFLICT_REANALYSIS_ATTEMPT.value,
            conflict_reanalysis_attempt_node,
            clock=event_clock,
            start_status=ExecutionStatus.RECOVERY,
        ),
    )
    builder.add_node(
        GraphNode.RISK_AUTHORITY.value,
        instrument_node(
            GraphNode.RISK_AUTHORITY.value,
            risk_authority_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.FINALIZATION_GUARD.value,
        instrument_node(
            GraphNode.FINALIZATION_GUARD.value,
            finalization_guard_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.HUMAN_REVIEW_CHECKPOINT.value,
        instrument_node(
            GraphNode.HUMAN_REVIEW_CHECKPOINT.value,
            prepare_human_review_node,
            clock=event_clock,
        ),
    )
    builder.add_node(
        GraphNode.HUMAN_REVIEW_INTERRUPT.value,
        lambda state: human_review_interrupt_node(state, clock=event_clock),
    )
    builder.add_node(
        GraphNode.HUMAN_REWORK_ATTEMPT.value,
        instrument_node(
            GraphNode.HUMAN_REWORK_ATTEMPT.value,
            human_rework_attempt_node,
            clock=event_clock,
            start_status=ExecutionStatus.RECOVERY,
        ),
    )

    human_review_route = (
        GraphNode.HUMAN_REVIEW_CHECKPOINT.value if checkpointer is not None else END
    )

    builder.add_edge(START, GraphNode.REQUIREMENT_ANALYZER.value)
    builder.add_edge(
        GraphNode.REQUIREMENT_ANALYZER.value,
        GraphNode.STRATEGY_ORCHESTRATOR.value,
    )
    builder.add_conditional_edges(
        GraphNode.STRATEGY_ORCHESTRATOR.value,
        lambda state: route_selected_specialists(
            state,
            human_review_route=human_review_route,
        ),
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
    builder.add_edge(GraphNode.PRODUCT_SPECIALIST.value, GraphNode.MERGE.value)
    builder.add_edge(GraphNode.SECURITY_SPECIALIST.value, GraphNode.MERGE.value)
    builder.add_edge(GraphNode.IMPLEMENTATION_SPECIALIST.value, GraphNode.MERGE.value)
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
        lambda state: route_recovery_plan(
            state,
            human_review_route=human_review_route,
        ),
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
    builder.add_conditional_edges(
        GraphNode.RECOVERY_ATTEMPT.value,
        route_recovery_specialists,
        {
            GraphNode.PRODUCT_SPECIALIST.value: GraphNode.PRODUCT_SPECIALIST.value,
            GraphNode.SECURITY_SPECIALIST.value: GraphNode.SECURITY_SPECIALIST.value,
            GraphNode.IMPLEMENTATION_SPECIALIST.value: (
                GraphNode.IMPLEMENTATION_SPECIALIST.value
            ),
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
        lambda state: route_conflict_plan(
            state,
            human_review_route=human_review_route,
        ),
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
        lambda state: route_risk_authority(
            state,
            human_review_route=human_review_route,
        ),
        {
            GraphNode.FINALIZATION_GUARD.value: GraphNode.FINALIZATION_GUARD.value,
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
        GraphNode.FINALIZATION_GUARD.value,
        lambda state: route_finalization(
            state,
            human_review_route=human_review_route,
        ),
        {
            GraphNode.COMMITMENT_PROMOTION.value: GraphNode.COMMITMENT_PROMOTION.value,
            GraphNode.HUMAN_REVIEW_CHECKPOINT.value: (
                GraphNode.HUMAN_REVIEW_CHECKPOINT.value
            ),
            END: END,
        },
    )
    builder.add_conditional_edges(
        GraphNode.HUMAN_REVIEW_INTERRUPT.value,
        route_human_review_resume,
        {
            GraphNode.FINALIZATION_GUARD.value: GraphNode.FINALIZATION_GUARD.value,
            GraphNode.RECOVERY_ATTEMPT.value: GraphNode.RECOVERY_ATTEMPT.value,
            GraphNode.HUMAN_REWORK_ATTEMPT.value: GraphNode.HUMAN_REWORK_ATTEMPT.value,
            END: END,
        },
    )
    builder.add_edge(GraphNode.COMMITMENT_PROMOTION.value, END)
    builder.add_conditional_edges(
        GraphNode.CONFLICT_REANALYSIS_ATTEMPT.value,
        route_conflict_specialists,
        {
            GraphNode.PRODUCT_SPECIALIST.value: GraphNode.PRODUCT_SPECIALIST.value,
            GraphNode.SECURITY_SPECIALIST.value: GraphNode.SECURITY_SPECIALIST.value,
            GraphNode.IMPLEMENTATION_SPECIALIST.value: (
                GraphNode.IMPLEMENTATION_SPECIALIST.value
            ),
        },
    )
    builder.add_conditional_edges(
        GraphNode.HUMAN_REWORK_ATTEMPT.value,
        route_human_rework_specialists,
        {
            GraphNode.PRODUCT_SPECIALIST.value: GraphNode.PRODUCT_SPECIALIST.value,
            GraphNode.SECURITY_SPECIALIST.value: GraphNode.SECURITY_SPECIALIST.value,
            GraphNode.IMPLEMENTATION_SPECIALIST.value: (
                GraphNode.IMPLEMENTATION_SPECIALIST.value
            ),
        },
    )
    return builder.compile(
        checkpointer=checkpointer,
        name="rfp-selected-fanout-step-2-8",
    )


def build_checkpointed_fanout_graph(
    retrievers: OfflineSpecialistRetrievers,
    *,
    event_clock: EventClock = utc_event_timestamp,
    checkpointer: BaseCheckpointSaver | None = None,
):
    """Compile the V1 graph with checkpoint-backed human-review interrupts."""

    return build_selected_fanout_graph(
        retrievers,
        event_clock=event_clock,
        checkpointer=(checkpointer if checkpointer is not None else InMemorySaver()),
    )
