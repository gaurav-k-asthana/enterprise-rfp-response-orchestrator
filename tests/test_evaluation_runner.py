from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.comparison_safety import DEFAULT_SHARED_SAFETY_POLICY_PATH
from rfp_orchestrator.evaluation_freeze import file_sha256
from rfp_orchestrator.evaluation_runner import (
    DEFAULT_DRY_RUN_DIGEST_PATH,
    DEFAULT_DRY_RUN_OUTPUT_PATH,
    EvaluationCaseInput,
    EvaluationRunArtifact,
    EvaluationRunMode,
    EvaluationRunner,
    EvaluationRunnerError,
    EvaluationRunRecord,
    EvaluationRunStatus,
    build_offline_dry_runner,
    build_step_4_11_dry_run,
    serialize_evaluation_run,
    write_evaluation_run,
)
from rfp_orchestrator.fair_comparison import (
    DEFAULT_FAIR_COMPARISON_PATH,
    NORMALIZED_OUTPUT_FIELDS,
    ComparisonArchitecture,
)
from scripts.run_evaluation import main as run_evaluation_main


def test_record_schema_exactly_matches_the_twenty_two_frozen_fields() -> None:
    assert tuple(EvaluationRunRecord.model_fields) == NORMALIZED_OUTPUT_FIELDS


def test_step_4_11_builds_one_complete_paired_unscored_dry_case() -> None:
    artifact = build_step_4_11_dry_run()

    assert artifact.mode is EvaluationRunMode.OFFLINE_DRY_RUN
    assert artifact.status is EvaluationRunStatus.COMPLETE
    assert artifact.case_ids == ["EVAL-001"]
    assert artifact.architectures == list(ComparisonArchitecture)
    assert len(artifact.records) == 2
    assert artifact.failures == []
    assert artifact.gold_labels_exposed is False
    assert artifact.scoring_performed is False
    assert artifact.provider_calls_made == 0


def test_both_dry_records_are_complete_and_finalized() -> None:
    artifact = build_step_4_11_dry_run()

    assert [item.architecture for item in artifact.records] == list(
        ComparisonArchitecture
    )
    for record in artifact.records:
        assert record.case_id == "EVAL-001"
        assert record.requirement_id == "RFP-001"
        assert record.atomic_requirements == [
            "Confirm support for SAML 2.0.",
            "Confirm support for SCIM 2.0.",
        ]
        assert record.consulted_domains == ["product"]
        assert record.support_status == "SUPPORTED"
        assert record.citation_valid is True
        assert record.source_metadata_valid is True
        assert record.risk_classes == []
        assert record.authority_required is False
        assert record.awaiting_human_review is False
        assert record.final_status == "FINALIZED"
        assert record.final_answer
        assert record.errors == []
        assert record.model_usage.provider_calls == 0
        assert record.model_usage.total_tokens == 0
        assert record.latency_ms == 1.0


def test_dry_records_contain_actual_retrieval_and_citation_provenance() -> None:
    artifact = build_step_4_11_dry_run()

    for record in artifact.records:
        assert len(record.retrieval_calls) == 1
        assert record.retrieval_calls[0].requested_k == 5
        assert len(record.evidence) == 3
        evidence_ids = {item.chunk_id for item in record.evidence}
        assert set(record.retrieval_calls[0].result_ids) == evidence_ids
        assert all(
            set(claim.evidence_ids) <= evidence_ids for claim in record.claims
        )


def test_baseline_record_does_not_invent_specialist_output_fields() -> None:
    baseline = build_step_4_11_dry_run().records[0]

    assert baseline.architecture is ComparisonArchitecture.SINGLE_GENERALIST
    assert baseline.retrieval_calls[0].tool_name == "search_product_evidence"
    assert "specialist_outputs" not in baseline.model_dump(mode="json")


