import json
from datetime import datetime
from pathlib import Path

import pytest

from rfp_orchestrator.evaluation_freeze import file_sha256
from rfp_orchestrator.evaluation_trials import (
    ADDITIONAL_REPEAT_COUNT,
    DEFAULT_PRICING_SNAPSHOT_PATH,
    DEFAULT_REPEAT_TRIAL_APPROVAL_PATH,
    DEFAULT_REPEAT_TRIAL_PLAN_PATH,
    DEFAULT_REPEAT_TRIAL_REVIEW_PATH,
    SELECTED_REPEAT_CASE_IDS,
    TOTAL_TRIALS_PER_SELECTED_CASE,
    EvaluationTrialPlanError,
    TrialPlanStatus,
    approve_repeat_trial_plan,
    build_repeat_trial_approval_record,
    build_repeat_trial_proposal,
    load_repeat_trial_approval,
    load_repeat_trial_plan,
    require_provider_execution_approval,
    serialize_repeat_trial_approval,
    serialize_repeat_trial_plan,
    validate_trial_request,
    write_repeat_trial_approval,
    write_repeat_trial_proposal,
)
from scripts.prepare_repeat_trial_plan import main as prepare_main
from scripts.record_repeat_trial_approval import main as approval_main


def test_repeat_subset_is_small_predefined_and_ordered() -> None:
    plan = build_repeat_trial_proposal()
    assert tuple(case.case_id for case in plan.repeat_cases) == SELECTED_REPEAT_CASE_IDS
    assert len(plan.repeat_cases) == 4
    assert plan.total_trials_per_selected_case == TOTAL_TRIALS_PER_SELECTED_CASE
    assert plan.additional_repeat_count == ADDITIONAL_REPEAT_COUNT


def test_repeat_subset_covers_only_meaningful_variability() -> None:
    plan = build_repeat_trial_proposal()
    dimensions = {
        dimension.value
        for case in plan.repeat_cases
        for dimension in case.variability_dimensions
    }
    assert dimensions == {
        "SIMPLE_STABILITY_CONTROL",
        "ROUTING_AND_TOOL_SELECTION",
        "CONFLICT_AND_AUTHORITY_ESCALATION",
        "EVIDENCE_GAP_AND_BOUNDED_RECOVERY",
    }
    assert plan.excluded_deterministic_stop_case_ids == ["EVAL-023", "EVAL-024"]


def test_execution_counts_are_exact() -> None:
    plan = build_repeat_trial_proposal()
    assert plan.primary_architecture_execution_count == 24 * 2
    assert plan.additional_repeat_architecture_execution_count == 4 * 2 * 2
    assert plan.max_total_architecture_execution_count == 64


def test_budget_is_derived_from_frozen_pricing_and_token_caps() -> None:
    plan = build_repeat_trial_proposal()
    budget = plan.budget
    assert budget.pricing_snapshot_sha256 == file_sha256(DEFAULT_PRICING_SNAPSHOT_PATH)
    assert budget.max_total_input_tokens == 128 * 8000
    assert budget.max_total_output_tokens == 128 * 2000
    calculated = (
        budget.max_total_input_tokens * budget.input_usd_per_million_tokens
        + budget.max_total_output_tokens * budget.output_usd_per_million_tokens
    ) / 1_000_000
    assert calculated == pytest.approx(5.12)
    assert budget.proposed_hard_cost_cap_usd == 5.12


def test_unapproved_plan_authorizes_zero_spend_and_calls() -> None:
    plan = build_repeat_trial_proposal()
    assert plan.status is TrialPlanStatus.AWAITING_APPROVAL
    assert plan.budget.currently_authorized_cost_usd == 0
    assert plan.provider_execution_authorized is False
    assert plan.provider_calls_made == 0
    with pytest.raises(EvaluationTrialPlanError, match="explicit approval"):
        require_provider_execution_approval(plan)


def test_primary_trial_allows_every_frozen_case() -> None:
    plan = build_repeat_trial_proposal()
    for case_id in plan.primary_case_ids:
        validate_trial_request(plan, case_id=case_id, trial_number=1)


