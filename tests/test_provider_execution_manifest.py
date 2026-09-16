from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfp_orchestrator.evaluation_freeze import file_sha256
from rfp_orchestrator.evaluation_schema import EXPECTED_CASE_IDS
from rfp_orchestrator.evaluation_trials import SELECTED_REPEAT_CASE_IDS
from rfp_orchestrator.fair_comparison import ComparisonArchitecture
from rfp_orchestrator.provider_execution_manifest import (
    DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH,
    DEFAULT_PROVIDER_EXECUTION_REVIEW_PATH,
    EXECUTION_SOURCE_PATHS,
    ProviderExecutionManifestError,
    build_provider_execution_manifest,
    exact_provider_command,
    serialize_provider_execution_manifest,
    verify_manifest_against_current_files,
    write_provider_execution_manifest,
)


def test_manifest_freezes_the_complete_case_trial_and_architecture_scope() -> None:
    manifest = build_provider_execution_manifest()

    assert manifest.architectures == list(ComparisonArchitecture)
    assert manifest.runs[0].case_ids == list(EXPECTED_CASE_IDS)
    assert manifest.runs[1].case_ids == list(SELECTED_REPEAT_CASE_IDS)
    assert manifest.runs[2].case_ids == list(SELECTED_REPEAT_CASE_IDS)
    assert manifest.primary_architecture_execution_count == 48
    assert manifest.repeat_architecture_execution_count == 16
    assert manifest.total_architecture_execution_count == 64
    assert manifest.provider_calls_made == 0
    assert manifest.network_calls_made == 0


def test_manifest_freezes_provider_retrieval_and_budget_boundaries() -> None:
    manifest = build_provider_execution_manifest()
    config = manifest.provider_configuration
    budget = manifest.budget

    assert config.generation_model == "gpt-5.6-terra"
    assert config.max_output_tokens_per_call == 2_000
    assert config.response_store is False
    assert config.strict_structured_outputs is True
    assert config.embedding_model == "text-embedding-3-small"
    assert config.embedding_dimensions == 1_536
    assert config.pinecone_index == "rfp-agentic-ai-v1"
    assert config.pinecone_namespace == "northstar-v1"
    assert config.product_retrieval == "hybrid_dense_sparse_top_5"
    assert config.security_retrieval == "hybrid_dense_sparse_top_5"
    assert config.implementation_retrieval == "dense_top_5"
    assert budget.authorized_maximum_usd == 5.12
    assert budget.max_provider_calls_total == 128
    assert budget.max_total_input_tokens == 1_024_000
    assert budget.max_total_output_tokens == 256_000
    assert budget.automatic_provider_retries_allowed is False


def test_manifest_hashes_every_execution_source_and_current_artifact() -> None:
    manifest = build_provider_execution_manifest()

    assert [item.path for item in manifest.execution_sources] == list(EXECUTION_SOURCE_PATHS)
    verify_manifest_against_current_files(manifest)
    by_path = {item.path: item.sha256 for item in manifest.source_artifacts}
    for path in EXECUTION_SOURCE_PATHS:
        assert by_path[path] == file_sha256(Path(path))


def test_manifest_serialization_and_exact_command_are_deterministic() -> None:
    first = build_provider_execution_manifest()
    second = build_provider_execution_manifest()
    first_content, first_digest = serialize_provider_execution_manifest(first)
    second_content, second_digest = serialize_provider_execution_manifest(second)
    command = exact_provider_command(first_digest)

    assert (first_content, first_digest) == (second_content, second_digest)
    assert f"--expected-manifest-sha256 {first_digest}" in command
    assert "--execute" in command
    assert "--approval-token EXECUTE-NORTHSTAR-RFP-COMPARISON-V1" in command
    assert "OPENAI_API_KEY" not in command
    assert "PINECONE_API_KEY" not in command
    assert "sk-" not in first_content.lower()
    assert "test-openai-key" not in first_content.lower()
    assert "test-pinecone-key" not in first_content.lower()


def test_writer_is_idempotent_and_refuses_different_content(tmp_path: Path) -> None:
    output = tmp_path / "manifest.json"
    review = tmp_path / "review.md"
    manifest = build_provider_execution_manifest()

    first = write_provider_execution_manifest(
        manifest,
        output_path=output,
        review_path=review,
    )
    second = write_provider_execution_manifest(
        manifest,
        output_path=output,
        review_path=review,
    )
    assert first == second
    assert first[1] in review.read_text(encoding="utf-8")

    output.write_text("different\n", encoding="utf-8")
    with pytest.raises(ProviderExecutionManifestError, match="refusing to overwrite"):
        write_provider_execution_manifest(
            manifest,
            output_path=output,
            review_path=review,
        )


def test_original_checked_in_manifest_remains_immutable_after_recovery_fixes() -> None:
    digest = file_sha256(DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH)

    assert digest == "48932d8e0da2ac7a764b03cc69e23faa6aa8d9579db659ffaac569c609ffc938"
    assert DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH.with_suffix(".sha256").read_text(
        encoding="utf-8"
    ) == (f"{digest}  {DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH.name}\n")
    review = DEFAULT_PROVIDER_EXECUTION_REVIEW_PATH.read_text(encoding="utf-8")
    assert "AWAITING EXACT-COMMAND APPROVAL" in review
    assert exact_provider_command(digest) in review
    assert "Step 4.G6 prepares the boundary only" in review


def test_changed_source_hash_fails_closed() -> None:
    payload = build_provider_execution_manifest().model_dump(mode="json")
    payload["source_artifacts"][0]["sha256"] = "0" * 64
    changed = type(build_provider_execution_manifest()).model_validate(payload)

    with pytest.raises(ProviderExecutionManifestError, match="drifted"):
        verify_manifest_against_current_files(changed)


def test_manifest_contains_no_gold_labels_or_secrets() -> None:
    content, _ = serialize_provider_execution_manifest(build_provider_execution_manifest())
    lowered = content.lower()

    assert "expected_answer" not in lowered
    assert "expected_route" not in lowered
    assert "claim_gold" not in lowered
    assert "pinecone_host" not in lowered
    assert "vector_values" not in lowered
    assert json.loads(content)["gold_labels_exposed_to_executors"] is False
