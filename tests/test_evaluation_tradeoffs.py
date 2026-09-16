import json
from pathlib import Path

import pytest

from rfp_orchestrator.evaluation_freeze import KNOWN_IMPLEMENTATION_GAPS, text_sha256
from rfp_orchestrator.evaluation_tradeoffs import (
    DEFAULT_TRADEOFF_JSON_PATH,
    DEFAULT_TRADEOFF_MARKDOWN_PATH,
    EvidenceStrength,
    TradeoffAnalysisError,
    build_tradeoff_analysis,
    render_tradeoff_analysis_markdown,
    serialize_tradeoff_analysis,
    tradeoff_sidecar_path,
    write_tradeoff_analysis,
)
from scripts.generate_tradeoff_analysis import main as analysis_main


def test_headline_has_no_winner_and_states_insufficient_evidence() -> None:
    analysis = build_tradeoff_analysis()
    assert "insufficient comparative evidence" in analysis.headline_finding.lower()
    assert analysis.comparative_winner is None
    assert analysis.universal_multi_agent_superiority_claimed is False
    assert analysis.provider_comparison_completed is False
    assert analysis.repeated_trials_completed is False


def test_observations_match_smoke_table_boundary() -> None:
    analysis = build_tradeoff_analysis()
    assert analysis.source_case_count == 1
    assert analysis.source_record_count == 2
    assert analysis.source_failure_count == 0
    assert all(
        item.evidence_strength is EvidenceStrength.OBSERVED_SMOKE
        for item in analysis.observations
    )
    combined = " ".join(item.statement for item in analysis.observations)
    assert "1/1 Safe Completion" in combined
    assert "zero model calls, tokens, and estimated cost" in combined
    assert "not provider-performance measurements" in combined


def test_hypotheses_are_conditional_not_results() -> None:
    analysis = build_tradeoff_analysis()
    assert all(
        item.evidence_strength is EvidenceStrength.DESIGN_HYPOTHESIS
        for item in analysis.architecture_hypotheses
    )
    combined = " ".join(item.statement for item in analysis.architecture_hypotheses)
    assert "may be preferable" in combined
    assert "only if measured" in combined


def test_limitations_cover_missing_case_families_and_provider_run() -> None:
    combined = " ".join(item.statement for item in build_tradeoff_analysis().limitations)
    assert "Only one of 24" in combined
    assert "deterministic offline fixture" in combined
    assert "cross-domain" in combined
    assert "have not run" in combined


def test_known_gaps_match_frozen_review() -> None:
    assert build_tradeoff_analysis().known_implementation_gaps == list(
        KNOWN_IMPLEMENTATION_GAPS
    )


def test_decision_rules_do_not_attribute_deterministic_gates_to_agent_count() -> None:
    rules = build_tradeoff_analysis().decision_rules
    assert [rule.provisional_preference for rule in rules] == [
        "single_generalist",
        "orchestrated_peer_specialists",
        "no_architecture_preference",
    ]
    assert "do not attribute" in rules[-1].condition


def test_required_evidence_uses_only_approved_repeat_subset() -> None:
    combined = " ".join(
        item.statement for item in build_tradeoff_analysis().required_next_evidence
    )
    assert "all 24 frozen cases" in combined
    assert "EVAL-001, EVAL-002, EVAL-015, and EVAL-021" in combined


def test_markdown_has_prominent_limitations_and_conclusion() -> None:
    markdown = render_tradeoff_analysis_markdown(build_tradeoff_analysis())
    assert "**Comparative winner:** none" in markdown
    assert "**Phase 4 exit gate:** not passed" in markdown
    assert "does not claim that multi-agent orchestration is universally better" in markdown
    assert "Architecture hypotheses—not measured results" in markdown
    assert "The defensible conclusion today is restraint" in markdown


def test_serialization_is_deterministic_and_secret_free() -> None:
    first, first_digest = serialize_tradeoff_analysis(build_tradeoff_analysis())
    second, second_digest = serialize_tradeoff_analysis(build_tradeoff_analysis())
    assert (first, first_digest) == (second, second_digest)
    assert first_digest == text_sha256(first)
    lowered = first.lower()
    assert "api_key" not in lowered
    assert "pinecone_host" not in lowered
    assert "vector_values" not in lowered


def test_writer_creates_distinct_sidecars_and_refuses_drift(tmp_path: Path) -> None:
    json_path = tmp_path / "analysis.json"
    markdown_path = tmp_path / "analysis.md"
    analysis = build_tradeoff_analysis()
    json_digest, markdown_digest = write_tradeoff_analysis(
        analysis, json_path=json_path, markdown_path=markdown_path
    )
    assert tradeoff_sidecar_path(json_path).read_text() == (
        f"{json_digest}  analysis.json\n"
    )
    assert tradeoff_sidecar_path(markdown_path).read_text() == (
        f"{markdown_digest}  analysis.md\n"
    )
    json_path.write_text("different\n")
    with pytest.raises(TradeoffAnalysisError, match="refusing to overwrite"):
        write_tradeoff_analysis(
            analysis, json_path=json_path, markdown_path=markdown_path
        )


def test_checked_in_analysis_matches_generator() -> None:
    analysis = build_tradeoff_analysis()
    json_content, json_digest = serialize_tradeoff_analysis(analysis)
    markdown_content = render_tradeoff_analysis_markdown(analysis)
    markdown_digest = text_sha256(markdown_content)
    assert DEFAULT_TRADEOFF_JSON_PATH.read_text() == json_content
    assert DEFAULT_TRADEOFF_MARKDOWN_PATH.read_text() == markdown_content
    assert tradeoff_sidecar_path(DEFAULT_TRADEOFF_JSON_PATH).read_text() == (
        f"{json_digest}  {DEFAULT_TRADEOFF_JSON_PATH.name}\n"
    )
    assert tradeoff_sidecar_path(DEFAULT_TRADEOFF_MARKDOWN_PATH).read_text() == (
        f"{markdown_digest}  {DEFAULT_TRADEOFF_MARKDOWN_PATH.name}\n"
    )


def test_cli_generates_analysis_without_provider_calls(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    json_path = tmp_path / "analysis.json"
    markdown_path = tmp_path / "analysis.md"
    assert analysis_main(
        [
            "--json-output",
            str(json_path),
            "--markdown-output",
            str(markdown_path),
        ]
    ) == 0
    stdout = capsys.readouterr().out
    assert "Comparative winner: none" in stdout
    assert "Phase 4 exit gate passed: no" in stdout
    assert "New architecture or provider calls made: 0" in stdout
    assert json.loads(json_path.read_text())["analysis_scope"] == "SMOKE_ONLY"