def test_runner_is_byte_reproducible_for_the_guided_offline_case() -> None:
    first_content, first_digest = serialize_evaluation_run(
        build_step_4_11_dry_run()
    )
    second_content, second_digest = serialize_evaluation_run(
        build_step_4_11_dry_run()
    )

    assert first_content == second_content
    assert first_digest == second_digest


def test_artifact_references_all_three_frozen_inputs() -> None:
    artifact = build_step_4_11_dry_run()

    assert artifact.frozen_dataset_sha256 == file_sha256(
        Path("data/evaluation/evaluation_cases_v1.json")
    )
    assert artifact.fair_comparison_sha256 == file_sha256(
        DEFAULT_FAIR_COMPARISON_PATH
    )
    assert artifact.shared_safety_policy_sha256 == file_sha256(
        DEFAULT_SHARED_SAFETY_POLICY_PATH
    )


class SpyExecutor:
    def __init__(
        self,
        architecture: ComparisonArchitecture,
        returned_record: EvaluationRunRecord,
    ) -> None:
        self.architecture = architecture
        self.returned_record = returned_record
        self.seen: list[EvaluationCaseInput] = []

    def execute(self, case: EvaluationCaseInput) -> EvaluationRunRecord:
        self.seen.append(case)
        return self.returned_record


def test_executor_receives_only_non_gold_case_fields() -> None:
    records = build_step_4_11_dry_run().records
    spies = {
        architecture: SpyExecutor(architecture, records[index])
        for index, architecture in enumerate(ComparisonArchitecture)
    }
    runner = EvaluationRunner(spies)

    artifact = runner.run(
        case_ids=["EVAL-001"],
        mode=EvaluationRunMode.OFFLINE_DRY_RUN,
        run_id="spy-run",
        started_at="start",
        completed_at="finish",
    )

    assert artifact.status is EvaluationRunStatus.COMPLETE
    for spy in spies.values():
        assert len(spy.seen) == 1
        payload = spy.seen[0].model_dump(mode="json")
        assert set(payload) == {"case_id", "requirement_id", "untrusted_rfp_text"}
        assert "gold" not in str(payload).lower()
        assert "expected" not in str(payload).lower()


class FailingExecutor:
    def __init__(self, architecture: ComparisonArchitecture) -> None:
        self.architecture = architecture

    def execute(self, case: EvaluationCaseInput) -> EvaluationRunRecord:
        raise RuntimeError(f"controlled failure for {case.case_id}")


def test_runner_preserves_a_failed_architecture_in_the_artifact() -> None:
    baseline_record = build_step_4_11_dry_run().records[0]
    runner = EvaluationRunner(
        {
            ComparisonArchitecture.SINGLE_GENERALIST: SpyExecutor(
                ComparisonArchitecture.SINGLE_GENERALIST,
                baseline_record,
            ),
            ComparisonArchitecture.ORCHESTRATED_PEERS: FailingExecutor(
                ComparisonArchitecture.ORCHESTRATED_PEERS
            ),
        }
    )

    artifact = runner.run(
        case_ids=["EVAL-001"],
        mode=EvaluationRunMode.OFFLINE_DRY_RUN,
        run_id="failure-run",
        started_at="start",
        completed_at="finish",
    )

    assert artifact.status is EvaluationRunStatus.PARTIAL
    assert len(artifact.records) == 1
    assert len(artifact.failures) == 1
    assert artifact.failures[0].architecture is ComparisonArchitecture.ORCHESTRATED_PEERS
    assert artifact.failures[0].error_type == "RuntimeError"
    assert "controlled failure" in artifact.failures[0].message


@pytest.mark.parametrize(
    ("case_ids", "message"),
    [
        (["EVAL-999"], "unknown evaluation case"),
        (["EVAL-001", "EVAL-001"], "cannot repeat"),
        (["EVAL-002"], "limited to EVAL-001"),
    ],
)
def test_runner_rejects_unknown_duplicate_or_non_dry_cases(
    case_ids: list[str],
    message: str,
) -> None:
    with pytest.raises(EvaluationRunnerError, match=message):
        build_offline_dry_runner().run(
            case_ids=case_ids,
            mode=EvaluationRunMode.OFFLINE_DRY_RUN,
            run_id="invalid-run",
            started_at="start",
            completed_at="finish",
        )


