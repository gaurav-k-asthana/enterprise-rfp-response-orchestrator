from __future__ import annotations

from pathlib import Path

import pytest

from rfp_orchestrator.fair_comparison import ComparisonArchitecture
from rfp_orchestrator.provider_final_evaluation import (
    DEFAULT_FINAL_JSON_PATH,
    DEFAULT_FINAL_MARKDOWN_PATH,
    ProviderFinalEvaluationError,
    build_provider_final_evaluation,
    render_provider_final_evaluation,
    serialize_provider_final_evaluation,
    write_provider_final_evaluation,
)


def report():
    return build_provider_final_evaluation()


def test_final_report_preserves_primary_metrics_and_all_failures() -> None:
    result = report()
    by_arch = {item.architecture: item for item in result.primary_architecture_headlines}

    assert result.total_requested_architecture_executions == 64
    assert result.total_successful_executions == 45
    assert result.total_failed_executions == 19
    assert by_arch[ComparisonArchitecture.SINGLE_GENERALIST].safe_completion_numerator == 20
    assert by_arch[ComparisonArchitecture.ORCHESTRATED_PEERS].safe_completion_numerator == 10
    assert by_arch[ComparisonArchitecture.SINGLE_GENERALIST].execution_success_numerator == 24
    assert by_arch[ComparisonArchitecture.ORCHESTRATED_PEERS].execution_success_numerator == 20


def test_repeat_summary_exposes_budget_censoring_instead_of_imputing_results() -> None:
    result = report()
    by_arch = {item.architecture: item for item in result.repeat_architecture_summaries}

    assert len(result.repeat_observations) == 24
    assert sum(item.execution_success for item in result.repeat_observations) == 8
    assert by_arch[ComparisonArchitecture.SINGLE_GENERALIST].successful_observations == 5
    assert by_arch[ComparisonArchitecture.ORCHESTRATED_PEERS].successful_observations == 3
    assert sum(item.failed_observations for item in by_arch.values()) == 16
    assert result.repeated_trials_fully_observed is False


def test_analysis_is_bounded_and_requires_human_review() -> None:
    result = report()
    rendered = render_provider_final_evaluation(result).lower()

    assert result.bounded_preference == "single_generalist_for_frozen_v1"
    assert result.universal_multi_agent_superiority_claimed is False
    assert result.phase_4_exit_gate_ready_for_human_review is True
    assert result.phase_4_exit_gate_passed is False
    assert "universal" in rendered
    assert "budget-censored" in rendered
    assert "all 19 failures" in rendered
    assert "new provider calls made by this analysis: 0" in rendered


def test_serialization_is_deterministic_and_secret_free() -> None:
    first, first_digest = serialize_provider_final_evaluation(report())
    second, second_digest = serialize_provider_final_evaluation(report())

    assert (first, first_digest) == (second, second_digest)
    assert "OPENAI_API_KEY" not in first
    assert "PINECONE_API_KEY" not in first
    assert "sk-" not in first.lower()


def test_writer_is_idempotent_and_write_once(tmp_path: Path) -> None:
    json_path = tmp_path / "final.json"
    markdown_path = tmp_path / "final.md"
    result = report()

    first = write_provider_final_evaluation(
        result, json_path=json_path, markdown_path=markdown_path
    )
    second = write_provider_final_evaluation(
        result, json_path=json_path, markdown_path=markdown_path
    )
    assert first == second

    json_path.write_text("different\n", encoding="utf-8")
    with pytest.raises(ProviderFinalEvaluationError, match="refusing to overwrite"):
        write_provider_final_evaluation(result, json_path=json_path, markdown_path=markdown_path)


def test_checked_in_review_artifacts_match_the_builder() -> None:
    result = report()
    json_content, json_digest = serialize_provider_final_evaluation(result)
    markdown_content = render_provider_final_evaluation(result)

    assert DEFAULT_FINAL_JSON_PATH.read_text(encoding="utf-8") == json_content
    assert DEFAULT_FINAL_MARKDOWN_PATH.read_text(encoding="utf-8") == markdown_content
    assert (
        DEFAULT_FINAL_JSON_PATH.with_name(f"{DEFAULT_FINAL_JSON_PATH.name}.sha256").read_text(
            encoding="utf-8"
        )
        == f"{json_digest}  {DEFAULT_FINAL_JSON_PATH.name}\n"
    )
