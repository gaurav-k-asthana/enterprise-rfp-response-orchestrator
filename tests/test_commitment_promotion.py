from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.commitment_promotion import (
    AuthoritativeCommitment,
    CommitmentPromotionError,
    CommitmentPromotionStatus,
    commitment_promotion_node,
    promote_approved_commitments,
)
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


def graph():
    return build_selected_fanout_graph(
        build_offline_retrievers(KB_DIRECTORY),
        event_clock=lambda: "fixed",
    )


def saml_state():
    return graph().invoke(
        new_requirement_state(
            "case-1",
            "RFP-001",
            "Confirm support for SAML 2.0 and SCIM 2.0.",
        )
    )


def approval(decision: str = "APPROVE", requirement_id: str = "RFP-001"):
    payload = {
        "requirement_id": requirement_id,
        "decision": decision,
        "reviewer": "reviewer@example.test",
        "timestamp": "2026-08-30T13:00:00Z",
    }
    if decision == "EDIT_AND_APPROVE":
        payload["edited_answer"] = "Approved edited response."
    if decision == "ADD_GUIDANCE":
        payload["guidance"] = "Revise before approval."
    return payload


def selected_state(*, decision: str | None = None, finalized: bool = False):
    state = saml_state()
    state["final_status"] = None
    state["approved_proposal_ids"] = [
        state["proposed_commitments"][0]["proposal_id"]
    ]
    if decision is not None:
        state["approval"] = approval(decision)
    if finalized:
        state["final_status"] = "FINALIZED"
    return state


def test_live_unreviewed_path_records_no_selection_and_no_authoritative_memory() -> None:
    state = saml_state()

    assert state["commitment_promotion"]["status"] == "NO_SELECTION"
    assert state["approved_proposal_ids"] == []
    assert state["commitments"] == []


def test_selected_proposal_without_human_decision_awaits_approval() -> None:
    result, ledger = promote_approved_commitments(selected_state())

    assert result.status is CommitmentPromotionStatus.AWAITING_APPROVAL
    assert ledger == []


def test_approved_proposal_without_final_status_awaits_finalization() -> None:
    result, ledger = promote_approved_commitments(
        selected_state(decision="APPROVE")
    )

    assert result.status is CommitmentPromotionStatus.AWAITING_FINALIZATION
    assert ledger == []


def test_final_status_without_human_decision_still_awaits_approval() -> None:
    result, ledger = promote_approved_commitments(selected_state(finalized=True))

    assert result.status is CommitmentPromotionStatus.AWAITING_APPROVAL
    assert ledger == []


@pytest.mark.parametrize(
    "decision",
    ["REJECT", "ADD_GUIDANCE", "REQUEST_RETRY"],
)
def test_non_approving_human_decisions_block_promotion(decision: str) -> None:
    result, ledger = promote_approved_commitments(
        selected_state(decision=decision, finalized=True)
    )

    assert result.status is CommitmentPromotionStatus.BLOCKED
    assert ledger == []


@pytest.mark.parametrize("decision", ["APPROVE", "EDIT_AND_APPROVE"])
def test_approving_decision_plus_finalization_promotes_selected_proposal(
    decision: str,
) -> None:
    state = selected_state(decision=decision, finalized=True)

    result, ledger = promote_approved_commitments(state)

    assert result.status is CommitmentPromotionStatus.PROMOTED
    assert len(ledger) == 1
    authoritative = ledger[0]
    assert authoritative.proposal_id == state["approved_proposal_ids"][0]
    assert authoritative.approved is True
    assert authoritative.final_status == "FINALIZED"
    assert authoritative.approval_decision.value == decision
    assert authoritative.approved_by == "reviewer@example.test"
    assert authoritative.approved_at == "2026-08-30T13:00:00Z"


def test_only_explicitly_selected_proposal_is_promoted() -> None:
    state = selected_state(decision="APPROVE", finalized=True)
    assert len(state["proposed_commitments"]) == 2

    _, ledger = promote_approved_commitments(state)

    assert [item.proposal_id for item in ledger] == state["approved_proposal_ids"]
    assert state["proposed_commitments"][1]["approved"] is False
    assert state["proposed_commitments"][1]["authoritative"] is False


def test_promotion_node_writes_authoritative_memory_only_after_success() -> None:
    pending = selected_state(decision="APPROVE")
    promoted = selected_state(decision="APPROVE", finalized=True)

    pending_update = commitment_promotion_node(pending)
    promoted_update = commitment_promotion_node(promoted)

    assert pending_update["commitment_promotion"]["status"] == (
        "AWAITING_FINALIZATION"
    )
    assert "commitments" not in pending_update
    assert promoted_update["commitment_promotion"]["status"] == "PROMOTED"
    assert promoted_update["commitments"][0]["approved"] is True


