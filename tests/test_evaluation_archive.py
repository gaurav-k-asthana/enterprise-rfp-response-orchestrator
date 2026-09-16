import json
from pathlib import Path

import pytest

from rfp_orchestrator.evaluation_archive import (
    CONTROLLED_FAILURE_FIXTURE_RUN_ID,
    ArchivedFileKind,
    ArchivePurpose,
    EvaluationArchiveError,
    RawEvaluationBundleManifest,
    archive_evaluation_run,
    build_bundle_contents,
    build_controlled_failure_fixture,
    serialize_bundle_manifest,
)
from rfp_orchestrator.evaluation_freeze import text_sha256
from rfp_orchestrator.evaluation_metrics import load_evaluation_run
from rfp_orchestrator.evaluation_runner import (
    DEFAULT_DRY_RUN_OUTPUT_PATH,
    EvaluationRunArtifact,
    EvaluationRunFailure,
    EvaluationRunRecord,
    serialize_evaluation_run,
)
from scripts.archive_evaluation_outputs import main as archive_main


def test_real_smoke_bundle_preserves_full_run_and_two_success_shards(
    tmp_path: Path,
) -> None:
    artifact = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)

    target, manifest, _ = archive_evaluation_run(artifact, archive_root=tmp_path)

    assert manifest.purpose is ArchivePurpose.EVALUATION_RUN
    assert manifest.success_record_count == 2
    assert manifest.failure_record_count == 0
    assert manifest.expected_execution_count == 2
    assert (target / "raw" / "run.json").is_file()
    assert len(list((target / "records").rglob("*.json"))) == 2
    assert not (target / "failures").exists()


def test_canonical_raw_file_is_byte_identical_to_source_artifact(tmp_path: Path) -> None:
    artifact = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    expected_content, expected_digest = serialize_evaluation_run(artifact)

    target, manifest, _ = archive_evaluation_run(artifact, archive_root=tmp_path)

    assert (target / "raw" / "run.json").read_text(encoding="utf-8") == expected_content
    assert manifest.source_run_sha256 == expected_digest


def test_success_shards_validate_as_complete_normalized_records(tmp_path: Path) -> None:
    artifact = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    target, _, _ = archive_evaluation_run(artifact, archive_root=tmp_path)

    shards = sorted((target / "records").rglob("*.json"))
    records = [
        EvaluationRunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        for path in shards
    ]

    assert {(item.case_id, item.architecture) for item in records} == {
        (item.case_id, item.architecture) for item in artifact.records
    }


def test_controlled_fixture_preserves_failure_as_its_own_file(tmp_path: Path) -> None:
    fixture = build_controlled_failure_fixture()

    target, manifest, _ = archive_evaluation_run(
        fixture,
        archive_root=tmp_path,
        purpose=ArchivePurpose.CONTROLLED_FAILURE_FIXTURE,
    )

    assert manifest.source_run_id == CONTROLLED_FAILURE_FIXTURE_RUN_ID
    assert manifest.success_record_count == 1
    assert manifest.failure_record_count == 1
    assert manifest.controlled_fixture_notice.startswith("CONTROLLED TEST FIXTURE")
    failure_paths = list((target / "failures").rglob("*.json"))
    assert len(failure_paths) == 1
    failure = EvaluationRunFailure.model_validate_json(
        failure_paths[0].read_text(encoding="utf-8")
    )
    assert failure.error_type == "ControlledArchiveFixtureFailure"
    assert "not report an observed" in manifest.controlled_fixture_notice


def test_manifest_hashes_and_byte_counts_verify_every_raw_file(tmp_path: Path) -> None:
    target, manifest, manifest_digest = archive_evaluation_run(
        build_controlled_failure_fixture(),
        archive_root=tmp_path,
        purpose=ArchivePurpose.CONTROLLED_FAILURE_FIXTURE,
    )

    for entry in manifest.files:
        content = (target / entry.relative_path).read_text(encoding="utf-8")
        assert text_sha256(content) == entry.sha256
        assert len(content.encode("utf-8")) == entry.byte_count
    manifest_content = (target / "manifest.json").read_text(encoding="utf-8")
    assert text_sha256(manifest_content) == manifest_digest
    assert (target / "manifest.sha256").read_text(encoding="utf-8") == (
        f"{manifest_digest}  manifest.json\n"
    )


def test_exact_existing_bundle_is_idempotently_reverified(tmp_path: Path) -> None:
    artifact = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    first = archive_evaluation_run(artifact, archive_root=tmp_path)
    second = archive_evaluation_run(artifact, archive_root=tmp_path)

    assert first[0] == second[0]
    assert first[1] == second[1]
    assert first[2] == second[2]


