from __future__ import annotations

import json
import socket

import pytest

from rfp_orchestrator.evaluation_runner import (
    EvaluationRunMode,
    EvaluationRunStatus,
)
from rfp_orchestrator.evaluation_schema import EXPECTED_CASE_IDS
from rfp_orchestrator.evaluation_trials import load_repeat_trial_plan
from rfp_orchestrator.fair_comparison import ComparisonArchitecture
from rfp_orchestrator.fake_provider_rehearsal import (
    build_step_4_g5_rehearsal,
    serialize_fake_provider_rehearsal,
    write_step_4_g5_rehearsal,
)


@pytest.fixture(scope="module")
def report():
    return build_step_4_g5_rehearsal()


def test_rehearsal_accounts_for_both_architectures_across_all_cases(report) -> None:
    artifact = report.artifact
    observed = {
        (item.case_id, item.architecture)
        for item in [*artifact.records, *artifact.failures]
    }
    expected = {
        (case_id, architecture)
        for case_id in EXPECTED_CASE_IDS
        for architecture in ComparisonArchitecture
    }

    assert artifact.mode is EvaluationRunMode.FAKE_PROVIDER_REHEARSAL
    assert artifact.status is EvaluationRunStatus.PARTIAL
    assert artifact.case_ids == list(EXPECTED_CASE_IDS)
    assert len(artifact.records) == 46
    assert len(artifact.failures) == 2
    assert len(artifact.records) + len(artifact.failures) == 48
    assert observed == expected


def test_rehearsal_preserves_deliberate_failures_in_denominator(report) -> None:
    failure_keys = {
        f"{item.case_id}:{item.architecture.value}"
        for item in report.artifact.failures
    }

    assert set(report.deliberately_injected_failure_keys) <= failure_keys
    assert report.failures_preserved_in_denominator is True
    assert report.accounted_architecture_executions == 48
    assert all("secret" not in item.message.lower() for item in report.artifact.failures)


def test_rehearsal_uses_fake_boundaries_even_when_network_is_blocked(monkeypatch) -> None:
    def blocked(*args, **kwargs):
        raise AssertionError("external network access is forbidden in Step 4.G5")

    monkeypatch.setattr(socket, "create_connection", blocked)
    report = build_step_4_g5_rehearsal()

    assert report.fake_clients_only is True
    assert report.external_network_calls == 0
    assert report.counters.embedding_calls > 0
    assert report.counters.embedding_calls == report.counters.pinecone_queries


def test_all_generation_counters_stop_inside_the_approved_envelope(report) -> None:
    budget = load_repeat_trial_plan().budget
    counters = report.counters.generation

    assert counters.attempted_calls == report.artifact.provider_calls_made
    assert counters.attempted_calls == counters.completed_calls + counters.failed_calls
    assert counters.attempted_calls <= budget.max_provider_calls_total
    assert counters.total_input_tokens <= budget.max_total_input_tokens
    assert counters.total_output_tokens <= budget.max_total_output_tokens
    assert max(counters.calls_by_execution.values()) <= (
        budget.max_provider_calls_per_architecture_execution
    )


def test_rehearsal_is_unscored_and_serializes_deterministically(report) -> None:
    first_content, first_digest = serialize_fake_provider_rehearsal(report)
    second_content, second_digest = serialize_fake_provider_rehearsal(report)

    assert report.scoring_performed is False
    assert first_content == second_content
    assert first_digest == second_digest
    assert "fake-openai-key" not in first_content
    assert "fake-pinecone-key" not in first_content


def test_rehearsal_artifact_and_digest_can_be_written(tmp_path) -> None:
    output_path = tmp_path / "rehearsal.json"
    digest_path = tmp_path / "rehearsal.sha256"

    content, digest = write_step_4_g5_rehearsal(output_path, digest_path)

    assert json.loads(output_path.read_text(encoding="utf-8"))
    assert output_path.read_text(encoding="utf-8") == content
    assert digest_path.read_text(encoding="utf-8") == digest + "\n"