def test_promotion_is_idempotent_for_the_same_proposal_and_approval() -> None:
    state = selected_state(decision="APPROVE", finalized=True)
    first_result, first_ledger = promote_approved_commitments(state)
    state["commitments"] = [item.model_dump(mode="json") for item in first_ledger]

    second_result, second_ledger = promote_approved_commitments(state)

    assert first_result.status is CommitmentPromotionStatus.PROMOTED
    assert second_result.status is CommitmentPromotionStatus.PROMOTED
    assert len(second_ledger) == 1
    assert second_ledger == first_ledger


@pytest.mark.parametrize(
    "unsafe_ids",
    [
        ["unknown-proposal"],
        ["duplicate", "duplicate"],
        [""],
        "not-a-list",
    ],
)
def test_invalid_or_unknown_selection_fails_closed(unsafe_ids) -> None:
    state = saml_state()
    state["approved_proposal_ids"] = unsafe_ids

    with pytest.raises(CommitmentPromotionError):
        promote_approved_commitments(state)


def test_approval_for_another_requirement_fails_closed() -> None:
    state = selected_state(finalized=True)
    state["approval"] = approval(requirement_id="RFP-OTHER")

    with pytest.raises(CommitmentPromotionError, match="does not match"):
        promote_approved_commitments(state)


def test_malformed_approval_and_final_status_fail_closed() -> None:
    malformed_approval = selected_state(finalized=True)
    malformed_approval["approval"] = {"decision": "APPROVE"}
    invalid_status = selected_state(decision="APPROVE")
    invalid_status["final_status"] = "NOT_A_STATUS"

    with pytest.raises(CommitmentPromotionError, match="approval state"):
        promote_approved_commitments(malformed_approval)
    with pytest.raises(CommitmentPromotionError, match="final_status"):
        promote_approved_commitments(invalid_status)


def test_unapproved_record_already_in_authoritative_memory_fails_closed() -> None:
    state = saml_state()
    state["commitments"] = [
        {
            "proposal_id": "old-proposal",
            "commitment_type": "UPTIME_SLA",
            "normalized_value": "99.9-percent",
            "source_requirement_id": "RFP-OLD",
            "source_claim_id": "old-claim",
            "specialist": "product",
            "evidence_ids": ["old-evidence"],
            "approved": False,
            "approval_decision": "APPROVE",
            "approved_by": "reviewer@example.test",
            "approved_at": "2026-08-29T12:00:00Z",
            "final_status": "FINALIZED",
        }
    ]

    with pytest.raises(CommitmentPromotionError, match="unapproved"):
        promote_approved_commitments(state)


def test_conflicting_existing_record_for_same_proposal_fails_closed() -> None:
    state = selected_state(decision="APPROVE", finalized=True)
    _, ledger = promote_approved_commitments(state)
    record = ledger[0].model_dump(mode="json")
    record["normalized_value"] = "tampered-value"
    state["commitments"] = [record]

    with pytest.raises(CommitmentPromotionError, match="conflicts"):
        promote_approved_commitments(state)


@pytest.mark.parametrize(
    "unsafe_update",
    [
        {"approved": False},
        {"approval_decision": "REJECT"},
        {"evidence_ids": []},
        {"final_status": "REJECTED"},
    ],
)
def test_authoritative_model_rejects_unapproved_or_incomplete_records(
    unsafe_update: dict,
) -> None:
    payload = {
        "proposal_id": "RFP-001:product:claim-001:SUPPORTED_INTEGRATION",
        "commitment_type": "SUPPORTED_INTEGRATION",
        "normalized_value": "saml-2.0:ga:enterprise-cloud",
        "source_requirement_id": "RFP-001",
        "source_claim_id": "claim-001",
        "specialist": "product",
        "evidence_ids": ["evidence-001"],
        "approved": True,
        "approval_decision": "APPROVE",
        "approved_by": "reviewer@example.test",
        "approved_at": "2026-08-30T13:00:00Z",
        "final_status": "FINALIZED",
    }
    payload.update(unsafe_update)

    with pytest.raises(ValidationError):
        AuthoritativeCommitment.model_validate(payload)


def test_exhausted_recovery_never_reaches_promotion_gate() -> None:
    state = graph().invoke(
        new_requirement_state(
            "case-1",
            "RFP-021",
            "Confirm that Northstar is authorized for FedRAMP High.",
        )
    )
    event_nodes = [item["node"] for item in state["execution_events"]]

    assert state["recovery_exhausted"] is True
    assert state["commitment_promotion"] is None
    assert state["commitments"] == []
    assert GraphNode.COMMITMENT_PROMOTION.value not in event_nodes