def test_additional_trials_allow_only_repeat_subset() -> None:
    plan = build_repeat_trial_proposal()
    for case_id in SELECTED_REPEAT_CASE_IDS:
        validate_trial_request(plan, case_id=case_id, trial_number=2)
        validate_trial_request(plan, case_id=case_id, trial_number=3)
    with pytest.raises(EvaluationTrialPlanError, match="not in the predefined"):
        validate_trial_request(plan, case_id="EVAL-003", trial_number=2)


def test_trial_number_and_unknown_case_fail_closed() -> None:
    plan = build_repeat_trial_proposal()
    with pytest.raises(EvaluationTrialPlanError, match="at least one"):
        validate_trial_request(plan, case_id="EVAL-001", trial_number=0)
    with pytest.raises(EvaluationTrialPlanError, match="frozen maximum"):
        validate_trial_request(plan, case_id="EVAL-001", trial_number=4)
    with pytest.raises(EvaluationTrialPlanError, match="unknown frozen"):
        validate_trial_request(plan, case_id="EVAL-999", trial_number=1)


def test_approval_requires_named_reviewer_timezone_and_bounded_cap() -> None:
    plan = build_repeat_trial_proposal()
    aware = datetime.fromisoformat("2026-09-14T13:00:00-04:00")
    with pytest.raises(EvaluationTrialPlanError, match="reviewer"):
        approve_repeat_trial_plan(plan, reviewer=" ", approved_at=aware, authorized_cost_usd=5.12)
    with pytest.raises(EvaluationTrialPlanError, match="timezone"):
        approve_repeat_trial_plan(
            plan,
            reviewer="Gaurav Asthana",
            approved_at=datetime.fromisoformat("2026-09-14T13:00:00"),
            authorized_cost_usd=5.12,
        )
    with pytest.raises(EvaluationTrialPlanError, match="no greater"):
        approve_repeat_trial_plan(plan, reviewer="Gaurav Asthana", approved_at=aware, authorized_cost_usd=5.13)


def test_bounded_explicit_approval_unlocks_only_the_plan_gate() -> None:
    approved = approve_repeat_trial_plan(
        build_repeat_trial_proposal(),
        reviewer="Gaurav Asthana",
        approved_at=datetime.fromisoformat("2026-09-14T13:00:00-04:00"),
        authorized_cost_usd=5.12,
    )
    assert approved.status is TrialPlanStatus.APPROVED
    assert approved.approved_by == "Gaurav Asthana"
    assert approved.budget.currently_authorized_cost_usd == 5.12
    require_provider_execution_approval(approved)


def test_serialization_is_deterministic_and_secret_free() -> None:
    first, first_digest = serialize_repeat_trial_plan(build_repeat_trial_proposal())
    second, second_digest = serialize_repeat_trial_plan(build_repeat_trial_proposal())
    assert (first, first_digest) == (second, second_digest)
    lowered = first.lower()
    assert "api_key" not in lowered
    assert "pinecone_host" not in lowered
    assert "vector_values" not in lowered


def test_writer_creates_plan_sidecar_and_review_packet(tmp_path: Path) -> None:
    output = tmp_path / "plan.json"
    review = tmp_path / "review.md"
    _, digest = write_repeat_trial_proposal(
        build_repeat_trial_proposal(), output_path=output, review_path=review
    )
    assert output.with_suffix(".sha256").read_text() == f"{digest}  plan.json\n"
    review_text = review.read_text()
    assert "Currently authorized spend: $0.00" in review_text
    assert "EVAL-023 and EVAL-024 are not repeated" in review_text


def test_writer_refuses_to_replace_different_plan(tmp_path: Path) -> None:
    output = tmp_path / "plan.json"
    review = tmp_path / "review.md"
    output.write_text("different\n")
    with pytest.raises(EvaluationTrialPlanError, match="refusing to overwrite"):
        write_repeat_trial_proposal(
            build_repeat_trial_proposal(), output_path=output, review_path=review
        )


def test_checked_in_proposal_matches_builder_after_generation() -> None:
    expected = build_repeat_trial_proposal()
    assert load_repeat_trial_plan() == expected
    content, digest = serialize_repeat_trial_plan(expected)
    assert DEFAULT_REPEAT_TRIAL_PLAN_PATH.read_text() == content
    assert DEFAULT_REPEAT_TRIAL_PLAN_PATH.with_suffix(".sha256").read_text() == (
        f"{digest}  {DEFAULT_REPEAT_TRIAL_PLAN_PATH.name}\n"
    )
    assert DEFAULT_REPEAT_TRIAL_REVIEW_PATH.read_text().startswith(
        "# Repeat-Trial Plan — V1 Review Packet"
    )


