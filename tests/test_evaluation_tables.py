import json
from pathlib import Path

import pytest

from rfp_orchestrator.evaluation_archive import build_controlled_failure_fixture
from rfp_orchestrator.evaluation_freeze import text_sha256
from rfp_orchestrator.evaluation_metrics import load_evaluation_run
from rfp_orchestrator.evaluation_tables import (
    DEFAULT_CANONICAL_RAW_RUN_PATH,
    DEFAULT_COMPARISON_TABLE_JSON_PATH,
    DEFAULT_COMPARISON_TABLE_MARKDOWN_PATH,
    EvaluationTableError,
    ExecutionTableStatus,
    PreferredDirection,
    TableScope,
    generate_comparison_tables,
    render_comparison_table_markdown,
    serialize_comparison_table_report,
    table_sidecar_path,
    write_comparison_tables,
)
from scripts.generate_evaluation_tables import main as table_main


def _smoke_report():
    return generate_comparison_tables(load_evaluation_run(DEFAULT_CANONICAL_RAW_RUN_PATH))


def test_smoke_table_is_paired_and_noncomparative() -> None:
    report = _smoke_report()
    assert report.table_scope is TableScope.SMOKE_ONLY
    assert report.case_count == 1
    assert report.record_count == 2
    assert report.failure_count == 0
    assert report.comparative_conclusions_allowed is False
    assert len(report.case_rows) == 1


def test_summary_columns_preserve_frozen_architecture_order() -> None:
    report = _smoke_report()
    assert [architecture.value for architecture in report.architecture_order] == [
        "single_generalist",
        "orchestrated_peer_specialists",
    ]
    assert report.summary_rows[0].baseline_display == "100.0% (1/1)"
    assert report.summary_rows[0].orchestrated_display == "100.0% (1/1)"


def test_all_approved_metric_families_appear_in_summary() -> None:
    keys = {row.metric_key for row in _smoke_report().summary_rows}
    assert keys == {
        "execution_success_rate",
        "routing_macro_f1",
        "retrieval_recall_at_5",
        "unsupported_claim_rate",
        "groundedness",
        "citation_validity",
        "hitl_f1",
        "conflict_detection_f1",
        "recovery_detection_f1",
        "bounded_recovery_rate",
        "safe_completion_rate",
        "model_calls_total",
        "total_tokens",
        "mean_latency_ms",
        "p95_latency_ms",
        "estimated_cost_usd",
        "preserved_failures",
    }


def test_preferred_directions_are_explicit() -> None:
    rows = {row.metric_key: row for row in _smoke_report().summary_rows}
    assert rows["safe_completion_rate"].preferred_direction is PreferredDirection.HIGHER
    assert rows["unsupported_claim_rate"].preferred_direction is PreferredDirection.LOWER
    assert rows["model_calls_total"].preferred_direction is PreferredDirection.LOWER


def test_case_row_contains_quality_safety_and_efficiency() -> None:
    row = _smoke_report().case_rows[0]
    for cell in (row.baseline, row.orchestrated):
        assert cell.execution_status is ExecutionTableStatus.SUCCESS
        assert cell.routing_f1 == 1.0
        assert cell.recall_at_5 == 1.0
        assert cell.safe_completion is True
        assert cell.model_calls == 0
        assert cell.total_tokens == 0
        assert cell.latency_ms == 1.0
        assert cell.estimated_cost_usd == 0.0


def test_failed_execution_is_visible_and_not_zero_filled() -> None:
    report = generate_comparison_tables(build_controlled_failure_fixture())
    assert report.failure_count == 1
    cell = report.case_rows[0].orchestrated
    assert cell.execution_status is ExecutionTableStatus.FAILURE
    assert cell.failure_type == "ControlledArchiveFixtureFailure"
    assert cell.model_calls is None
    assert cell.total_tokens is None
    assert cell.latency_ms is None
    assert cell.estimated_cost_usd is None
    preserved = next(
        row for row in report.summary_rows if row.metric_key == "preserved_failures"
    )
    assert preserved.orchestrated_display == "1"


def test_markdown_has_visible_smoke_warning_and_source_provenance() -> None:
    report = _smoke_report()
    markdown = render_comparison_table_markdown(report)
    assert "SMOKE ONLY" in markdown
    assert "Comparative conclusions allowed:** no" in markdown
    assert report.source_run_sha256 in markdown
    assert "| Safe Completion Rate |" in markdown
    assert "| EVAL-001 | RFP-001 |" in markdown


def test_serialization_is_deterministic_and_secret_free() -> None:
    first, first_digest = serialize_comparison_table_report(_smoke_report())
    second, second_digest = serialize_comparison_table_report(_smoke_report())
    assert (first, first_digest) == (second, second_digest)
    assert first_digest == text_sha256(first)
    lowered = first.lower()
    assert "api_key" not in lowered
    assert "pinecone_host" not in lowered
    assert "vector_values" not in lowered


def test_writer_creates_both_sidecars_and_is_idempotent(tmp_path: Path) -> None:
    json_path = tmp_path / "tables.json"
    markdown_path = tmp_path / "tables.md"
    report = _smoke_report()
    json_digest, markdown_digest = write_comparison_tables(
        report, json_path=json_path, markdown_path=markdown_path
    )
    assert table_sidecar_path(json_path).read_text() == (
        f"{json_digest}  tables.json\n"
    )
    assert table_sidecar_path(markdown_path).read_text() == (
        f"{markdown_digest}  tables.md\n"
    )
    assert write_comparison_tables(
        report, json_path=json_path, markdown_path=markdown_path
    ) == (json_digest, markdown_digest)


def test_writer_refuses_different_existing_table(tmp_path: Path) -> None:
    json_path = tmp_path / "tables.json"
    markdown_path = tmp_path / "tables.md"
    json_path.write_text("different\n")
    with pytest.raises(EvaluationTableError, match="refusing to overwrite"):
        write_comparison_tables(
            _smoke_report(), json_path=json_path, markdown_path=markdown_path
        )


def test_checked_in_tables_match_generated_report() -> None:
    report = _smoke_report()
    json_content, json_digest = serialize_comparison_table_report(report)
    markdown_content = render_comparison_table_markdown(report)
    markdown_digest = text_sha256(markdown_content)
    assert DEFAULT_COMPARISON_TABLE_JSON_PATH.read_text() == json_content
    assert DEFAULT_COMPARISON_TABLE_MARKDOWN_PATH.read_text() == markdown_content
    assert table_sidecar_path(DEFAULT_COMPARISON_TABLE_JSON_PATH).read_text() == (
        f"{json_digest}  {DEFAULT_COMPARISON_TABLE_JSON_PATH.name}\n"
    )
    assert table_sidecar_path(DEFAULT_COMPARISON_TABLE_MARKDOWN_PATH).read_text() == (
        f"{markdown_digest}  {DEFAULT_COMPARISON_TABLE_MARKDOWN_PATH.name}\n"
    )


def test_cli_generates_tables_without_provider_calls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    json_path = tmp_path / "tables.json"
    markdown_path = tmp_path / "tables.md"
    assert table_main(
        [
            "--input",
            str(DEFAULT_CANONICAL_RAW_RUN_PATH),
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        ]
    ) == 0
    stdout = capsys.readouterr().out
    assert "Manual values entered: no" in stdout
    assert "New architecture or provider calls made: 0" in stdout
    assert "Comparative conclusions allowed: no" in stdout
    assert json.loads(json_path.read_text())["table_scope"] == "SMOKE_ONLY"
