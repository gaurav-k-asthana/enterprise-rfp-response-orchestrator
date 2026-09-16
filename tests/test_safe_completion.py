from pathlib import Path

import pytest

from rfp_orchestrator.evaluation_metrics import load_evaluation_run
from rfp_orchestrator.evaluation_runner import (
    DEFAULT_DRY_RUN_OUTPUT_PATH,
    EvaluationRunArtifact,
    EvaluationRunFailure,
    EvaluationRunStatus,
)
from rfp_orchestrator.models import RequirementStatus, RiskClass
from rfp_orchestrator.safe_completion import (
    DEFAULT_SAFE_COMPLETION_DIGEST_PATH,
    DEFAULT_SAFE_COMPLETION_OUTPUT_PATH,
    ObservedDisposition,
    SafeCompletionError,
    SafeCompletionReport,
    build_step_4_13_smoke_report,
    calculate_safe_completion,
    serialize_safe_completion_report,
    write_safe_completion_report,
)
from scripts.calculate_safe_completion import main as calculate_safe_completion_main


def _artifact_for_case(
    case_id: str,
    requirement_id: str,
    *,
    escalated: bool,
    risk_classes: list[RiskClass],
) -> EvaluationRunArtifact:
    source = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    payload = source.model_dump(mode="python")
    payload["case_ids"] = [case_id]
    for record in payload["records"]:
        record["case_id"] = case_id
        record["requirement_id"] = requirement_id
        record["risk_classes"] = risk_classes
        record["authority_required"] = escalated
        record["awaiting_human_review"] = escalated
        record["final_status"] = (
            RequirementStatus.NEEDS_HUMAN
            if escalated
            else RequirementStatus.FINALIZED
        )
        record["final_answer"] = None if escalated else record["proposed_answer"]
    return EvaluationRunArtifact.model_validate(payload)


def test_smoke_safe_completion_is_one_for_both_architectures() -> None:
    report = build_step_4_13_smoke_report()

    assert report.report_scope == "SMOKE_ONLY"
    assert report.safe_completion_rate_calculated is True
    assert report.comparative_conclusions_allowed is False
    assert report.provider_calls_in_source_run == 0
    for summary in report.architecture_summaries:
        assert summary.safely_finalized_count == 1
        assert summary.correctly_escalated_count == 0
        assert summary.unsafe_or_incomplete_count == 0
        assert summary.safe_completion_rate.numerator == 1
        assert summary.safe_completion_rate.denominator == 1
        assert summary.safe_completion_rate.value == 1.0


def test_safe_autonomous_completion_requires_every_guard() -> None:
    report = build_step_4_13_smoke_report()

    for outcome in report.case_outcomes:
        assert outcome.observed_disposition is ObservedDisposition.FINALIZED
        assert outcome.safely_finalized is True
        assert outcome.correctly_escalated is False
        assert outcome.safe_completion is True
        assert all(outcome.checks.model_dump().values())
        assert outcome.failure_reasons == []


def test_required_hitl_counts_as_correct_escalation() -> None:
    artifact = _artifact_for_case(
        "EVAL-005",
        "RFP-005",
        escalated=True,
        risk_classes=[RiskClass.SLA_OR_SERVICE_CREDIT],
    )

    report = calculate_safe_completion(artifact)

    for outcome in report.case_outcomes:
        assert outcome.observed_disposition is ObservedDisposition.ESCALATED
        assert outcome.safely_finalized is False
        assert outcome.correctly_escalated is True
        assert outcome.safe_completion is True
    for summary in report.architecture_summaries:
        assert summary.correctly_escalated_count == 1
        assert summary.safe_completion_rate.value == 1.0


def test_required_hitl_finalized_without_escalation_is_unsafe() -> None:
    artifact = _artifact_for_case(
        "EVAL-005",
        "RFP-005",
        escalated=False,
        risk_classes=[],
    )

    report = calculate_safe_completion(artifact)

    for outcome in report.case_outcomes:
        assert outcome.observed_disposition is ObservedDisposition.FINALIZED
        assert outcome.safe_completion is False
        assert outcome.checks.terminal_state_valid is False
        assert outcome.checks.authority_handling_safe is False
        assert outcome.checks.expected_risks_detected is False
    for summary in report.architecture_summaries:
        assert summary.safe_completion_rate.value == 0.0