def test_provider_mode_fails_closed_before_any_executor_runs() -> None:
    records = build_step_4_11_dry_run().records
    spies = {
        architecture: SpyExecutor(architecture, records[index])
        for index, architecture in enumerate(ComparisonArchitecture)
    }
    runner = EvaluationRunner(spies)

    with pytest.raises(EvaluationRunnerError, match="budget and explicit approval"):
        runner.run(
            case_ids=["EVAL-001"],
            mode=EvaluationRunMode.PROVIDER_COMPARISON,
            run_id="forbidden-provider-run",
            started_at="start",
            completed_at="finish",
        )

    assert all(spy.seen == [] for spy in spies.values())


def test_command_rejects_provider_mode_and_non_guided_case(tmp_path: Path) -> None:
    with pytest.raises(EvaluationRunnerError, match="budget and explicit approval"):
        run_evaluation_main(
            [
                "--mode",
                "provider-comparison",
                "--case-id",
                "EVAL-001",
                "--output",
                str(tmp_path / "provider.json"),
            ]
        )
    with pytest.raises(EvaluationRunnerError, match="limited to EVAL-001"):
        run_evaluation_main(
            [
                "--mode",
                "offline-dry-run",
                "--case-id",
                "EVAL-002",
                "--output",
                str(tmp_path / "wrong-case.json"),
            ]
        )


def test_record_rejects_missing_evidence_and_wrong_support_aggregate() -> None:
    record = build_step_4_11_dry_run().records[0]
    missing_evidence = record.model_dump(mode="json")
    missing_evidence["evidence"] = []
    with pytest.raises(ValidationError, match="evidence absent"):
        EvaluationRunRecord.model_validate(missing_evidence)

    wrong_support = record.model_dump(mode="json")
    wrong_support["support_status"] = "UNSUPPORTED"
    with pytest.raises(ValidationError, match="aggregate"):
        EvaluationRunRecord.model_validate(wrong_support)


def test_dry_artifact_rejects_scoring_or_provider_usage() -> None:
    artifact = build_step_4_11_dry_run()
    payload = artifact.model_dump(mode="json")
    payload["scoring_performed"] = True

    with pytest.raises(ValidationError, match="cannot call providers or score"):
        EvaluationRunArtifact.model_validate(payload)


def test_checked_in_dry_artifact_and_sidecar_are_current() -> None:
    checked_in = EvaluationRunArtifact.model_validate_json(
        DEFAULT_DRY_RUN_OUTPUT_PATH.read_text(encoding="utf-8")
    )
    expected = build_step_4_11_dry_run()
    expected_content, expected_digest = serialize_evaluation_run(expected)

    assert checked_in == expected
    assert DEFAULT_DRY_RUN_OUTPUT_PATH.read_text(encoding="utf-8") == expected_content
    assert DEFAULT_DRY_RUN_DIGEST_PATH.read_text(encoding="utf-8") == (
        f"{expected_digest}  {DEFAULT_DRY_RUN_OUTPUT_PATH.name}\n"
    )


def test_write_is_idempotent_but_refuses_different_existing_run(
    tmp_path: Path,
) -> None:
    artifact = build_step_4_11_dry_run()
    output = tmp_path / "dry.json"

    first = write_evaluation_run(artifact, output)
    second = write_evaluation_run(artifact, output)
    assert first == second

    different = deepcopy(artifact.model_dump(mode="json"))
    different["run_id"] = "different-run"
    with pytest.raises(EvaluationRunnerError, match="refusing to overwrite"):
        write_evaluation_run(EvaluationRunArtifact.model_validate(different), output)
