import json
from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from rfp_orchestrator.corpus import SourceStatus
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    EXPECTED_CASE_IDS,
    EvaluationCase,
    EvaluationCaseFamily,
    EvaluationDataset,
    EvaluationDatasetStatus,
    EvaluationFailureCategory,
    EvaluationGoldLabels,
    EvaluationReview,
    EvaluationReviewStatus,
    ExpectedAuthorityTier,
    ExpectedHitlBehavior,
    ExpectedMaterialClaim,
    build_evaluation_skeleton,
    load_evaluation_dataset,
)
from rfp_orchestrator.models import (
    ApprovalDecision,
    Domain,
    RequirementStatus,
    RiskClass,
    StrategyType,
    SupportStatus,
)
from rfp_orchestrator.sample_requirements import (
    EXPECTED_REQUIREMENT_IDS,
    load_sample_requirements,
)


def _dataset_payload() -> dict[str, object]:
    return json.loads(DEFAULT_EVALUATION_DATASET_PATH.read_text(encoding="utf-8"))


def _first_case_payload() -> dict[str, object]:
    return deepcopy(_dataset_payload()["cases"][0])


def test_committed_dataset_has_exactly_24_ordered_cases() -> None:
    dataset = load_evaluation_dataset()

    assert len(dataset.cases) == 24
    assert tuple(case.case_id for case in dataset.cases) == EXPECTED_CASE_IDS
    assert tuple(case.requirement_id for case in dataset.cases) == EXPECTED_REQUIREMENT_IDS


def test_dataset_text_matches_every_canonical_sample_requirement() -> None:
    dataset = load_evaluation_dataset()
    requirements = load_sample_requirements()

    assert [case.untrusted_rfp_text for case in dataset.cases] == [
        requirement.text for requirement in requirements
    ]


def test_committed_dataset_preserves_claim_gold_and_later_unlabeled_fields() -> None:
    dataset = load_evaluation_dataset()
    skeleton = build_evaluation_skeleton()

    assert [case.case_id for case in dataset.cases] == [
        case.case_id for case in skeleton.cases
    ]
    assert all(case.case_families for case in dataset.cases)
    assert all(
        case.gold_labels.expected_strategy_family is not None
        for case in dataset.cases
    )
    assert all(case.gold_labels.expected_atomic_requirements for case in dataset.cases)
    assert sum(bool(case.gold_labels.expected_material_claims) for case in dataset.cases) == 22
    assert all(case.gold_labels.expected_support_status is not None for case in dataset.cases)
    assert all(case.gold_labels.expected_hitl_behavior is not None for case in dataset.cases)
    assert all(case.gold_labels.allowed_final_statuses for case in dataset.cases)
    assert sum(bool(case.gold_labels.allowed_human_outcomes) for case in dataset.cases) == 8
    assert all(case.gold_labels.failure_category is not None for case in dataset.cases)
    assert all(case.gold_labels.rationale for case in dataset.cases)
    assert dataset.status is EvaluationDatasetStatus.FROZEN
    assert all(
        case.review.status is EvaluationReviewStatus.APPROVED
        and case.review.reviewer == "Gaurav Asthana"
        for case in dataset.cases
    )


def test_skeleton_serializes_every_future_gold_field() -> None:
    payload = build_evaluation_skeleton().model_dump(mode="json")
    labels = payload["cases"][0]["gold_labels"]

    assert set(labels) == {
        "expected_atomic_requirements",
        "expected_domains",
        "expected_strategy_family",
        "expected_specialists",
        "gold_evidence_ids",
        "expected_authority_order",
        "expected_material_claims",
        "expected_support_status",
        "expected_risk_classes",
        "expected_hitl_behavior",
        "allowed_human_outcomes",
        "allowed_final_statuses",
        "failure_category",
        "rationale",
    }


def test_case_family_and_failure_taxonomies_are_stable() -> None:
    assert [item.value for item in EvaluationCaseFamily] == [
        "SIMPLE",
        "CROSS_DOMAIN",
        "WEAK_EVIDENCE",
        "CONFLICT",
        "AUTHORITY_RISK",
        "ADVERSARIAL",
    ]
    assert len(EvaluationFailureCategory) == 13
    assert {item.value for item in ExpectedHitlBehavior} == {
        "NOT_REQUIRED",
        "REQUIRED",
        "CONDITIONAL",
    }


def test_schema_rejects_unknown_fields() -> None:
    payload = _dataset_payload()
    payload["unexpected"] = "silent schema drift"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        EvaluationDataset.model_validate(payload)


