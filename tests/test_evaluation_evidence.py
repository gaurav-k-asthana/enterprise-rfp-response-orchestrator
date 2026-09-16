from copy import deepcopy

import pytest
from pydantic import ValidationError

from rfp_orchestrator.corpus import SourceStatus, load_corpus_chunks
from rfp_orchestrator.evaluation_evidence import (
    EVIDENCE_ASSIGNMENTS,
    EXPECTED_EMPTY_EVIDENCE_CASES,
    KB_DIRECTORY,
    EvidenceAssignment,
    apply_evidence_labels,
    render_evidence_matrix,
    validate_evidence_labels,
)
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    EXPECTED_CASE_IDS,
    EvaluationGoldLabels,
    EvaluationReviewStatus,
    ExpectedAuthorityTier,
    load_evaluation_dataset,
)
from rfp_orchestrator.models import Domain, Requirement
from rfp_orchestrator.requirement_classification import analyze_requirement_input
from rfp_orchestrator.retrieval import build_offline_retrievers

EVIDENCE_MATRIX_PATH = DEFAULT_EVALUATION_DATASET_PATH.parent / "evidence_matrix_v1.md"


def test_assignments_cover_all_24_cases_in_stable_order() -> None:
    assert tuple(EVIDENCE_ASSIGNMENTS) == EXPECTED_CASE_IDS


def test_committed_dataset_matches_reviewed_evidence_assignments() -> None:
    dataset = load_evaluation_dataset()

    validate_evidence_labels(dataset)
    assert dataset == apply_evidence_labels()


def test_every_gold_id_exists_and_matches_its_authority_tier() -> None:
    dataset = load_evaluation_dataset()
    chunks = {chunk.chunk_id: chunk for chunk in load_corpus_chunks(KB_DIRECTORY)}

    for case in dataset.cases:
        for tier in case.gold_labels.expected_authority_order:
            for evidence_id in tier.evidence_ids:
                chunk = chunks[evidence_id]
                assert chunk.source_status is tier.source_status
                assert chunk.authority_rank == tier.authority_rank


def test_cross_domain_cases_have_gold_evidence_from_every_expected_domain() -> None:
    dataset = load_evaluation_dataset()
    chunks = {chunk.chunk_id: chunk for chunk in load_corpus_chunks(KB_DIRECTORY)}

    for case in dataset.cases:
        if len(case.gold_labels.expected_domains) < 2:
            continue
        evidence_domains = {
            chunks[evidence_id].domain
            for evidence_id in case.gold_labels.gold_evidence_ids
        }
        assert evidence_domains == set(case.gold_labels.expected_domains)


def test_every_nonempty_gold_id_is_reachable_in_its_specialist_top_5() -> None:
    dataset = load_evaluation_dataset()
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    by_domain = {
        Domain.PRODUCT: retrievers.product,
        Domain.SECURITY: retrievers.security,
        Domain.IMPLEMENTATION: retrievers.implementation,
    }

    for case in dataset.cases:
        requirement = analyze_requirement_input(
            Requirement(
                requirement_id=case.requirement_id,
                original_text=case.untrusted_rfp_text,
            )
        )
        query = "\n".join(requirement.atomic_requirements) or requirement.original_text
        returned_ids = {
            evidence.chunk_id
            for domain in case.gold_labels.expected_domains
            for evidence in by_domain[domain].search(query, k=5)
        }
        assert set(case.gold_labels.gold_evidence_ids) <= returned_ids


def test_only_missing_or_preretrieval_cases_have_empty_gold_evidence() -> None:
    dataset = load_evaluation_dataset()

    assert tuple(
        case.case_id for case in dataset.cases if not case.gold_labels.gold_evidence_ids
    ) == EXPECTED_EMPTY_EVIDENCE_CASES
    assert EXPECTED_EMPTY_EVIDENCE_CASES == ("EVAL-021", "EVAL-023", "EVAL-024")


