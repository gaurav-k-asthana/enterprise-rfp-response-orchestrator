from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.citation_validation import citation_validation_node
from rfp_orchestrator.claim_support import (
    ClaimSupportIssueType,
    ClaimSupportValidationResult,
    adjudicate_atomic_claims,
    claim_support_validation_node,
)
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.source_validation import source_validation_node
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


def fixed_clock() -> str:
    return "2026-08-30T12:00:00Z"


def live_state(requirement_id: str, text: str) -> dict:
    graph = build_selected_fanout_graph(
        build_offline_retrievers(KB_DIRECTORY),
        event_clock=fixed_clock,
    )
    return graph.invoke(new_requirement_state("case-1", requirement_id, text))


def refresh_upstream_gates(state: dict) -> None:
    state.update(citation_validation_node(state))
    state.update(source_validation_node(state))


def issue_types(result: ClaimSupportValidationResult) -> list[ClaimSupportIssueType]:
    return [issue.issue_type for issue in result.issues]


def test_live_supported_claims_are_independently_adjudicated() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")

    assert state["claim_support_valid"] is True
    validation = state["claim_support_validation"]
    assert validation["support_status_by_specialist"] == {"product": "SUPPORTED"}
    assert [claim["supported"] for claim in validation["assessments"][0]["claims"]] == [
        True,
        True,
    ]
    assert all(
        claim["lexical_coverage"] >= 0.70
        for claim in validation["assessments"][0]["claims"]
    )


def test_live_parallel_outputs_are_assessed_separately() -> None:
    state = live_state(
        "RFP-002",
        (
            "Describe customer-managed encryption keys and identify supported "
            "deployment environments."
        ),
    )

    assert state["claim_support_valid"] is True
    assert state["claim_support_validation"]["support_status_by_specialist"] == {
        "product": "SUPPORTED",
        "security": "SUPPORTED",
    }


def test_honestly_unsupported_claim_is_a_valid_assessment() -> None:
    state = live_state(
        "RFP-021",
        "Confirm that Northstar is authorized for FedRAMP High.",
    )

    assert state["claim_support_valid"] is True
    assert state["claim_support_validation"]["issues"] == []
    assert state["specialist_outputs"]["security"]["claims"][0]["supported"] is False
    assert state["claim_support_validation"]["support_status_by_specialist"] == {
        "security": "UNSUPPORTED"
    }


def test_mixed_atomic_claims_aggregate_to_partial() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    output = state["specialist_outputs"]["product"]
    output["claims"][1]["evidence_ids"] = []
    output["claims"][1]["supported"] = False
    output["support_status"] = "PARTIAL"
    refresh_upstream_gates(state)

    result, corrected = adjudicate_atomic_claims(state)

    assert result.valid is True
    assert result.support_status_by_specialist == {"product": "PARTIAL"}
    assert [claim["supported"] for claim in corrected["product"]["claims"]] == [
        True,
        False,
    ]


def test_nonblank_draft_without_atomic_claims_is_unsupported_and_invalid() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    output = state["specialist_outputs"]["product"]
    output["claims"] = []
    output["support_status"] = "UNSUPPORTED"
    refresh_upstream_gates(state)

    result, corrected = adjudicate_atomic_claims(state)

    assert result.valid is False
    assert result.support_status_by_specialist == {"product": "UNSUPPORTED"}
    assert corrected["product"]["claims"] == []
    assert ClaimSupportIssueType.MISSING_ATOMIC_CLAIMS in issue_types(result)


def test_unrelated_claim_text_is_not_supported_by_a_valid_citation() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    state["specialist_outputs"]["product"]["claims"][0]["text"] = (
        "Northstar is authorized for FedRAMP High."
    )
    refresh_upstream_gates(state)

    result, corrected = adjudicate_atomic_claims(state)

    assert corrected["product"]["claims"][0]["supported"] is False
    assert ClaimSupportIssueType.EVIDENCE_DOES_NOT_SUPPORT_CLAIM in issue_types(result)
    assert ClaimSupportIssueType.PROVISIONAL_SUPPORT_MISMATCH in issue_types(result)


def test_numeric_anchor_must_appear_in_evidence() -> None:
    state = live_state(
        "RFP-005",
        "Commit to 99.99% monthly uptime and service credits.",
    )
    claim = state["specialist_outputs"]["product"]["claims"][0]
    claim["text"] = claim["text"].replace("99.9%", "99.99%")
    refresh_upstream_gates(state)

    result, corrected = adjudicate_atomic_claims(state)

    assert corrected["product"]["claims"][0]["supported"] is False
    assert ClaimSupportIssueType.EVIDENCE_DOES_NOT_SUPPORT_CLAIM in issue_types(result)