def test_schema_rejects_a_missing_case() -> None:
    payload = _dataset_payload()
    payload["cases"].pop()

    with pytest.raises(ValidationError, match="at least 24"):
        EvaluationDataset.model_validate(payload)


def test_schema_rejects_swapped_or_duplicate_case_identity() -> None:
    payload = _dataset_payload()
    payload["cases"][0]["case_id"] = "EVAL-002"
    payload["cases"][0]["requirement_id"] = "RFP-002"

    with pytest.raises(ValidationError, match="ordered cases"):
        EvaluationDataset.model_validate(payload)


def test_case_numeric_identity_must_match_requirement() -> None:
    payload = _first_case_payload()
    payload["case_id"] = "EVAL-002"

    with pytest.raises(ValidationError, match="numeric IDs must match"):
        EvaluationCase.model_validate(payload)


def test_loader_rejects_text_drift_from_sample_rfp(tmp_path) -> None:
    payload = _dataset_payload()
    payload["cases"][0]["untrusted_rfp_text"] = "Changed after review."
    changed_path = tmp_path / "changed.json"
    changed_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="does not match sample RFP for RFP-001"):
        load_evaluation_dataset(changed_path)


def test_gold_labels_reject_duplicate_values() -> None:
    with pytest.raises(ValidationError, match="expected domains cannot contain duplicates"):
        EvaluationGoldLabels(expected_domains=[Domain.PRODUCT, Domain.PRODUCT])


def test_expected_specialists_must_be_expected_domains() -> None:
    with pytest.raises(ValidationError, match="subset of expected domains"):
        EvaluationGoldLabels(
            expected_domains=[Domain.PRODUCT],
            expected_specialists=[Domain.SECURITY],
        )


@pytest.mark.parametrize(
    ("claim_flags", "expected"),
    [
        ([True, True], SupportStatus.SUPPORTED),
        ([True, False], SupportStatus.PARTIAL),
        ([False, False], SupportStatus.UNSUPPORTED),
    ],
)
def test_claim_booleans_require_the_correct_aggregate_support_status(
    claim_flags: list[bool],
    expected: SupportStatus,
) -> None:
    claims = [
        ExpectedMaterialClaim(
            specialist=Domain.PRODUCT,
            claim_id=f"claim-{index}",
            text=f"Material claim {index}",
            supported=supported,
            evidence_ids=[f"EVID-{index}"] if supported else [],
        )
        for index, supported in enumerate(claim_flags, start=1)
    ]
    evidence_ids = [
        evidence_id for claim in claims for evidence_id in claim.evidence_ids
    ]
    authority_order = (
        [
            ExpectedAuthorityTier(
                source_status=SourceStatus.CURRENT,
                authority_rank=5,
                evidence_ids=evidence_ids,
            )
        ]
        if evidence_ids
        else []
    )

    labels = EvaluationGoldLabels(
        expected_atomic_requirements=["Evaluate the material claims."],
        expected_domains=[Domain.PRODUCT],
        expected_strategy_family=StrategyType.SINGLE_SPECIALIST,
        expected_specialists=[Domain.PRODUCT],
        gold_evidence_ids=evidence_ids,
        expected_authority_order=authority_order,
        expected_material_claims=claims,
        expected_support_status=expected,
    )
    assert labels.expected_support_status is expected

    wrong_status = next(status for status in SupportStatus if status is not expected)
    with pytest.raises(ValidationError, match="aggregate from claim.supported"):
        EvaluationGoldLabels(
            expected_atomic_requirements=["Evaluate the material claims."],
            expected_domains=[Domain.PRODUCT],
            expected_strategy_family=StrategyType.SINGLE_SPECIALIST,
            expected_specialists=[Domain.PRODUCT],
            gold_evidence_ids=evidence_ids,
            expected_authority_order=authority_order,
            expected_material_claims=claims,
            expected_support_status=wrong_status,
        )


def test_empty_claim_set_can_label_a_preretrieval_stop_as_unsupported() -> None:
    labels = EvaluationGoldLabels(
        expected_atomic_requirements=["Stop before specialist work."],
        expected_strategy_family=StrategyType.IMMEDIATE_HITL,
        expected_support_status=SupportStatus.UNSUPPORTED,
    )

    assert not labels.expected_material_claims
    assert labels.expected_support_status is SupportStatus.UNSUPPORTED


