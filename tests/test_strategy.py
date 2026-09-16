import pytest
from pydantic import ValidationError

from rfp_orchestrator.models import Domain, StrategyDecision, StrategyType
from rfp_orchestrator.state import new_requirement_state
from rfp_orchestrator.strategy import (
    finalize,
    immediate_hitl,
    parallel_specialists,
    retrieval_recovery,
    single_specialist,
    strategy_state_update,
    targeted_conflict_resolution,
)


def test_single_specialist_output_selects_exactly_one_peer() -> None:
    decision = single_specialist(Domain.PRODUCT, "Only Product evidence is needed.")

    assert decision.strategy is StrategyType.SINGLE_SPECIALIST
    assert decision.selected_specialists == [Domain.PRODUCT]


def test_parallel_output_selects_two_or_three_unique_peers() -> None:
    decision = parallel_specialists(
        [Domain.PRODUCT, Domain.SECURITY],
        "Product availability and Security controls are both required.",
    )

    assert decision.strategy is StrategyType.PARALLEL_SPECIALISTS
    assert decision.selected_specialists == [Domain.PRODUCT, Domain.SECURITY]


def test_recovery_output_requires_failure_context_and_target_peers() -> None:
    decision = retrieval_recovery(
        [Domain.SECURITY],
        "The first retrieval returned no applicable current evidence.",
        "Retry Security retrieval with recorded failure context.",
    )

    assert decision.strategy is StrategyType.RETRIEVAL_RECOVERY
    assert decision.recovery_context.startswith("The first retrieval")


def test_conflict_output_requires_conflict_ids_and_target_peers() -> None:
    decision = targeted_conflict_resolution(
        [Domain.SECURITY],
        ["retention-30-vs-90"],
        "Reanalyze the conflicting retention values without hiding either source.",
    )

    assert decision.strategy is StrategyType.TARGETED_CONFLICT_RESOLUTION
    assert decision.target_conflict_ids == ["retention-30-vs-90"]


def test_immediate_hitl_and_finalize_are_terminal_outputs() -> None:
    hitl = immediate_hitl("Pricing and indemnity require organizational authority.")
    completed = finalize("All deterministic finalization guards passed.")

    assert hitl.strategy is StrategyType.IMMEDIATE_HITL
    assert completed.strategy is StrategyType.FINALIZE
    assert hitl.selected_specialists == completed.selected_specialists == []


@pytest.mark.parametrize(
    ("strategy", "specialists"),
    [
        (StrategyType.SINGLE_SPECIALIST, []),
        (StrategyType.SINGLE_SPECIALIST, [Domain.PRODUCT, Domain.SECURITY]),
        (StrategyType.PARALLEL_SPECIALISTS, [Domain.PRODUCT]),
        (
            StrategyType.PARALLEL_SPECIALISTS,
            [Domain.PRODUCT, Domain.PRODUCT],
        ),
    ],
)
def test_specialist_route_cardinality_is_validated(
    strategy: StrategyType, specialists: list[Domain]
) -> None:
    with pytest.raises(ValidationError):
        StrategyDecision(
            strategy=strategy,
            selected_specialists=specialists,
            rationale="Invalid specialist selection.",
        )


def test_recovery_rejects_missing_or_misplaced_context() -> None:
    with pytest.raises(ValidationError, match="requires recovery_context"):
        StrategyDecision(
            strategy=StrategyType.RETRIEVAL_RECOVERY,
            selected_specialists=[Domain.SECURITY],
            rationale="Retry retrieval.",
        )
    with pytest.raises(ValidationError, match="valid only for RETRIEVAL_RECOVERY"):
        StrategyDecision(
            strategy=StrategyType.FINALIZE,
            rationale="Finish.",
            recovery_context="This context is misplaced.",
        )


def test_conflict_resolution_rejects_missing_or_misplaced_conflict_ids() -> None:
    with pytest.raises(ValidationError, match="requires target_conflict_ids"):
        StrategyDecision(
            strategy=StrategyType.TARGETED_CONFLICT_RESOLUTION,
            selected_specialists=[Domain.SECURITY],
            rationale="Resolve the conflict.",
        )
    with pytest.raises(ValidationError, match="valid only"):
        StrategyDecision(
            strategy=StrategyType.FINALIZE,
            rationale="Finish.",
            target_conflict_ids=["conflict-1"],
        )


def test_terminal_routes_reject_specialist_selection() -> None:
    with pytest.raises(ValidationError, match="cannot select specialists"):
        StrategyDecision(
            strategy=StrategyType.IMMEDIATE_HITL,
            selected_specialists=[Domain.PRODUCT],
            rationale="Escalate.",
        )


def test_duplicate_specialists_conflicts_and_blank_rationale_are_rejected() -> None:
    with pytest.raises(ValidationError, match="cannot contain duplicates"):
        StrategyDecision(
            strategy=StrategyType.RETRIEVAL_RECOVERY,
            selected_specialists=[Domain.SECURITY, Domain.SECURITY],
            rationale="Retry.",
            recovery_context="Weak evidence.",
        )
    with pytest.raises(ValidationError, match="cannot contain duplicates"):
        StrategyDecision(
            strategy=StrategyType.TARGETED_CONFLICT_RESOLUTION,
            selected_specialists=[Domain.SECURITY],
            rationale="Resolve.",
            target_conflict_ids=["conflict-1", "conflict-1"],
        )
    with pytest.raises(ValidationError, match="cannot be blank"):
        StrategyDecision(strategy=StrategyType.FINALIZE, rationale="   ")


def test_strategy_state_update_is_explicit_and_serializable() -> None:
    decision = parallel_specialists(
        [Domain.PRODUCT, Domain.SECURITY],
        "Both peer domains are required.",
    )

    update = strategy_state_update(decision)

    assert update == {
        "strategy": "PARALLEL_SPECIALISTS",
        "selected_specialists": ["product", "security"],
        "strategy_rationale": "Both peer domains are required.",
        "recovery_context": None,
        "target_conflict_ids": [],
    }


def test_new_graph_state_has_no_strategy_before_orchestration() -> None:
    state = new_requirement_state("case-1", "RFP-001", "Confirm SAML support.")

    assert state["strategy"] is None
    assert state["selected_specialists"] == []
    assert state["strategy_rationale"] is None
    assert state["recovery_context"] is None
    assert state["target_conflict_ids"] == []
