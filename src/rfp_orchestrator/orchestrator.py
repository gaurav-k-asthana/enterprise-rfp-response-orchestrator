"""Deterministic minimum-cost safe-path selection for Step 2.5."""

from rfp_orchestrator.models import StrategyDecision, StrategySelectionContext
from rfp_orchestrator.risk_authority import assess_preflight_safety
from rfp_orchestrator.state import GraphState
from rfp_orchestrator.strategy import (
    finalize,
    immediate_hitl,
    parallel_specialists,
    retrieval_recovery,
    single_specialist,
    strategy_state_update,
    targeted_conflict_resolution,
)

MAX_RETRIEVAL_RETRIES = 2

def select_minimum_safe_strategy(
    context: StrategySelectionContext,
) -> StrategyDecision:
    """Choose the cheapest route that does not bypass an active safety signal."""

    requirement = context.requirement
    preflight = assess_preflight_safety(requirement)

    if preflight.prompt_injection_detected:
        return immediate_hitl(preflight.reason)

    if preflight.requires_human and not context.human_approval_present:
        return immediate_hitl(preflight.reason)

    if context.conflict_ids:
        return targeted_conflict_resolution(
            context.conflict_specialists,
            context.conflict_ids,
            "Resolve the identified conflicts with only the affected peer specialists.",
        )

    if context.recovery_specialists:
        if context.retry_count >= MAX_RETRIEVAL_RETRIES:
            return immediate_hitl(
                "The two-retry retrieval budget is exhausted; automated recovery must stop."
            )
        return retrieval_recovery(
            context.recovery_specialists,
            context.recovery_context or "",
            "Retry only the failed specialist retrieval using recorded failure context.",
        )

    if context.finalization_ready:
        return finalize(
            "Downstream evidence, consistency, and authority guards marked the response ready."
        )

    domains = requirement.assigned_domains
    if len(domains) == 1:
        return single_specialist(
            domains[0],
            "One classified domain requires one peer specialist.",
        )
    if len(domains) >= 2:
        return parallel_specialists(
            domains,
            "Multiple classified domains require parallel peer specialists.",
        )

    return immediate_hitl(
        "No safe specialist route is available for the classified requirement."
    )


def orchestrator_state_update(context: StrategySelectionContext) -> GraphState:
    """Return the state fields written by the future LangGraph orchestrator node."""

    return strategy_state_update(select_minimum_safe_strategy(context))
