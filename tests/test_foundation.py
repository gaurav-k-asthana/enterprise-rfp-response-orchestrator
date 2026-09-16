import pytest
from pydantic import ValidationError

from rfp_orchestrator.config import Settings
from rfp_orchestrator.models import (
    ApprovalDecision,
    Commitment,
    CommitmentType,
    Domain,
    HumanApproval,
    Requirement,
    RiskAssessment,
    RiskClass,
)
from rfp_orchestrator.retrieval import enforce_top_k
from rfp_orchestrator.state import new_requirement_state


def test_locked_limits_are_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.max_retrieval_retries == 2
    assert settings.retrieval_top_k == 5


def test_retry_limit_cannot_exceed_two() -> None:
    with pytest.raises(ValueError):
        Settings(_env_file=None, max_retrieval_retries=3)


def test_new_state_is_explicit_and_empty() -> None:
    state = new_requirement_state("case-1", "q-1", "Does it support SAML?")
    assert state["retry_count"] == 0
    assert state["specialist_outputs"] == {}
    assert state["proposed_commitments"] == []
    assert state["commitment_extraction"] is None
    assert state["commitment_consistent"] is None
    assert state["commitment_consistency"] is None
    assert state["conflict_resolution"] is None
    assert state["conflict_reanalysis_count"] == 0
    assert state["conflict_resolution_attempts"] == []
    assert state["conflict_unresolved"] is False
    assert state["risk_assessment"] is None
    assert state["authority_required"] is False
    assert state["authority_owners"] == []
    assert state["authority_gate_passed"] is None
    assert state["human_review_request"] is None
    assert state["awaiting_human_review"] is False
    assert state["approved_proposal_ids"] == []
    assert state["commitment_promotion"] is None
    assert state["commitments"] == []
    assert state["execution_events"] == []


def test_top_k_guard() -> None:
    assert enforce_top_k(5) == 5
    with pytest.raises(ValueError):
        enforce_top_k(6)


def test_requirement_uses_typed_domains() -> None:
    requirement = Requirement(
        requirement_id="q-1",
        original_text="Confirm support for SAML.",
        assigned_domains=[Domain.PRODUCT, Domain.SECURITY],
    )
    assert requirement.assigned_domains == [Domain.PRODUCT, Domain.SECURITY]


def test_commitment_starts_unapproved() -> None:
    commitment = Commitment(
        commitment_type=CommitmentType.UPTIME_SLA,
        normalized_value="99.9%",
        source_requirement_id="q-2",
    )
    assert commitment.approved is False


def test_human_risk_requires_a_reason() -> None:
    with pytest.raises(ValidationError):
        RiskAssessment(
            risk_classes=[RiskClass.SLA_OR_SERVICE_CREDIT],
            requires_human=True,
        )


def test_edit_and_approve_requires_edited_answer() -> None:
    with pytest.raises(ValidationError):
        HumanApproval(
            requirement_id="q-3",
            decision=ApprovalDecision.EDIT_AND_APPROVE,
            reviewer="reviewer@example.test",
            timestamp="2026-08-29T12:00:00Z",
        )
