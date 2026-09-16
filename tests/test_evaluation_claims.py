from copy import deepcopy

import pytest
from pydantic import ValidationError

from rfp_orchestrator.evaluation_claims import (
    CLAIM_ASSIGNMENTS,
    EXPECTED_NO_CLAIM_CASES,
    EXPECTED_SUPPORT_COUNTS,
    ClaimAssignment,
    apply_claim_labels,
    render_claim_matrix,
    support_counts,
    validate_claim_labels,
)
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    EXPECTED_CASE_IDS,
    EvaluationReviewStatus,
    ExpectedMaterialClaim,
    load_evaluation_dataset,
)
from rfp_orchestrator.models import Domain, SupportStatus
from rfp_orchestrator.requirement_analyzer import decompose_requirement

CLAIM_MATRIX_PATH = DEFAULT_EVALUATION_DATASET_PATH.parent / "claim_matrix_v1.md"


def test_assignments_cover_all_24_cases_in_stable_order() -> None:
    assert tuple(CLAIM_ASSIGNMENTS) == EXPECTED_CASE_IDS


def test_committed_dataset_matches_reviewed_claim_assignments() -> None:
    dataset = load_evaluation_dataset()

    validate_claim_labels(dataset)
    assert dataset == apply_claim_labels()


def test_gold_atomic_requirements_match_current_deterministic_decomposition() -> None:
    dataset = load_evaluation_dataset()

    for case in dataset.cases:
        assert case.gold_labels.expected_atomic_requirements == decompose_requirement(
            case.untrusted_rfp_text
        )


def test_claims_stay_with_selected_specialists_and_gold_evidence() -> None:
    dataset = load_evaluation_dataset()

    for case in dataset.cases:
        selected = set(case.gold_labels.expected_specialists)
        gold_ids = set(case.gold_labels.gold_evidence_ids)
        for claim in case.gold_labels.expected_material_claims:
            assert claim.specialist in selected
            assert set(claim.evidence_ids) <= gold_ids
            assert bool(claim.evidence_ids) is claim.supported


def test_support_distribution_is_21_supported_and_3_unsupported() -> None:
    dataset = load_evaluation_dataset()

    assert support_counts(dataset) == EXPECTED_SUPPORT_COUNTS
    assert EXPECTED_SUPPORT_COUNTS == {
        SupportStatus.SUPPORTED: 21,
        SupportStatus.PARTIAL: 0,
        SupportStatus.UNSUPPORTED: 3,
    }


def test_supported_negative_answers_remain_supported() -> None:
    dataset = load_evaluation_dataset()
    by_requirement = {case.requirement_id: case for case in dataset.cases}

    for requirement_id in ("RFP-003", "RFP-012", "RFP-013", "RFP-022"):
        case = by_requirement[requirement_id]
        assert case.gold_labels.expected_support_status is SupportStatus.SUPPORTED
        assert all(
            claim.supported for claim in case.gold_labels.expected_material_claims
        )


def test_conflicting_retention_claims_are_individually_supported() -> None:
    case = load_evaluation_dataset().cases[13]

    assert case.requirement_id == "RFP-014"
    assert case.gold_labels.expected_support_status is SupportStatus.SUPPORTED
    assert [claim.supported for claim in case.gold_labels.expected_material_claims] == [
        True,
        True,
    ]
    assert {
        evidence_id
        for claim in case.gold_labels.expected_material_claims
        for evidence_id in claim.evidence_ids
    } == {
        "SEC-RET-001::chunk-001",
        "SEC-RET-OPS-001::chunk-001",
    }


def test_only_missing_evidence_or_preretrieval_cases_are_unsupported() -> None:
    dataset = load_evaluation_dataset()

    assert [
        case.requirement_id
        for case in dataset.cases
        if case.gold_labels.expected_support_status is SupportStatus.UNSUPPORTED
    ] == ["RFP-021", "RFP-023", "RFP-024"]
    assert tuple(
        case.case_id
        for case in dataset.cases
        if not case.gold_labels.expected_material_claims
    ) == EXPECTED_NO_CLAIM_CASES


def test_claim_labels_preserve_step_4_6_and_approved_review_fields() -> None:
    dataset = load_evaluation_dataset()

    assert all(case.gold_labels.expected_hitl_behavior is not None for case in dataset.cases)
    assert all(case.gold_labels.allowed_final_statuses for case in dataset.cases)
    assert sum(bool(case.gold_labels.allowed_human_outcomes) for case in dataset.cases) == 8
    assert all(case.gold_labels.failure_category is not None for case in dataset.cases)
    assert all(case.gold_labels.rationale for case in dataset.cases)
    assert all(
        case.review.status is EvaluationReviewStatus.APPROVED
        for case in dataset.cases
    )


def test_checked_in_markdown_is_generated_from_validated_claim_gold() -> None:
    assert CLAIM_MATRIX_PATH.read_text(encoding="utf-8") == render_claim_matrix(
        load_evaluation_dataset()
    )


def test_validator_rejects_claim_drift() -> None:
    dataset = load_evaluation_dataset()
    payload = dataset.model_dump(mode="json")
    payload["cases"][0]["gold_labels"]["expected_material_claims"][0][
        "text"
    ] = "Changed claim."
    changed = type(dataset).model_validate(payload)

    with pytest.raises(ValueError, match="material-claim drift for EVAL-001"):
        validate_claim_labels(changed)


def test_application_rejects_an_incomplete_assignment_map() -> None:
    assignments = deepcopy(CLAIM_ASSIGNMENTS)
    assignments.pop("EVAL-024")

    with pytest.raises(ValueError, match="EVAL-001 through EVAL-024"):
        apply_claim_labels(load_evaluation_dataset(), assignments)


def test_assignment_rejects_incorrect_aggregate_status() -> None:
    with pytest.raises(ValidationError, match="aggregate from material claim"):
        ClaimAssignment(
            atomic_requirements=["Evaluate one claim."],
            material_claims=[
                ExpectedMaterialClaim(
                    specialist=Domain.PRODUCT,
                    claim_id="claim-1",
                    text="One unsupported claim.",
                    supported=False,
                )
            ],
            support_status=SupportStatus.SUPPORTED,
            claim_reason="Deliberately invalid.",
        )
