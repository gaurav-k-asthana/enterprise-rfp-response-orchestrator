from collections import Counter
from copy import deepcopy

import pytest
from pydantic import ValidationError

from rfp_orchestrator.evaluation_claims import CLAIM_ASSIGNMENTS
from rfp_orchestrator.evaluation_safety import (
    ALL_REVIEW_OUTCOMES,
    BLOCKED_HITL_STATUSES,
    CONFLICT_REVIEW_OUTCOMES,
    EVIDENCE_GAP_REVIEW_OUTCOMES,
    EXPECTED_HITL_CASES,
    EXPECTED_HITL_COUNTS,
    RESOLVABLE_HITL_STATUSES,
    SAFETY_ASSIGNMENTS,
    STOP_ONLY_REVIEW_OUTCOMES,
    SafetyAssignment,
    apply_safety_labels,
    hitl_counts,
    render_safety_matrix,
    risk_counts,
    validate_safety_labels,
)
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    EXPECTED_CASE_IDS,
    EvaluationFailureCategory,
    EvaluationReviewStatus,
    ExpectedHitlBehavior,
    load_evaluation_dataset,
)
from rfp_orchestrator.models import RequirementStatus, RiskClass
from rfp_orchestrator.requirement_classification import detect_initial_risks

SAFETY_MATRIX_PATH = DEFAULT_EVALUATION_DATASET_PATH.parent / "safety_matrix_v1.md"


def test_assignments_cover_all_24_cases_in_stable_order() -> None:
    assert tuple(SAFETY_ASSIGNMENTS) == EXPECTED_CASE_IDS


def test_committed_dataset_matches_reviewed_safety_assignments() -> None:
    dataset = load_evaluation_dataset()

    validate_safety_labels(dataset)
    assert dataset == apply_safety_labels()


def test_hitl_distribution_and_required_case_set_are_frozen() -> None:
    dataset = load_evaluation_dataset()

    assert hitl_counts(dataset) == EXPECTED_HITL_COUNTS
    assert EXPECTED_HITL_COUNTS == {
        ExpectedHitlBehavior.NOT_REQUIRED: 16,
        ExpectedHitlBehavior.REQUIRED: 8,
        ExpectedHitlBehavior.CONDITIONAL: 0,
    }
    assert tuple(
        case.case_id
        for case in dataset.cases
        if case.gold_labels.expected_hitl_behavior is ExpectedHitlBehavior.REQUIRED
    ) == EXPECTED_HITL_CASES


def test_text_detected_initial_risks_are_never_omitted_from_gold() -> None:
    dataset = load_evaluation_dataset()

    for case in dataset.cases:
        assert set(detect_initial_risks(case.untrusted_rfp_text)) <= set(
            case.gold_labels.expected_risk_classes
        )


def test_dynamic_and_authority_risk_memberships_have_expected_counts() -> None:
    counts = risk_counts(load_evaluation_dataset())

    assert counts == {
        RiskClass.UNSUPPORTED_CATEGORICAL_YES: 0,
        RiskClass.ROADMAP_COMMITMENT: 1,
        RiskClass.PRICING_OR_DISCOUNT: 1,
        RiskClass.SLA_OR_SERVICE_CREDIT: 1,
        RiskClass.WARRANTY_OR_INDEMNITY: 1,
        RiskClass.SECURITY_EXCEPTION: 3,
        RiskClass.DATA_RESIDENCY_AMBIGUITY: 1,
        RiskClass.CONFLICTING_EVIDENCE: 2,
        RiskClass.SPECIALIST_DISAGREEMENT: 0,
        RiskClass.RETRY_BUDGET_EXHAUSTED: 1,
    }


def test_autonomous_cases_allow_only_finalized_and_no_human_action() -> None:
    dataset = load_evaluation_dataset()

    for case in dataset.cases:
        labels = case.gold_labels
        if labels.expected_hitl_behavior is not ExpectedHitlBehavior.NOT_REQUIRED:
            continue
        assert not labels.expected_risk_classes
        assert not labels.allowed_human_outcomes
        assert labels.allowed_final_statuses == [RequirementStatus.FINALIZED]


def test_evidence_complete_authority_cases_allow_all_review_outcomes() -> None:
    dataset = load_evaluation_dataset()
    by_id = {case.case_id: case for case in dataset.cases}

    for case_id in ("EVAL-005", "EVAL-006", "EVAL-013"):
        labels = by_id[case_id].gold_labels
        assert labels.allowed_human_outcomes == ALL_REVIEW_OUTCOMES
        assert labels.allowed_final_statuses == RESOLVABLE_HITL_STATUSES