def test_provisional_boolean_is_checked_not_trusted() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    state["specialist_outputs"]["product"]["claims"][0]["supported"] = False
    refresh_upstream_gates(state)

    result, corrected = adjudicate_atomic_claims(state)

    assert corrected["product"]["claims"][0]["supported"] is True
    assert issue_types(result) == [ClaimSupportIssueType.PROVISIONAL_SUPPORT_MISMATCH]


def test_incorrect_aggregate_status_is_recomputed_and_reported() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    output = state["specialist_outputs"]["product"]
    output["claims"][1]["evidence_ids"] = []
    output["claims"][1]["supported"] = False
    refresh_upstream_gates(state)

    result, corrected = adjudicate_atomic_claims(state)

    assert corrected["product"]["support_status"] == "PARTIAL"
    assert issue_types(result) == [ClaimSupportIssueType.AGGREGATE_STATUS_MISMATCH]


@pytest.mark.parametrize(
    ("field", "value", "expected_issue"),
    [
        ("claim_id", "", ClaimSupportIssueType.BLANK_CLAIM_ID),
        ("text", "   ", ClaimSupportIssueType.BLANK_CLAIM_TEXT),
        ("supported", "yes", ClaimSupportIssueType.INVALID_PROVISIONAL_SUPPORT),
    ],
)
def test_invalid_atomic_claim_fields_fail_closed(
    field: str,
    value,
    expected_issue: ClaimSupportIssueType,
) -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    state["specialist_outputs"]["product"]["claims"][0][field] = value
    refresh_upstream_gates(state)

    result, _ = adjudicate_atomic_claims(state)

    assert result.valid is False
    assert expected_issue in issue_types(result)


@pytest.mark.parametrize(
    ("field", "expected_issue"),
    [
        ("claim_id", ClaimSupportIssueType.DUPLICATE_CLAIM_ID),
        ("text", ClaimSupportIssueType.DUPLICATE_CLAIM_TEXT),
    ],
)
def test_duplicate_atomic_claim_identity_or_text_fails_closed(
    field: str,
    expected_issue: ClaimSupportIssueType,
) -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    claims = state["specialist_outputs"]["product"]["claims"]
    claims[1][field] = claims[0][field]
    refresh_upstream_gates(state)

    result, _ = adjudicate_atomic_claims(state)

    assert result.valid is False
    assert expected_issue in issue_types(result)


def test_ineligible_archived_citation_cannot_support_claim() -> None:
    state = live_state(
        "RFP-008",
        "State the supported TLS versions for application and API connections.",
    )
    archived_id = next(
        item["chunk_id"]
        for item in state["evidence"]
        if item["source_status"] == "archived"
    )
    state["specialist_outputs"]["security"]["claims"][0]["evidence_ids"] = [
        archived_id
    ]
    refresh_upstream_gates(state)

    result, corrected = adjudicate_atomic_claims(state)

    assert corrected["security"]["claims"][0]["supported"] is False
    assert ClaimSupportIssueType.UPSTREAM_SOURCE_INVALID in issue_types(result)
    assert ClaimSupportIssueType.INELIGIBLE_EVIDENCE in issue_types(result)


def test_invalid_upstream_citation_prevents_claim_gate_from_passing() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    state["citation_valid"] = False

    result, _ = adjudicate_atomic_claims(state)

    assert result.valid is False
    assert issue_types(result)[0] is ClaimSupportIssueType.UPSTREAM_CITATION_INVALID


def test_claim_node_updates_adjudicated_outputs_without_finalizing() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    original_answer = deepcopy(state["specialist_outputs"]["product"]["proposed_answer"])

    update = claim_support_validation_node(state)

    assert update["claim_support_valid"] is True
    assert update["specialist_outputs"]["product"]["proposed_answer"] == original_answer
    assert update["merged_specialist_outputs"][0]["support_status"] == "SUPPORTED"
    assert "final_answer" not in update


def test_claim_support_events_follow_source_validation() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    pairs = [(event["node"], event["status"]) for event in state["execution_events"]]

    assert pairs.index(
        (GraphNode.CLAIM_SUPPORT_VALIDATION.value, "active")
    ) > pairs.index((GraphNode.SOURCE_VALIDATION.value, "complete"))
    assert pairs.index(
        (GraphNode.CLAIM_SUPPORT_VALIDATION.value, "complete")
    ) < pairs.index((GraphNode.RECOVERY_PLANNING.value, "active"))


def test_result_rejects_inconsistent_valid_flag_or_status_map() -> None:
    with pytest.raises(ValidationError, match="valid exactly when issues are empty"):
        ClaimSupportValidationResult(valid=False, issues=[])

    with pytest.raises(ValidationError, match="status map"):
        ClaimSupportValidationResult(
            valid=True,
            support_status_by_specialist={"product": "SUPPORTED"},
        )