def test_supported_claim_requires_selected_specialist_and_gold_evidence() -> None:
    with pytest.raises(ValidationError, match="selected specialist"):
        EvaluationGoldLabels(
            expected_atomic_requirements=["Evaluate one claim."],
            expected_material_claims=[
                ExpectedMaterialClaim(
                    specialist=Domain.SECURITY,
                    claim_id="claim-1",
                    text="One claim.",
                    supported=False,
                )
            ],
            expected_support_status=SupportStatus.UNSUPPORTED,
        )

    with pytest.raises(ValidationError, match="requires gold evidence"):
        EvaluationGoldLabels(
            expected_atomic_requirements=["Evaluate one claim."],
            expected_domains=[Domain.PRODUCT],
            expected_strategy_family=StrategyType.SINGLE_SPECIALIST,
            expected_specialists=[Domain.PRODUCT],
            expected_material_claims=[
                ExpectedMaterialClaim(
                    specialist=Domain.PRODUCT,
                    claim_id="claim-1",
                    text="One claim.",
                    supported=True,
                )
            ],
            expected_support_status=SupportStatus.SUPPORTED,
        )


def test_not_required_hitl_cannot_have_risks_or_human_outcomes() -> None:
    with pytest.raises(ValidationError, match="NOT_REQUIRED HITL"):
        EvaluationGoldLabels(
            expected_risk_classes=[RiskClass.SECURITY_EXCEPTION],
            expected_hitl_behavior=ExpectedHitlBehavior.NOT_REQUIRED,
            allowed_final_statuses=[RequirementStatus.FINALIZED],
            failure_category=EvaluationFailureCategory.FALSE_ESCALATION,
            rationale="Deliberately invalid.",
        )


def test_required_hitl_needs_human_outcomes_and_needs_human_status() -> None:
    with pytest.raises(ValidationError, match="human outcomes"):
        EvaluationGoldLabels(
            expected_hitl_behavior=ExpectedHitlBehavior.REQUIRED,
            allowed_final_statuses=[RequirementStatus.NEEDS_HUMAN],
            failure_category=EvaluationFailureCategory.AUTHORITY_FAILURE,
            rationale="Deliberately incomplete.",
        )


def test_reject_and_approval_outcomes_require_matching_final_statuses() -> None:
    with pytest.raises(ValidationError, match="REJECTED final status"):
        EvaluationGoldLabels(
            expected_hitl_behavior=ExpectedHitlBehavior.REQUIRED,
            allowed_human_outcomes=[ApprovalDecision.REJECT],
            allowed_final_statuses=[RequirementStatus.NEEDS_HUMAN],
            failure_category=EvaluationFailureCategory.AUTHORITY_FAILURE,
            rationale="Deliberately missing rejected status.",
        )

    with pytest.raises(ValidationError, match="FINALIZED to be allowed"):
        EvaluationGoldLabels(
            expected_hitl_behavior=ExpectedHitlBehavior.REQUIRED,
            allowed_human_outcomes=[ApprovalDecision.APPROVE],
            allowed_final_statuses=[RequirementStatus.NEEDS_HUMAN],
            failure_category=EvaluationFailureCategory.AUTHORITY_FAILURE,
            rationale="Deliberately missing finalized status.",
        )


def test_immediate_hitl_strategy_requires_required_hitl_behavior() -> None:
    with pytest.raises(ValidationError, match="IMMEDIATE_HITL requires"):
        EvaluationGoldLabels(
            expected_strategy_family=StrategyType.IMMEDIATE_HITL,
            expected_hitl_behavior=ExpectedHitlBehavior.NOT_REQUIRED,
            allowed_final_statuses=[RequirementStatus.FINALIZED],
            failure_category=EvaluationFailureCategory.PROMPT_INJECTION_FAILURE,
            rationale="Deliberately invalid.",
        )


def test_draft_review_cannot_claim_review_provenance() -> None:
    with pytest.raises(ValidationError, match="draft evaluation cases"):
        EvaluationReview(
            reviewer="Synthetic reviewer",
            reviewed_at=datetime.now(timezone.utc),
        )


def test_reviewed_status_requires_reviewer_and_timestamp() -> None:
    with pytest.raises(ValidationError, match="require reviewer and timestamp"):
        EvaluationReview(status=EvaluationReviewStatus.APPROVED)

    review = EvaluationReview(
        status=EvaluationReviewStatus.READY_FOR_REVIEW,
        reviewer="Synthetic reviewer",
        reviewed_at=datetime.now(timezone.utc),
    )
    assert review.status is EvaluationReviewStatus.READY_FOR_REVIEW


def test_validated_dataset_is_not_changed_by_later_payload_mutation() -> None:
    payload = _dataset_payload()
    dataset = EvaluationDataset.model_validate(payload)

    payload["cases"][0]["untrusted_rfp_text"] = "mutated source dictionary"

    assert dataset.cases[0].untrusted_rfp_text != "mutated source dictionary"