def test_conflict_cases_disallow_approval_until_conflict_is_resolved() -> None:
    dataset = load_evaluation_dataset()
    by_id = {case.case_id: case for case in dataset.cases}

    for case_id in ("EVAL-014", "EVAL-015"):
        labels = by_id[case_id].gold_labels
        assert RiskClass.CONFLICTING_EVIDENCE in labels.expected_risk_classes
        assert labels.allowed_human_outcomes == CONFLICT_REVIEW_OUTCOMES
        assert labels.allowed_final_statuses == BLOCKED_HITL_STATUSES


def test_exhausted_fedramp_case_cannot_approve_or_retry_normally() -> None:
    case = load_evaluation_dataset().cases[20]
    labels = case.gold_labels

    assert case.requirement_id == "RFP-021"
    assert labels.expected_risk_classes == [
        RiskClass.SECURITY_EXCEPTION,
        RiskClass.RETRY_BUDGET_EXHAUSTED,
    ]
    assert labels.allowed_human_outcomes == EVIDENCE_GAP_REVIEW_OUTCOMES
    assert labels.allowed_final_statuses == BLOCKED_HITL_STATUSES


def test_preretrieval_stops_allow_only_rejection_inside_v1() -> None:
    dataset = load_evaluation_dataset()

    for case in dataset.cases[22:]:
        assert case.gold_labels.allowed_human_outcomes == STOP_ONLY_REVIEW_OUTCOMES
        assert case.gold_labels.allowed_final_statuses == BLOCKED_HITL_STATUSES


def test_every_case_has_a_primary_failure_hazard_and_rationale() -> None:
    dataset = load_evaluation_dataset()

    assert all(case.gold_labels.failure_category is not None for case in dataset.cases)
    assert all(
        case.gold_labels.rationale and case.gold_labels.rationale.strip()
        for case in dataset.cases
    )
    observed = Counter(
        case.gold_labels.failure_category for case in dataset.cases
    )
    assert observed[EvaluationFailureCategory.ROUTING_FAILURE] == 7
    assert observed[EvaluationFailureCategory.AUTHORITY_FAILURE] == 4
    assert observed[EvaluationFailureCategory.FALSE_ESCALATION] == 2
    assert observed[EvaluationFailureCategory.CONSISTENCY_FAILURE] == 2


def test_prompt_injection_has_no_business_risk_but_has_its_failure_category() -> None:
    case = load_evaluation_dataset().cases[23]

    assert not case.gold_labels.expected_risk_classes
    assert (
        case.gold_labels.failure_category
        is EvaluationFailureCategory.PROMPT_INJECTION_FAILURE
    )
    assert case.gold_labels.expected_hitl_behavior is ExpectedHitlBehavior.REQUIRED


def test_safety_labels_preserve_all_prior_gold_and_approved_review() -> None:
    dataset = load_evaluation_dataset()

    assert all(case.case_families for case in dataset.cases)
    assert all(case.gold_labels.expected_atomic_requirements for case in dataset.cases)
    assert all(case.gold_labels.expected_support_status is not None for case in dataset.cases)
    assert all(
        case.review.status is EvaluationReviewStatus.APPROVED
        for case in dataset.cases
    )
    assert tuple(CLAIM_ASSIGNMENTS) == EXPECTED_CASE_IDS


def test_checked_in_markdown_is_generated_from_validated_safety_gold() -> None:
    assert SAFETY_MATRIX_PATH.read_text(encoding="utf-8") == render_safety_matrix(
        load_evaluation_dataset()
    )


def test_validator_rejects_safety_drift() -> None:
    dataset = load_evaluation_dataset()
    payload = dataset.model_dump(mode="json")
    payload["cases"][0]["gold_labels"]["failure_category"] = "CITATION_FAILURE"
    changed = type(dataset).model_validate(payload)

    with pytest.raises(ValueError, match="failure-category drift for EVAL-001"):
        validate_safety_labels(changed)


def test_application_rejects_an_incomplete_assignment_map() -> None:
    assignments = deepcopy(SAFETY_ASSIGNMENTS)
    assignments.pop("EVAL-024")

    with pytest.raises(ValueError, match="EVAL-001 through EVAL-024"):
        apply_safety_labels(load_evaluation_dataset(), assignments)


def test_assignment_rejects_autonomous_human_outcomes() -> None:
    with pytest.raises(ValidationError, match="autonomous cases"):
        SafetyAssignment(
            hitl_behavior=ExpectedHitlBehavior.NOT_REQUIRED,
            allowed_human_outcomes=STOP_ONLY_REVIEW_OUTCOMES,
            allowed_final_statuses=[RequirementStatus.FINALIZED],
            failure_category=EvaluationFailureCategory.FALSE_ESCALATION,
            rationale="Deliberately invalid.",
        )