def test_stale_tls_evidence_is_visible_but_below_current_evidence() -> None:
    case = load_evaluation_dataset().cases[7]

    assert case.requirement_id == "RFP-008"
    assert [tier.source_status for tier in case.gold_labels.expected_authority_order] == [
        SourceStatus.CURRENT,
        SourceStatus.ARCHIVED,
    ]
    assert case.gold_labels.gold_evidence_ids[-1] == "SEC-CTRL-OLD-001::chunk-001"


def test_conflicting_retention_sources_share_one_authority_tier() -> None:
    case = load_evaluation_dataset().cases[13]

    assert case.requirement_id == "RFP-014"
    assert len(case.gold_labels.expected_authority_order) == 1
    assert set(case.gold_labels.expected_authority_order[0].evidence_ids) == {
        "SEC-RET-001::chunk-001",
        "SEC-RET-OPS-001::chunk-001",
    }


def test_schema_rejects_gold_ids_outside_authority_tiers() -> None:
    with pytest.raises(ValidationError, match="exactly follow"):
        EvaluationGoldLabels(gold_evidence_ids=["PROD-AVAIL-001::chunk-001"])


def test_schema_requires_equal_precedence_sources_to_share_one_tier() -> None:
    with pytest.raises(ValidationError, match="share one authority tier"):
        EvaluationGoldLabels(
            gold_evidence_ids=["A", "B"],
            expected_authority_order=[
                ExpectedAuthorityTier(
                    source_status=SourceStatus.CURRENT,
                    authority_rank=5,
                    evidence_ids=["A"],
                ),
                ExpectedAuthorityTier(
                    source_status=SourceStatus.CURRENT,
                    authority_rank=5,
                    evidence_ids=["B"],
                ),
            ],
        )


def test_evidence_labels_preserve_prior_work_and_newer_claim_gold() -> None:
    dataset = load_evaluation_dataset()

    assert all(case.case_families for case in dataset.cases)
    assert all(case.gold_labels.expected_strategy_family is not None for case in dataset.cases)
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


def test_validator_rejects_gold_evidence_drift() -> None:
    dataset = load_evaluation_dataset()
    payload = dataset.model_dump(mode="json")
    labels = payload["cases"][0]["gold_labels"]
    labels["expected_authority_order"][0]["evidence_ids"].reverse()
    labels["gold_evidence_ids"][:2] = labels["expected_authority_order"][0][
        "evidence_ids"
    ]
    changed = type(dataset).model_validate(payload)

    with pytest.raises(ValueError, match="gold-evidence drift for EVAL-001"):
        validate_evidence_labels(changed)


def test_checked_in_markdown_is_generated_from_validated_evidence_gold() -> None:
    assert EVIDENCE_MATRIX_PATH.read_text(encoding="utf-8") == render_evidence_matrix(
        load_evaluation_dataset()
    )


def test_application_rejects_an_incomplete_assignment_map() -> None:
    assignments = deepcopy(EVIDENCE_ASSIGNMENTS)
    assignments.pop("EVAL-024")

    with pytest.raises(ValueError, match="EVAL-001 through EVAL-024"):
        apply_evidence_labels(load_evaluation_dataset(), assignments)


def test_assignment_rejects_duplicate_ids_across_tiers() -> None:
    repeated = "SEC-CTRL-001::chunk-001"

    with pytest.raises(ValidationError, match="multiple authority tiers"):
        EvidenceAssignment(
            authority_tiers=[
                ExpectedAuthorityTier(
                    source_status=SourceStatus.CURRENT,
                    authority_rank=5,
                    evidence_ids=[repeated],
                ),
                ExpectedAuthorityTier(
                    source_status=SourceStatus.ARCHIVED,
                    authority_rank=2,
                    evidence_ids=[repeated],
                ),
            ],
            evidence_reason="Invalid duplicate.",
        )
