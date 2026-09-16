from pathlib import Path

import pytest

from rfp_orchestrator.evaluation_metrics import (
    DEFAULT_METRICS_DIGEST_PATH,
    DEFAULT_METRICS_OUTPUT_PATH,
    EvaluationMetricReport,
    EvaluationMetricsError,
    binary_metrics,
    build_step_4_12_smoke_report,
    calculate_metrics,
    load_evaluation_run,
    serialize_metric_report,
    write_metric_report,
)
from rfp_orchestrator.evaluation_runner import (
    DEFAULT_DRY_RUN_OUTPUT_PATH,
    EvaluationRunArtifact,
    EvaluationRunFailure,
    EvaluationRunStatus,
)
from rfp_orchestrator.fair_comparison import ComparisonArchitecture
from scripts.calculate_evaluation_metrics import main as calculate_metrics_main


def test_step_4_12_smoke_report_is_explicitly_non_comparative() -> None:
    report = build_step_4_12_smoke_report()

    assert report.report_scope == "SMOKE_ONLY"
    assert report.case_count == 1
    assert report.record_count == 2
    assert report.failure_count == 0
    assert report.gold_scoring_performed is True
    assert report.gold_labels_exposed_to_executors is False
    assert report.safe_completion_rate_calculated is False
    assert report.comparative_conclusions_allowed is False
    assert report.provider_calls_in_source_run == 0


def test_evaluation_001_smoke_metrics_are_perfect_for_both_arms() -> None:
    report = build_step_4_12_smoke_report()

    for summary in report.architecture_summaries:
        assert summary.execution_success_rate.value == 1.0
        assert summary.routing_micro.precision == 1.0
        assert summary.routing_micro.recall == 1.0
        assert summary.routing_micro.f1 == 1.0
        assert summary.routing_macro_f1.value == 1.0
        assert summary.retrieval_recall_at_5.value == 1.0
        assert summary.unsupported_claim_rate.value == 0.0
        assert summary.groundedness.value == 1.0
        assert summary.citation_validity.value == 1.0
        assert summary.hitl.accuracy == 1.0
        assert summary.conflict_detection.accuracy == 1.0
        assert summary.recovery_detection.accuracy == 1.0
        assert summary.hitl.f1 is None
        assert summary.conflict_detection.f1 is None
        assert summary.recovery_detection.f1 is None


def test_case_details_make_every_smoke_aggregate_regenerable() -> None:
    report = build_step_4_12_smoke_report()

    assert [item.architecture for item in report.case_details] == list(
        ComparisonArchitecture
    )
    for detail in report.case_details:
        assert detail.expected_domains == ["product"]
        assert detail.observed_domains == ["product"]
        assert detail.routing_f1 == 1.0
        assert detail.recall_at_5 == 1.0
        assert detail.claim_count == 2
        assert detail.unsupported_claim_count == 0
        assert detail.grounded_claim_count == 2
        assert detail.citation_applicable is True
        assert detail.citation_valid is True


def test_binary_metrics_exposes_false_positives_and_false_negatives() -> None:
    metric = binary_metrics(
        [True, True, False, False],
        [True, False, True, False],
    )

    assert metric.true_positive == 1
    assert metric.false_positive == 1
    assert metric.false_negative == 1
    assert metric.true_negative == 1
    assert metric.precision == 0.5
    assert metric.recall == 0.5
    assert metric.f1 == 0.5
    assert metric.accuracy == 0.5


def test_binary_metrics_uses_none_when_positive_denominators_do_not_exist() -> None:
    metric = binary_metrics([False], [False])

    assert metric.precision is None
    assert metric.recall is None
    assert metric.f1 is None
    assert metric.accuracy == 1.0


def test_failed_execution_remains_in_denominators_and_case_details() -> None:
    source = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    payload = source.model_dump(mode="python")
    failed_record = payload["records"].pop()
    payload["failures"] = [
        EvaluationRunFailure(
            case_id=failed_record["case_id"],
            requirement_id=failed_record["requirement_id"],
            architecture=failed_record["architecture"],
            error_type="ControlledFailure",
            message="preserved for metric testing",
        )
    ]
    payload["status"] = EvaluationRunStatus.PARTIAL
    artifact = EvaluationRunArtifact.model_validate(payload)

    report = calculate_metrics(artifact)
    orchestrated = report.architecture_summaries[1]
    detail = report.case_details[1]

    assert report.failure_count == 1
    assert orchestrated.execution_success_rate.value == 0.0
    assert detail.execution_failed is True
    assert detail.failure_type == "ControlledFailure"
    assert detail.retrieved_evidence_ids == []
    assert detail.recall_at_5 == 0.0


def test_metric_calculation_rejects_frozen_input_hash_drift() -> None:
    source = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    payload = source.model_dump(mode="python")
    payload["fair_comparison_sha256"] = "0" * 64
    drifted = EvaluationRunArtifact.model_validate(payload)

    with pytest.raises(EvaluationMetricsError, match="provenance drifted"):
        calculate_metrics(drifted)


def test_metric_report_serialization_is_byte_reproducible() -> None:
    first_content, first_digest = serialize_metric_report(
        build_step_4_12_smoke_report()
    )
    second_content, second_digest = serialize_metric_report(
        build_step_4_12_smoke_report()
    )

    assert first_content == second_content
    assert first_digest == second_digest


def test_checked_metric_artifact_and_sidecar_match_generated_report() -> None:
    content, digest = serialize_metric_report(build_step_4_12_smoke_report())

    assert DEFAULT_METRICS_OUTPUT_PATH.read_text(encoding="utf-8") == content
    assert DEFAULT_METRICS_DIGEST_PATH.read_text(encoding="utf-8") == (
        f"{digest}  {DEFAULT_METRICS_OUTPUT_PATH.name}\n"
    )


def test_metric_writer_refuses_to_overwrite_a_different_report(tmp_path: Path) -> None:
    output = tmp_path / "metrics.json"
    output.write_text("different\n", encoding="utf-8")

    with pytest.raises(EvaluationMetricsError, match="refusing to overwrite"):
        write_metric_report(build_step_4_12_smoke_report(), output)


def test_metric_cli_regenerates_report_without_provider_calls(tmp_path: Path) -> None:
    output = tmp_path / "metrics.json"

    assert calculate_metrics_main(
        [
            "--input",
            str(DEFAULT_DRY_RUN_OUTPUT_PATH),
            "--output",
            str(output),
        ]
    ) == 0
    parsed = EvaluationMetricReport.model_validate_json(
        output.read_text(encoding="utf-8")
    )
    assert parsed.report_scope == "SMOKE_ONLY"
    assert parsed.provider_calls_in_source_run == 0
    assert parsed.safe_completion_rate_calculated is False


def test_metric_report_contains_no_credentials_or_vectors() -> None:
    content, _ = serialize_metric_report(build_step_4_12_smoke_report())

    lowered = content.lower()
    assert "api_key" not in lowered
    assert "secret" not in lowered
    assert "embedding_values" not in lowered
    assert "vector_values" not in lowered
