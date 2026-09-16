from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from rfp_orchestrator.evaluation_freeze import (
    DEFAULT_REVIEW_PACKET_PATH,
    build_freeze_manifest,
    freeze_gold_dataset,
    gold_content_sha256,
    render_gold_review_packet,
    validate_frozen_gold,
    validate_gold_readiness,
)
from rfp_orchestrator.evaluation_schema import (
    EvaluationDataset,
    EvaluationDatasetStatus,
    EvaluationReview,
    EvaluationReviewStatus,
    load_evaluation_dataset,
)


def _draft_dataset() -> EvaluationDataset:
    payload = load_evaluation_dataset().model_dump(mode="json")
    payload["status"] = EvaluationDatasetStatus.DRAFT.value
    for case in payload["cases"]:
        case["review"] = EvaluationReview().model_dump(mode="json")
    return EvaluationDataset.model_validate(payload)


def test_committed_dataset_is_complete_approved_and_frozen() -> None:
    dataset = load_evaluation_dataset()

    validate_gold_readiness(dataset)
    validate_frozen_gold(dataset)
    assert dataset.status is EvaluationDatasetStatus.FROZEN
    assert all(
        case.review.status is EvaluationReviewStatus.APPROVED
        and case.review.reviewer == "Gaurav Asthana"
        for case in dataset.cases
    )


def test_review_packet_is_generated_from_the_validated_frozen_release() -> None:
    rendered = render_gold_review_packet(load_evaluation_dataset())

    assert "APPROVED and FROZEN by Gaurav Asthana" in rendered
    assert "RFP-006 currently exhausts deterministic retrieval" in rendered
    assert rendered.count(" / RFP-") == 24
    assert "Approved cases: **24/24**" in rendered
    assert DEFAULT_REVIEW_PACKET_PATH.read_text(encoding="utf-8") == rendered


def test_freeze_adds_one_approval_event_without_changing_gold() -> None:
    draft = _draft_dataset()
    before = gold_content_sha256(draft)
    reviewed_at = datetime(2026, 9, 3, 18, 0, tzinfo=timezone.utc)

    frozen = freeze_gold_dataset(
        draft,
        reviewer="Synthetic reviewer",
        reviewed_at=reviewed_at,
        notes="Approved in a test fixture.",
    )

    validate_frozen_gold(frozen)
    assert frozen.status is EvaluationDatasetStatus.FROZEN
    assert gold_content_sha256(frozen) == before
    assert all(
        case.review.status is EvaluationReviewStatus.APPROVED
        and case.review.reviewer == "Synthetic reviewer"
        and case.review.reviewed_at == reviewed_at
        for case in frozen.cases
    )
    assert draft.status is EvaluationDatasetStatus.DRAFT

    approved_packet = render_gold_review_packet(
        frozen,
        dataset_file_digest="f" * 64,
    )
    assert "APPROVED and FROZEN by Synthetic reviewer" in approved_packet
    assert "Approved cases: **24/24**" in approved_packet


def test_freeze_requires_named_reviewer_and_timezone() -> None:
    dataset = _draft_dataset()

    with pytest.raises(ValueError, match="reviewer cannot be blank"):
        freeze_gold_dataset(
            dataset,
            reviewer=" ",
            reviewed_at=datetime.now(timezone.utc),
        )
    with pytest.raises(ValueError, match="include a timezone"):
        freeze_gold_dataset(
            dataset,
            reviewer="Synthetic reviewer",
            reviewed_at=datetime(2026, 9, 3, 18, 0, tzinfo=timezone.utc).replace(
                tzinfo=None
            ),
        )


def test_dataset_status_and_case_review_status_cannot_disagree() -> None:
    payload = _draft_dataset().model_dump(mode="json")
    payload["status"] = EvaluationDatasetStatus.FROZEN.value

    with pytest.raises(ValidationError, match="requires every case review to be APPROVED"):
        EvaluationDataset.model_validate(payload)


def test_frozen_validator_rejects_gold_label_drift() -> None:
    frozen = freeze_gold_dataset(
        _draft_dataset(),
        reviewer="Synthetic reviewer",
        reviewed_at=datetime(2026, 9, 3, 18, 0, tzinfo=timezone.utc),
    )
    payload = frozen.model_dump(mode="json")
    payload["cases"][0]["gold_labels"]["rationale"] = "Changed after review."
    changed = EvaluationDataset.model_validate(payload)

    with pytest.raises(ValueError, match="rationale drift for EVAL-001"):
        validate_frozen_gold(changed)


def test_freeze_manifest_records_provenance_and_content_identity() -> None:
    frozen = freeze_gold_dataset(
        _draft_dataset(),
        reviewer="Synthetic reviewer",
        reviewed_at=datetime(2026, 9, 3, 18, 0, tzinfo=timezone.utc),
    )

    manifest = build_freeze_manifest(
        frozen,
        draft_dataset_digest="a" * 64,
        frozen_dataset_digest="b" * 64,
        review_packet_digest="c" * 64,
    )

    assert manifest["dataset_status"] == "FROZEN"
    assert manifest["case_count"] == 24
    assert manifest["review"]["reviewer"] == "Synthetic reviewer"
    assert manifest["gold_content_sha256"] == gold_content_sha256(frozen)
    assert len(manifest["matrix_sha256"]) == 5
