from copy import deepcopy

import pytest
from pydantic import ValidationError

from rfp_orchestrator.evaluation_routing import (
    EXPECTED_DOMAIN_COUNTS,
    EXPECTED_STRATEGY_COUNTS,
    ROUTING_ASSIGNMENTS,
    RoutingAssignment,
    apply_routing_labels,
    domain_counts,
    render_routing_matrix,
    strategy_counts,
    validate_routing_labels,
)
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    EXPECTED_CASE_IDS,
    EvaluationReviewStatus,
    load_evaluation_dataset,
)
from rfp_orchestrator.models import Domain, StrategyType

ROUTING_MATRIX_PATH = DEFAULT_EVALUATION_DATASET_PATH.parent / "routing_matrix_v1.md"


def test_assignments_cover_all_24_cases_in_stable_order() -> None:
    assert tuple(ROUTING_ASSIGNMENTS) == EXPECTED_CASE_IDS


def test_committed_dataset_matches_reviewed_routing_assignments() -> None:
    dataset = load_evaluation_dataset()

    validate_routing_labels(dataset)
    assert dataset == apply_routing_labels()


def test_strategy_and_domain_distributions_match_reviewed_counts() -> None:
    dataset = load_evaluation_dataset()

    assert strategy_counts(dataset) == EXPECTED_STRATEGY_COUNTS
    assert domain_counts(dataset) == EXPECTED_DOMAIN_COUNTS


def test_routing_labels_preserve_coverage_and_newer_claim_gold() -> None:
    dataset = load_evaluation_dataset()

    assert all(case.case_families for case in dataset.cases)
    assert all(case.gold_labels.expected_atomic_requirements for case in dataset.cases)
    assert sum(bool(case.gold_labels.expected_material_claims) for case in dataset.cases) == 22
    assert all(case.gold_labels.expected_support_status is not None for case in dataset.cases)
    assert all(case.gold_labels.expected_hitl_behavior is not None for case in dataset.cases)
    assert all(case.gold_labels.allowed_final_statuses for case in dataset.cases)
    assert sum(bool(case.gold_labels.allowed_human_outcomes) for case in dataset.cases) == 8
    assert all(case.gold_labels.failure_category is not None for case in dataset.cases)
    assert all(case.gold_labels.rationale for case in dataset.cases)
    assert all(
        case.review.status is EvaluationReviewStatus.APPROVED
        for case in dataset.cases
    )


def test_initial_strategy_counts_are_18_single_4_parallel_and_2_hitl() -> None:
    assert EXPECTED_STRATEGY_COUNTS == {
        StrategyType.SINGLE_SPECIALIST: 18,
        StrategyType.PARALLEL_SPECIALISTS: 4,
        StrategyType.IMMEDIATE_HITL: 2,
    }


def test_immediate_hitl_cases_select_no_specialist() -> None:
    hitl_cases = [
        case
        for case in load_evaluation_dataset().cases
        if case.gold_labels.expected_strategy_family is StrategyType.IMMEDIATE_HITL
    ]

    assert [case.requirement_id for case in hitl_cases] == ["RFP-023", "RFP-024"]
    assert all(not case.gold_labels.expected_domains for case in hitl_cases)
    assert all(not case.gold_labels.expected_specialists for case in hitl_cases)


def test_parallel_routes_select_all_expected_peers_in_canonical_order() -> None:
    parallel_cases = [
        case
        for case in load_evaluation_dataset().cases
        if case.gold_labels.expected_strategy_family
        is StrategyType.PARALLEL_SPECIALISTS
    ]

    assert [case.requirement_id for case in parallel_cases] == [
        "RFP-002",
        "RFP-011",
        "RFP-012",
        "RFP-020",
    ]
    assert all(
        case.gold_labels.expected_domains == [Domain.PRODUCT, Domain.SECURITY]
        for case in parallel_cases
    )
    assert all(
        case.gold_labels.expected_specialists == case.gold_labels.expected_domains
        for case in parallel_cases
    )


def test_assignment_rejects_noninitial_strategy_and_bad_peer_selection() -> None:
    with pytest.raises(ValidationError, match="initial strategy"):
        RoutingAssignment(
            expected_domains=[Domain.SECURITY],
            initial_strategy=StrategyType.RETRIEVAL_RECOVERY,
            selected_specialists=[Domain.SECURITY],
            routing_reason="Later transition, not an initial route.",
        )

    with pytest.raises(ValidationError, match="select all expected peer specialists"):
        RoutingAssignment(
            expected_domains=[Domain.PRODUCT, Domain.SECURITY],
            initial_strategy=StrategyType.PARALLEL_SPECIALISTS,
            selected_specialists=[Domain.PRODUCT],
            routing_reason="Missing selected peer.",
        )


def test_validator_rejects_routing_drift() -> None:
    dataset = load_evaluation_dataset()
    payload = dataset.model_dump(mode="json")
    labels = payload["cases"][1]["gold_labels"]
    labels["expected_domains"].reverse()
    labels["expected_specialists"].reverse()
    changed = type(dataset).model_validate(payload)

    with pytest.raises(ValueError, match="expected-domain drift for EVAL-002"):
        validate_routing_labels(changed)


def test_checked_in_markdown_is_generated_from_validated_routing_gold() -> None:
    assert ROUTING_MATRIX_PATH.read_text(encoding="utf-8") == render_routing_matrix(
        load_evaluation_dataset()
    )


def test_application_rejects_an_incomplete_assignment_map() -> None:
    assignments = deepcopy(ROUTING_ASSIGNMENTS)
    assignments.pop("EVAL-024")

    with pytest.raises(ValueError, match="EVAL-001 through EVAL-024"):
        apply_routing_labels(load_evaluation_dataset(), assignments)
