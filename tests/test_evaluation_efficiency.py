from pathlib import Path

import pytest

from rfp_orchestrator.evaluation_efficiency import (
    DEFAULT_EFFICIENCY_DIGEST_PATH,
    DEFAULT_EFFICIENCY_OUTPUT_PATH,
    DEFAULT_PRICING_SNAPSHOT_DIGEST_PATH,
    DEFAULT_PRICING_SNAPSHOT_PATH,
    CostStatus,
    EfficiencyMetricsError,
    EfficiencyReport,
    build_pricing_snapshot,
    build_step_4_14_smoke_report,
    calculate_efficiency,
    serialize_efficiency_report,
    serialize_pricing_snapshot,
    write_efficiency_report,
)
from rfp_orchestrator.evaluation_metrics import load_evaluation_run
from rfp_orchestrator.evaluation_runner import (
    DEFAULT_DRY_RUN_OUTPUT_PATH,
    EvaluationRunArtifact,
    EvaluationRunFailure,
    EvaluationRunMode,
    EvaluationRunStatus,
)
from scripts.calculate_evaluation_efficiency import main as efficiency_main


def _usage_artifact(
    *,
    provider: str = "OpenAI API",
    model: str = "gpt-5.6-terra",
    calls: int = 2,
    input_tokens: int = 1_000,
    output_tokens: int = 500,
    recorded_cost: float | None = None,
) -> EvaluationRunArtifact:
    source = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    payload = source.model_dump(mode="python")
    payload["mode"] = EvaluationRunMode.PROVIDER_COMPARISON
    usage = payload["records"][0]["model_usage"]
    usage.update(
        provider=provider,
        model=model,
        provider_calls=calls,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        estimated_cost_usd=recorded_cost,
    )
    payload["provider_calls_made"] = calls
    return EvaluationRunArtifact.model_validate(payload)


def test_pricing_snapshot_freezes_current_official_standard_rates() -> None:
    snapshot = build_pricing_snapshot()

    assert snapshot.model == "gpt-5.6-terra"
    assert snapshot.billing_unit_tokens == 1_000_000
    assert snapshot.input_usd_per_unit == 2.0
    assert snapshot.cached_input_usd_per_unit == 0.2
    assert snapshot.output_usd_per_unit == 12.0
    assert snapshot.checked_at == "2026-09-12"
    assert snapshot.source_url.startswith("https://developers.openai.com/")


def test_offline_smoke_reports_zero_calls_tokens_and_cost() -> None:
    report = build_step_4_14_smoke_report()

    assert report.report_scope == "SMOKE_ONLY"
    assert report.new_provider_calls_made_by_reporter == 0
    assert report.comparative_conclusions_allowed is False
    for summary in report.architecture_summaries:
        assert summary.usage_complete is True
        assert summary.model_calls_total == 0
        assert summary.input_tokens_total == 0
        assert summary.output_tokens_total == 0
        assert summary.total_tokens == 0
        assert summary.estimated_cost_usd_total == 0.0
        assert summary.latency_ms.observation_count == 1
        assert summary.latency_ms.mean == 1.0
        assert summary.latency_ms.p95_nearest_rank == 1.0


def test_smoke_keeps_per_case_efficiency_provenance() -> None:
    report = build_step_4_14_smoke_report()

    assert len(report.case_details) == 2
    for detail in report.case_details:
        assert detail.execution_failed is False
        assert detail.provider == "offline_fixture"
        assert detail.model == "deterministic_no_llm"
        assert detail.model_calls == 0
        assert detail.total_tokens == 0
        assert detail.latency_ms == 1.0
        assert detail.calculated_estimated_cost_usd == 0.0
        assert detail.cost_status is CostStatus.ZERO_USAGE


def test_standard_rate_estimate_uses_input_and_output_separately() -> None:
    report = calculate_efficiency(_usage_artifact())
    detail = report.case_details[0]
    baseline = report.architecture_summaries[0]

    assert detail.calculated_estimated_cost_usd == 0.008
    assert detail.cost_status is CostStatus.STANDARD_RATE_ESTIMATE
    assert baseline.model_calls_total == 2
    assert baseline.input_tokens_total == 1_000
    assert baseline.output_tokens_total == 500
    assert baseline.total_tokens == 1_500
    assert baseline.estimated_cost_usd_total == 0.008


def test_runtime_openai_label_matches_the_frozen_openai_api_provider() -> None:
    source = _usage_artifact()
    payload = source.model_dump(mode="python")
    payload["records"][0]["model_usage"]["provider"] = "openai"

    report = calculate_efficiency(type(source).model_validate(payload))

    assert report.case_details[0].provider == "openai"
    assert report.case_details[0].calculated_estimated_cost_usd == 0.008


