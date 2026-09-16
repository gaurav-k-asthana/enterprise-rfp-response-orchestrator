from __future__ import annotations

import json
from pathlib import Path

import pytest

from rfp_orchestrator.evaluation_freeze import file_sha256
from rfp_orchestrator.evaluation_schema import EXPECTED_CASE_IDS
from rfp_orchestrator.evaluation_trials import SELECTED_REPEAT_CASE_IDS
from rfp_orchestrator.provider_recovery_manifest import (
    ATTEMPT_RECORD_SHA256,
    PREDECESSOR_MANIFEST_SHA256,
    RECOVERY_EXECUTION_SOURCE_PATHS,
    ProviderRecoveryManifestError,
    build_provider_recovery_manifest,
    exact_provider_recovery_command,
    serialize_provider_recovery_manifest,
    verify_recovery_manifest_against_current_files,
    write_provider_recovery_manifest,
)


def test_recovery_manifest_freezes_new_runs_and_carries_forward_usage() -> None:
    manifest = build_provider_recovery_manifest()

    assert manifest.predecessor_manifest.sha256 == PREDECESSOR_MANIFEST_SHA256
    assert manifest.invalid_attempt_record.sha256 == ATTEMPT_RECORD_SHA256
    assert manifest.runs[0].case_ids == list(EXPECTED_CASE_IDS)
    assert manifest.runs[1].case_ids == list(SELECTED_REPEAT_CASE_IDS)
    assert manifest.runs[2].case_ids == list(SELECTED_REPEAT_CASE_IDS)
    assert all(item.run_id.endswith("-recovery-v2") for item in manifest.runs)
    assert manifest.prior_usage.attempted_calls == 36
    assert manifest.prior_usage.input_tokens == 57_403
    assert manifest.prior_usage.output_tokens == 11_971
    assert manifest.recovery_budget.remaining_provider_calls == 92
    assert manifest.recovery_budget.remaining_input_tokens == 966_597
    assert manifest.recovery_budget.remaining_output_tokens == 244_029


def test_recovery_manifest_hashes_current_execution_sources() -> None:
    manifest = build_provider_recovery_manifest()

    assert [item.path for item in manifest.execution_sources] == list(
        RECOVERY_EXECUTION_SOURCE_PATHS
    )
    verify_recovery_manifest_against_current_files(manifest)


def test_recovery_manifest_and_command_are_deterministic_and_secret_free() -> None:
    first, first_digest = serialize_provider_recovery_manifest(build_provider_recovery_manifest())
    second, second_digest = serialize_provider_recovery_manifest(build_provider_recovery_manifest())
    command = exact_provider_recovery_command(first_digest)

    assert (first, first_digest) == (second, second_digest)
    assert "scripts/run_provider_recovery.py --execute" in command
    assert f"--expected-manifest-sha256 {first_digest}" in command
    assert "EXECUTE-NORTHSTAR-RFP-RECOVERY-V2" in command
    assert "OPENAI_API_KEY" not in command
    assert "PINECONE_API_KEY" not in command
    lowered = first.lower()
    assert "expected_answer" not in lowered
    assert "sk-" not in lowered
    assert json.loads(first)["network_calls_made_during_preparation"] == 0


def test_recovery_writer_is_idempotent_and_write_once(tmp_path: Path) -> None:
    output = tmp_path / "recovery.json"
    review = tmp_path / "review.md"
    manifest = build_provider_recovery_manifest()

    first = write_provider_recovery_manifest(manifest, output_path=output, review_path=review)
    second = write_provider_recovery_manifest(manifest, output_path=output, review_path=review)
    assert first == second
    assert first[1] in review.read_text(encoding="utf-8")

    output.write_text("different\n", encoding="utf-8")
    with pytest.raises(ProviderRecoveryManifestError, match="refusing to overwrite"):
        write_provider_recovery_manifest(manifest, output_path=output, review_path=review)


def test_recovery_manifest_detects_source_drift() -> None:
    payload = build_provider_recovery_manifest().model_dump(mode="json")
    payload["source_artifacts"][0]["sha256"] = "0" * 64
    changed = type(build_provider_recovery_manifest()).model_validate(payload)

    with pytest.raises(ProviderRecoveryManifestError, match="drifted"):
        verify_recovery_manifest_against_current_files(changed)


def test_frozen_predecessor_and_attempt_files_still_match() -> None:
    manifest = build_provider_recovery_manifest()

    assert file_sha256(Path(manifest.predecessor_manifest.path)) == PREDECESSOR_MANIFEST_SHA256
    assert file_sha256(Path(manifest.invalid_attempt_record.path)) == ATTEMPT_RECORD_SHA256
