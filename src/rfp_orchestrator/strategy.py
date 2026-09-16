"""Validated Step 2.4 strategy outputs without Step 2.5 selection logic."""

from rfp_orchestrator.models import Domain, StrategyDecision, StrategyType
from rfp_orchestrator.state import GraphState


def single_specialist(domain: Domain, rationale: str) -> StrategyDecision:
    return StrategyDecision(
        strategy=StrategyType.SINGLE_SPECIALIST,
        selected_specialists=[domain],
        rationale=rationale,
    )


def parallel_specialists(
    domains: list[Domain], rationale: str
) -> StrategyDecision:
    return StrategyDecision(
        strategy=StrategyType.PARALLEL_SPECIALISTS,
        selected_specialists=domains,
        rationale=rationale,
    )


def retrieval_recovery(
    domains: list[Domain], recovery_context: str, rationale: str
) -> StrategyDecision:
    return StrategyDecision(
        strategy=StrategyType.RETRIEVAL_RECOVERY,
        selected_specialists=domains,
        recovery_context=recovery_context,
        rationale=rationale,
    )


def targeted_conflict_resolution(
    domains: list[Domain], conflict_ids: list[str], rationale: str
) -> StrategyDecision:
    return StrategyDecision(
        strategy=StrategyType.TARGETED_CONFLICT_RESOLUTION,
        selected_specialists=domains,
        target_conflict_ids=conflict_ids,
        rationale=rationale,
    )


def immediate_hitl(rationale: str) -> StrategyDecision:
    return StrategyDecision(strategy=StrategyType.IMMEDIATE_HITL, rationale=rationale)


def finalize(rationale: str) -> StrategyDecision:
    return StrategyDecision(strategy=StrategyType.FINALIZE, rationale=rationale)


def strategy_state_update(decision: StrategyDecision) -> GraphState:
    """Translate a validated decision into the explicit graph-state fields."""

    return {
        "strategy": decision.strategy.value,
        "selected_specialists": [
            specialist.value for specialist in decision.selected_specialists
        ],
        "strategy_rationale": decision.rationale,
        "recovery_context": decision.recovery_context,
        "target_conflict_ids": list(decision.target_conflict_ids),
    }