def test_recorded_cost_must_match_the_frozen_estimate() -> None:
    artifact = _usage_artifact(recorded_cost=1.0)

    with pytest.raises(EfficiencyMetricsError, match="recorded estimated cost"):
        calculate_efficiency(artifact)


@pytest.mark.parametrize(
    ("provider", "model"),
    [("different-provider", "gpt-5.6-terra"), ("OpenAI API", "different-model")],
)
def test_paid_usage_must_match_the_frozen_provider_and_model(provider: str, model: str) -> None:
    artifact = _usage_artifact(provider=provider, model=model)

    with pytest.raises(EfficiencyMetricsError, match="frozen pricing model"):
        calculate_efficiency(artifact)


def test_zero_calls_cannot_hide_nonzero_tokens() -> None:
    artifact = _usage_artifact(calls=0, input_tokens=1, output_tokens=0)

    with pytest.raises(EfficiencyMetricsError, match="zero provider calls"):
        calculate_efficiency(artifact)


def test_failed_execution_usage_is_unobserved_not_zero() -> None:
    source = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    payload = source.model_dump(mode="python")
    failed_record = payload["records"].pop()
    payload["failures"] = [
        EvaluationRunFailure(
            case_id=failed_record["case_id"],
            requirement_id=failed_record["requirement_id"],
            architecture=failed_record["architecture"],
            error_type="ControlledFailure",
            message="usage observation unavailable",
        )
    ]
    payload["status"] = EvaluationRunStatus.PARTIAL
    artifact = EvaluationRunArtifact.model_validate(payload)

    report = calculate_efficiency(artifact)
    summary = report.architecture_summaries[1]
    detail = report.case_details[1]

    assert summary.usage_complete is False
    assert summary.unobserved_failure_count == 1
    assert summary.latency_ms.missing_count == 1
    assert detail.model_calls is None
    assert detail.total_tokens is None
    assert detail.latency_ms is None
    assert detail.calculated_estimated_cost_usd is None
    assert detail.cost_status is CostStatus.UNOBSERVED_EXECUTION_FAILURE


def test_efficiency_report_is_byte_reproducible() -> None:
    first_content, first_digest = serialize_efficiency_report(build_step_4_14_smoke_report())
    second_content, second_digest = serialize_efficiency_report(build_step_4_14_smoke_report())

    assert first_content == second_content
    assert first_digest == second_digest


def test_checked_pricing_snapshot_and_sidecar_match() -> None:
    content, digest = serialize_pricing_snapshot(build_pricing_snapshot())

    assert DEFAULT_PRICING_SNAPSHOT_PATH.read_text(encoding="utf-8") == content
    assert DEFAULT_PRICING_SNAPSHOT_DIGEST_PATH.read_text(encoding="utf-8") == (
        f"{digest}  {DEFAULT_PRICING_SNAPSHOT_PATH.name}\n"
    )


def test_checked_efficiency_artifact_and_sidecar_match() -> None:
    content, digest = serialize_efficiency_report(build_step_4_14_smoke_report())

    assert DEFAULT_EFFICIENCY_OUTPUT_PATH.read_text(encoding="utf-8") == content
    assert DEFAULT_EFFICIENCY_DIGEST_PATH.read_text(encoding="utf-8") == (
        f"{digest}  {DEFAULT_EFFICIENCY_OUTPUT_PATH.name}\n"
    )


def test_writer_refuses_to_replace_a_different_report(tmp_path: Path) -> None:
    output = tmp_path / "efficiency.json"
    output.write_text("different\n", encoding="utf-8")

    with pytest.raises(EfficiencyMetricsError, match="refusing to overwrite"):
        write_efficiency_report(build_step_4_14_smoke_report(), output)


def test_efficiency_cli_is_provider_free(tmp_path: Path) -> None:
    output = tmp_path / "efficiency.json"
    pricing = tmp_path / "pricing.json"

    assert (
        efficiency_main(
            [
                "--input",
                str(DEFAULT_DRY_RUN_OUTPUT_PATH),
                "--output",
                str(output),
                "--pricing-output",
                str(pricing),
            ]
        )
        == 0
    )
    report = EfficiencyReport.model_validate_json(output.read_text(encoding="utf-8"))
    assert report.new_provider_calls_made_by_reporter == 0
    assert report.comparative_conclusions_allowed is False


def test_efficiency_artifacts_contain_no_credentials_or_vectors() -> None:
    report_content, _ = serialize_efficiency_report(build_step_4_14_smoke_report())
    pricing_content, _ = serialize_pricing_snapshot(build_pricing_snapshot())

    lowered = (report_content + pricing_content).lower()
    assert "api_key" not in lowered
    assert "secret" not in lowered
    assert "embedding_values" not in lowered
    assert "vector_values" not in lowered