def test_tampered_file_is_rejected_instead_of_overwritten(tmp_path: Path) -> None:
    artifact = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    target, _, _ = archive_evaluation_run(artifact, archive_root=tmp_path)
    record_path = next((target / "records").rglob("*.json"))
    record_path.write_text("tampered\n", encoding="utf-8")

    with pytest.raises(EvaluationArchiveError, match="refusing overwrite"):
        archive_evaluation_run(artifact, archive_root=tmp_path)
    assert record_path.read_text(encoding="utf-8") == "tampered\n"


def test_extra_file_is_rejected_instead_of_ignored(tmp_path: Path) -> None:
    artifact = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    target, _, _ = archive_evaluation_run(artifact, archive_root=tmp_path)
    (target / "unexpected.txt").write_text("unexpected\n", encoding="utf-8")

    with pytest.raises(EvaluationArchiveError, match="file set differs"):
        archive_evaluation_run(artifact, archive_root=tmp_path)


def test_unsafe_run_id_cannot_escape_the_archive_root() -> None:
    artifact = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    payload = artifact.model_dump(mode="python")
    payload["run_id"] = "../escape"
    unsafe = EvaluationRunArtifact.model_validate(payload)

    with pytest.raises(EvaluationArchiveError, match="run ID"):
        build_bundle_contents(unsafe, purpose=ArchivePurpose.EVALUATION_RUN)


def test_different_content_cannot_reuse_an_existing_run_directory(
    tmp_path: Path,
) -> None:
    artifact = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    archive_evaluation_run(artifact, archive_root=tmp_path)
    payload = artifact.model_dump(mode="python")
    payload["started_at"] = "different-but-valid"
    different = EvaluationRunArtifact.model_validate(payload)

    with pytest.raises(EvaluationArchiveError, match="content differs"):
        archive_evaluation_run(different, archive_root=tmp_path)


def test_checked_real_and_controlled_bundles_match_current_builders() -> None:
    real = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    real_target, real_manifest, real_digest = archive_evaluation_run(real)
    fixture_target, fixture_manifest, fixture_digest = archive_evaluation_run(
        build_controlled_failure_fixture(),
        purpose=ArchivePurpose.CONTROLLED_FAILURE_FIXTURE,
    )

    for target, manifest, digest in (
        (real_target, real_manifest, real_digest),
        (fixture_target, fixture_manifest, fixture_digest),
    ):
        checked = RawEvaluationBundleManifest.model_validate_json(
            (target / "manifest.json").read_text(encoding="utf-8")
        )
        _, expected_digest = serialize_bundle_manifest(manifest)
        assert checked == manifest
        assert digest == expected_digest


def test_archive_cli_creates_both_inspectable_bundles(tmp_path: Path) -> None:
    assert archive_main(
        [
            "--input",
            str(DEFAULT_DRY_RUN_OUTPUT_PATH),
            "--archive-root",
            str(tmp_path),
            "--include-controlled-failure-fixture",
        ]
    ) == 0
    assert (tmp_path / "step-4-11-offline-dry-eval-001" / "manifest.json").is_file()
    assert (
        tmp_path
        / CONTROLLED_FAILURE_FIXTURE_RUN_ID
        / "failures"
        / "EVAL-001"
        / "orchestrated_peer_specialists.json"
    ).is_file()


def test_bundle_contains_raw_records_not_summary_tables() -> None:
    manifest, contents = build_bundle_contents(
        load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH),
        purpose=ArchivePurpose.EVALUATION_RUN,
    )

    assert manifest.raw_outputs_canonical is True
    assert manifest.summary_files_in_bundle is False
    assert all("summary" not in path for path in contents)
    assert {item.kind for item in manifest.files} == {
        ArchivedFileKind.RAW_RUN,
        ArchivedFileKind.SUCCESS_RECORD,
    }


def test_current_bundle_contents_do_not_expose_credentials_or_vectors() -> None:
    manifests_and_contents = [
        build_bundle_contents(
            load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH),
            purpose=ArchivePurpose.EVALUATION_RUN,
        ),
        build_bundle_contents(
            build_controlled_failure_fixture(),
            purpose=ArchivePurpose.CONTROLLED_FAILURE_FIXTURE,
        ),
    ]
    combined = ""
    for manifest, contents in manifests_and_contents:
        combined += json.dumps(manifest.model_dump(mode="json"))
        combined += "".join(contents.values())
    lowered = combined.lower()
    assert "api_key" not in lowered
    assert "embedding_values" not in lowered
    assert "vector_values" not in lowered
