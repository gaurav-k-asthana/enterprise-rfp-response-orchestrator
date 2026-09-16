from copy import deepcopy
from pathlib import Path

import pytest

from rfp_orchestrator.fair_comparison import (
    COMPARISON_ID,
    DEFAULT_FAIR_COMPARISON_DIGEST_PATH,
    DEFAULT_FAIR_COMPARISON_PATH,
    INTENDED_ARCHITECTURE_DIFFERENCES,
    NORMALIZED_OUTPUT_FIELDS,
    ComparisonArchitecture,
    FairComparisonFreeze,
    build_comparison_profiles,
    build_fair_comparison_freeze,
    serialize_fair_comparison_freeze,
    shared_profile_sha256,
    validate_fair_comparison_freeze,
    validate_fair_profiles,
    write_fair_comparison_freeze,
)
from rfp_orchestrator.provider_config import (
    OPENAI_EMBEDDING_MODEL,
    OPENAI_GENERATION_MODEL,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_profiles_differ_only_by_architecture_identity() -> None:
    baseline, orchestrated = build_comparison_profiles(PROJECT_ROOT)

    validate_fair_profiles(baseline, orchestrated)
    assert baseline.architecture is ComparisonArchitecture.SINGLE_GENERALIST
    assert orchestrated.architecture is ComparisonArchitecture.ORCHESTRATED_PEERS
    assert shared_profile_sha256(baseline) == shared_profile_sha256(orchestrated)


def test_frozen_questions_are_identical_and_gold_is_scoring_only() -> None:
    freeze = build_fair_comparison_freeze(PROJECT_ROOT)

    assert freeze.comparison_id == COMPARISON_ID
    assert freeze.baseline.questions == freeze.orchestrated.questions
    assert freeze.baseline.questions.case_count == 24
    assert freeze.baseline.questions.dataset_status == "FROZEN"
    assert freeze.gold_scoring_reference.exposed_to_comparison_arms is False
    arm_payload = str(freeze.baseline.model_dump(mode="json")).lower()
    assert "gold_content_sha256" not in arm_payload
    assert "expected_domains" not in arm_payload


def test_corpus_and_all_twenty_record_ids_are_shared() -> None:
    baseline, orchestrated = build_comparison_profiles(PROJECT_ROOT)

    assert baseline.corpus == orchestrated.corpus
    assert baseline.corpus.document_count == 12
    assert baseline.corpus.record_count == 20
    assert len(set(baseline.corpus.record_ids)) == 20


def test_generation_model_settings_are_exactly_shared() -> None:
    baseline, orchestrated = build_comparison_profiles(PROJECT_ROOT)

    assert baseline.generation == orchestrated.generation
    assert baseline.generation.model == OPENAI_GENERATION_MODEL
    assert baseline.generation.reasoning_effort == "low"
    assert baseline.generation.max_output_tokens == 2_000
    assert baseline.generation.structured_outputs_strict is True
    assert baseline.generation.store is False


def test_three_available_retrieval_tools_are_exactly_shared() -> None:
    baseline, orchestrated = build_comparison_profiles(PROJECT_ROOT)

    assert baseline.retrieval_tools == orchestrated.retrieval_tools
    assert len(baseline.retrieval_tools) == 3
    assert [tool.domain for tool in baseline.retrieval_tools] == [
        "product",
        "security",
        "implementation",
    ]
    assert all(tool.top_k == 5 for tool in baseline.retrieval_tools)
    assert all(
        tool.embedding_model == OPENAI_EMBEDDING_MODEL
        for tool in baseline.retrieval_tools
    )
    assert baseline.retrieval_tools[0].sparse_weight == 0.60
    assert baseline.retrieval_tools[1].sparse_weight == 0.60
    assert baseline.retrieval_tools[2].sparse_weight is None
    assert baseline.retrieval_tools[2].dense_weight == 1.0


def test_normalized_output_requirements_are_exactly_shared() -> None:
    baseline, orchestrated = build_comparison_profiles(PROJECT_ROOT)

    assert baseline.output_contract == orchestrated.output_contract
    assert tuple(baseline.output_contract.normalized_fields) == NORMALIZED_OUTPUT_FIELDS
    assert baseline.output_contract.claim_support_type == "per-atomic-claim boolean"
    assert baseline.output_contract.aggregate_support_values == [
        "SUPPORTED",
        "PARTIAL",
        "UNSUPPORTED",
    ]


@pytest.mark.parametrize(
    ("section", "field", "changed_value"),
    [
        ("questions", "question_set_sha256", "0" * 64),
        ("corpus", "corpus_sha256", "1" * 64),
        ("generation", "model", "different-model"),
        ("output_contract", "citation_rule", "Different citation rule."),
    ],
)
def test_validator_rejects_any_non_architecture_profile_drift(
    section: str,
    field: str,
    changed_value: str,
) -> None:
    baseline, orchestrated = build_comparison_profiles(PROJECT_ROOT)
    payload = orchestrated.model_dump(mode="json")
    payload[section][field] = changed_value
    changed = type(orchestrated).model_validate(payload)

    with pytest.raises(ValueError, match="fair comparison drift"):
        validate_fair_profiles(baseline, changed)


def test_validator_rejects_retrieval_tool_drift() -> None:
    baseline, orchestrated = build_comparison_profiles(PROJECT_ROOT)
    payload = orchestrated.model_dump(mode="json")
    payload["retrieval_tools"][0]["minimum_relative_score"] = 0.5
    changed = type(orchestrated).model_validate(payload)

    with pytest.raises(ValueError, match="fair comparison drift"):
        validate_fair_profiles(baseline, changed)


def test_only_named_architecture_differences_are_permitted() -> None:
    freeze = build_fair_comparison_freeze(PROJECT_ROOT)

    assert tuple(freeze.intended_architecture_differences) == (
        INTENDED_ARCHITECTURE_DIFFERENCES
    )
    assert freeze.verification["profiles_equal_except_architecture"] is True
    assert freeze.verification["comparative_cases_run"] == 0
    assert freeze.verification["network_calls_made"] == 0


def test_checked_in_freeze_and_sidecar_match_current_shared_inputs() -> None:
    payload = FairComparisonFreeze.model_validate_json(
        DEFAULT_FAIR_COMPARISON_PATH.read_text(encoding="utf-8")
    )
    validate_fair_comparison_freeze(payload)
    expected_content, expected_digest = serialize_fair_comparison_freeze(payload)

    assert DEFAULT_FAIR_COMPARISON_PATH.read_text(encoding="utf-8") == expected_content
    assert DEFAULT_FAIR_COMPARISON_DIGEST_PATH.read_text(encoding="utf-8") == (
        f"{expected_digest}  {DEFAULT_FAIR_COMPARISON_PATH.name}\n"
    )


def test_arm_profiles_are_secret_free_and_use_only_relative_paths() -> None:
    freeze = build_fair_comparison_freeze(PROJECT_ROOT)

    for arm in (freeze.baseline, freeze.orchestrated):
        serialized = str(arm.model_dump(mode="json"))
        lowered = serialized.lower()
        assert "/users/" not in lowered
        assert "openai_api_key" not in lowered
        assert "pinecone_api_key" not in lowered
        assert "langsmith_api_key" not in lowered


def test_write_refuses_to_replace_a_different_freeze(tmp_path: Path) -> None:
    output_path = tmp_path / "fair_comparison_config_v1.json"
    output_path.write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="refusing to overwrite"):
        write_fair_comparison_freeze(output_path)


def test_freeze_rejects_a_changed_shared_checksum() -> None:
    freeze = build_fair_comparison_freeze(PROJECT_ROOT)
    payload = deepcopy(freeze.model_dump(mode="json"))
    payload["shared_profile_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="shared comparison profile checksum"):
        FairComparisonFreeze.model_validate(payload)