def test_cli_prepares_proposal_without_provider_execution(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "plan.json"
    review = tmp_path / "review.md"
    assert prepare_main(["--output", str(output), "--review-output", str(review)]) == 0
    stdout = capsys.readouterr().out
    assert "Currently authorized spend: $0.00" in stdout
    assert "Provider execution authorized: no" in stdout
    assert "Provider calls made: 0" in stdout
    payload = json.loads(output.read_text())
    assert payload["comparative_runs_completed"] == 0


def test_approval_record_references_exact_proposal_without_running_it() -> None:
    plan = build_repeat_trial_proposal()
    _, proposal_digest = serialize_repeat_trial_plan(plan)
    approval = build_repeat_trial_approval_record(
        plan,
        expected_proposal_sha256=proposal_digest,
        reviewer="Gaurav Asthana",
        approved_at=datetime.fromisoformat("2026-09-14T16:04:35-04:00"),
        authorized_cost_usd=5.12,
    )
    assert approval.proposal_sha256 == proposal_digest
    assert approval.approved_by == "Gaurav Asthana"
    assert approval.authorized_cost_usd == 5.12
    assert approval.budget_authorized is True
    assert approval.paid_command_approved is False
    assert approval.provider_calls_made == 0


def test_approval_record_rejects_unapproved_proposal_digest() -> None:
    with pytest.raises(EvaluationTrialPlanError, match="does not match"):
        build_repeat_trial_approval_record(
            build_repeat_trial_proposal(),
            expected_proposal_sha256="0" * 64,
            reviewer="Gaurav Asthana",
            approved_at=datetime.fromisoformat("2026-09-14T16:04:35-04:00"),
            authorized_cost_usd=5.12,
        )


def test_approval_writer_is_content_addressed(tmp_path: Path) -> None:
    plan = build_repeat_trial_proposal()
    _, proposal_digest = serialize_repeat_trial_plan(plan)
    approval = build_repeat_trial_approval_record(
        plan,
        expected_proposal_sha256=proposal_digest,
        reviewer="Gaurav Asthana",
        approved_at=datetime.fromisoformat("2026-09-14T16:04:35-04:00"),
        authorized_cost_usd=5.12,
    )
    output = tmp_path / "approval.json"
    _, approval_digest = write_repeat_trial_approval(approval, output_path=output)
    assert output.with_suffix(".sha256").read_text() == (
        f"{approval_digest}  approval.json\n"
    )
    write_repeat_trial_approval(approval, output_path=output)
    output.write_text("different\n")
    with pytest.raises(EvaluationTrialPlanError, match="refusing to overwrite"):
        write_repeat_trial_approval(approval, output_path=output)


def test_checked_in_approval_matches_explicit_user_authorization() -> None:
    approval = load_repeat_trial_approval()
    assert approval.proposal_sha256 == (
        "77acb469316289d92871d8450d35f7975d5b2cddbead1f6a81f710b6a5f88b2a"
    )
    assert approval.approved_by == "Gaurav Asthana"
    assert approval.authorized_cost_usd == 5.12
    content, digest = serialize_repeat_trial_approval(approval)
    assert DEFAULT_REPEAT_TRIAL_APPROVAL_PATH.read_text() == content
    assert DEFAULT_REPEAT_TRIAL_APPROVAL_PATH.with_suffix(".sha256").read_text() == (
        f"{digest}  {DEFAULT_REPEAT_TRIAL_APPROVAL_PATH.name}\n"
    )


def test_approval_cli_records_provenance_but_makes_no_call(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output = tmp_path / "approval.json"
    assert approval_main(
        [
            "--expected-plan-sha256",
            "77acb469316289d92871d8450d35f7975d5b2cddbead1f6a81f710b6a5f88b2a",
            "--reviewer",
            "Gaurav Asthana",
            "--approved-at",
            "2026-09-14T16:04:35-04:00",
            "--authorized-cost-usd",
            "5.12",
            "--output",
            str(output),
        ]
    ) == 0
    stdout = capsys.readouterr().out
    assert "Paid command approved: no" in stdout
    assert "Provider calls made: 0" in stdout
    assert json.loads(output.read_text())["comparative_runs_completed"] == 0
