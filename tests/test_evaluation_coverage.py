from copy import deepcopy

import pytest
from pydantic import ValidationError

from rfp_orchestrator.evaluation_coverage import (
    COVERAGE_ASSIGNMENTS,
    EXPECTED_FAMILY_COUNTS,
    MINIMUM_FAMILY_COUNTS,
    CoverageAssignment,
    apply_coverage_matrix,
    family_counts,
    render_coverage_matrix,
    validate_coverage_matrix,
)
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    EXPECTED_CASE_IDS,
    EvaluationCaseFamily,
    EvaluationReviewStatus,
    build_evaluation_skeleton,
    load_evaluation_dataset,
)

COVERAGE_MATRIX_PATH = (
    DEFAULT_EVALUATION_DATASET_PATH.parent / "coverage_matrix_v1.md"
)


def test_assignments_cover_all_24_cases_in_stable_order() -> None:
    assert tuple(COVERAGE_ASSIGNMENTS) == EXPECTED_CASE_IDS
    assert all(assignment.families for assignment in COVERAGE_ASSIGNMENTS.values())
    assert all(
        assignment.coverage_reason.strip()
        for assignment in COVERAGE_ASSIGNMENTS.values()
    )


def test_committed_dataset_matches_reviewed_coverage_assignments() -> None:
    dataset = load_evaluation_dataset()

    validate_coverage_matrix(dataset)
    assert dataset == apply_coverage_matrix()


def test_family_distribution_matches_reviewed_counts_and_minimums() -> None:
    counts = family_counts(load_evaluation_dataset())

    assert counts == EXPECTED_FAMILY_COUNTS
    assert all(
        counts[family] >= minimum
        for family, minimum in MINIMUM_FAMILY_COUNTS.items()
    )


def test_simple_is_exclusive_and_challenges_are_the_majority() -> None:
    dataset = load_evaluation_dataset()
    simple = EvaluationCaseFamily.SIMPLE

    assert all(
        len(case.case_families) == 1
        for case in dataset.cases
        if simple in case.case_families
    )
    assert sum(simple not in case.case_families for case in dataset.cases) == 14


def test_coverage_remains_stable_after_claim_labels_are_added() -> None:
    dataset = load_evaluation_dataset()

    assert all(case.case_families for case in dataset.cases)
    assert all(case.gold_labels.expected_atomic_requirements for case in dataset.cases)
    assert sum(bool(case.gold_labels.expected_material_claims) for case in dataset.cases) == 22
    assert all(case.gold_labels.expected_support_status is not None for case in dataset.cases)
    assert all(case.gold_labels.expected_hitl_behavior is not None for case in dataset.cases)
    assert all(case.gold_labels.allowed_final_statuses for case in dataset.cases)
    assert all(case.gold_labels.rationale for case in dataset.cases)
    assert all(
        case.review.status is EvaluationReviewStatus.APPROVED
        for case in dataset.cases
    )


def test_checked_in_markdown_is_generated_from_the_validated_dataset() -> None:
    assert COVERAGE_MATRIX_PATH.read_text(encoding="utf-8") == render_coverage_matrix(
        load_evaluation_dataset()
    )


def test_assignment_rejects_simple_mixed_with_a_challenge_family() -> None:
    with pytest.raises(ValidationError, match="SIMPLE is exclusive"):
        CoverageAssignment(
            families=[
                EvaluationCaseFamily.SIMPLE,
                EvaluationCaseFamily.WEAK_EVIDENCE,
            ],
            coverage_reason="Invalid overlap.",
        )


def test_validator_rejects_assignment_drift() -> None:
    dataset = load_evaluation_dataset()
    payload = dataset.model_dump(mode="json")
    payload["cases"][0]["case_families"] = ["WEAK_EVIDENCE"]
    changed = type(dataset).model_validate(payload)

    with pytest.raises(ValueError, match="coverage assignment drift for EVAL-001"):
        validate_coverage_matrix(changed)


def test_application_rejects_an_incomplete_assignment_map() -> None:
    assignments = deepcopy(COVERAGE_ASSIGNMENTS)
    assignments.pop("EVAL-024")

    with pytest.raises(ValueError, match="EVAL-001 through EVAL-024"):
        apply_coverage_matrix(build_evaluation_skeleton(), assignments)