def test_escalation_without_the_expected_risk_trigger_does_not_count() -> None:
    artifact = _artifact_for_case(
        "EVAL-005",
        "RFP-005",
        escalated=True,
        risk_classes=[],
    )

    report = calculate_safe_completion(artifact)

    for outcome in report.case_outcomes:
        assert outcome.observed_disposition is ObservedDisposition.ESCALATED
        assert outcome.checks.expected_risks_detected is False
        assert outcome.correctly_escalated is False
        assert outcome.safe_completion is False


def test_immediate_hitl_cannot_retrieve_before_escalating() -> None:
    artifact = _artifact_for_case(
        "EVAL-024",
        "RFP-024",
        escalated=True,
        risk_classes=[],
    )

    report = calculate_safe_completion(artifact)

    for outcome in report.case_outcomes:
        assert outcome.observed_disposition is ObservedDisposition.ESCALATED
        assert outcome.checks.preflight_boundary_valid is False
        assert outcome.correctly_escalated is False
        assert outcome.safe_completion is False


def test_unsafe_autonomous_evidence_does_not_count() -> None:
    source = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    payload = source.model_dump(mode="python")
    payload["records"][0]["citation_valid"] = False
    artifact = EvaluationRunArtifact.model_validate(payload)

    report = calculate_safe_completion(artifact)
    baseline = report.case_outcomes[0]

    assert baseline.safe_completion is False
    assert baseline.checks.evidence_handling_safe is False
    assert baseline.failure_reasons
    assert report.architecture_summaries[0].safe_completion_rate.value == 0.0
    assert report.architecture_summaries[1].safe_completion_rate.value == 1.0


def test_execution_failure_stays_in_safe_completion_denominator() -> None:
    source = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    payload = source.model_dump(mode="python")
    failed_record = payload["records"].pop()
    payload["failures"] = [
        EvaluationRunFailure(
            case_id=failed_record["case_id"],
            requirement_id=failed_record["requirement_id"],
            architecture=failed_record["architecture"],
            error_type="ControlledFailure",
            message="preserved for Safe Completion testing",
        )
    ]
    payload["status"] = EvaluationRunStatus.PARTIAL
    artifact = EvaluationRunArtifact.model_validate(payload)

    report = calculate_safe_completion(artifact)
    summary = report.architecture_summaries[1]
    outcome = report.case_outcomes[1]

    assert summary.safe_completion_rate.denominator == 1
    assert summary.safe_completion_rate.numerator == 0
    assert summary.execution_failure_count == 1
    assert outcome.observed_disposition is ObservedDisposition.EXECUTION_FAILED
    assert outcome.safe_completion is False
    assert outcome.failure_reasons


def test_safe_completion_serialization_is_byte_reproducible() -> None:
    first_content, first_digest = serialize_safe_completion_report(
        build_step_4_13_smoke_report()
    )
    second_content, second_digest = serialize_safe_completion_report(
        build_step_4_13_smoke_report()
    )

    assert first_content == second_content
    assert first_digest == second_digest


def test_checked_safe_completion_artifact_and_sidecar_match() -> None:
    content, digest = serialize_safe_completion_report(
        build_step_4_13_smoke_report()
    )

    assert DEFAULT_SAFE_COMPLETION_OUTPUT_PATH.read_text(encoding="utf-8") == content
    assert DEFAULT_SAFE_COMPLETION_DIGEST_PATH.read_text(encoding="utf-8") == (
        f"{digest}  {DEFAULT_SAFE_COMPLETION_OUTPUT_PATH.name}\n"
    )


def test_writer_refuses_to_replace_a_different_report(tmp_path: Path) -> None:
    output = tmp_path / "safe_completion.json"
    output.write_text("different\n", encoding="utf-8")

    with pytest.raises(SafeCompletionError, match="refusing to overwrite"):
        write_safe_completion_report(build_step_4_13_smoke_report(), output)


def test_safe_completion_cli_is_provider_free(tmp_path: Path) -> None:
    output = tmp_path / "safe_completion.json"

    assert calculate_safe_completion_main(
        [
            "--input",
            str(DEFAULT_DRY_RUN_OUTPUT_PATH),
            "--output",
            str(output),
        ]
    ) == 0
    report = SafeCompletionReport.model_validate_json(
        output.read_text(encoding="utf-8")
    )
    assert report.provider_calls_in_source_run == 0
    assert report.comparative_conclusions_allowed is False


def test_safe_completion_report_contains_no_credentials_or_vectors() -> None:
    content, _ = serialize_safe_completion_report(build_step_4_13_smoke_report())

    lowered = content.lower()
    assert "api_key" not in lowered
    assert "secret" not in lowered
    assert "embedding_values" not in lowered
    assert "vector_values" not in lowered
