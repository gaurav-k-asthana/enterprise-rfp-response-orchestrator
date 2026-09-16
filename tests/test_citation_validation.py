from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.citation_validation import (
    CitationIssueType,
    CitationValidationResult,
    citation_validation_node,
    validate_citation_membership,
)
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.retrieval import build_offline_retrievers
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
    initial = new_requirement_state("case-1", requirement_id, text)
    return graph.invoke(initial)


def issue_types(result: CitationValidationResult) -> list[CitationIssueType]:
    return [issue.issue_type for issue in result.issues]


def test_live_single_specialist_citations_are_valid() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")

    assert state["citation_valid"] is True
    assert state["citation_validation"]["issues"] == []
    assert state["citation_validation"]["cited_evidence_ids"]


def test_live_parallel_citations_are_valid_across_distinct_branches() -> None:
    state = live_state(
        "RFP-002",
        (
            "Describe customer-managed encryption keys and identify supported "
            "deployment environments."
        ),
    )

    assert state["citation_valid"] is True
    assert {item["domain"] for item in state["evidence"]} == {
        "product",
        "security",
    }


def test_unsupported_claim_may_have_no_citation_without_structural_failure() -> None:
    state = live_state(
        "RFP-021",
        "Confirm that Northstar is authorized for FedRAMP High.",
    )

    claim = state["specialist_outputs"]["security"]["claims"][0]
    assert claim["supported"] is False
    assert claim["evidence_ids"] == []
    assert state["citation_valid"] is True


def test_provisionally_supported_claim_requires_a_citation() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    state["specialist_outputs"]["product"]["claims"][0]["evidence_ids"] = []

    result = validate_citation_membership(state)

    assert result.valid is False
    assert CitationIssueType.MISSING_CITATION in issue_types(result)


def test_unknown_citation_is_rejected() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    state["specialist_outputs"]["product"]["claims"][0]["evidence_ids"] = [
        "invented::chunk-999"
    ]

    result = validate_citation_membership(state)

    assert result.valid is False
    assert issue_types(result) == [CitationIssueType.UNKNOWN_CITATION]


def test_cross_specialist_citation_is_rejected() -> None:
    state = live_state(
        "RFP-002",
        (
            "Describe customer-managed encryption keys and identify supported "
            "deployment environments."
        ),
    )
    security_id = state["specialist_evidence"]["security"][0]["chunk_id"]
    state["specialist_outputs"]["product"]["claims"][0]["evidence_ids"] = [
        security_id
    ]

    result = validate_citation_membership(state)

    assert result.valid is False
    assert issue_types(result) == [CitationIssueType.CROSS_SPECIALIST_CITATION]


def test_duplicate_citation_in_one_claim_is_rejected() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    claim = state["specialist_outputs"]["product"]["claims"][0]
    claim["evidence_ids"] = [claim["evidence_ids"][0], claim["evidence_ids"][0]]

    result = validate_citation_membership(state)

    assert result.valid is False
    assert issue_types(result) == [CitationIssueType.DUPLICATE_CITATION]


def test_citation_retrieved_by_branch_but_missing_from_merge_is_rejected() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    cited_id = state["specialist_outputs"]["product"]["claims"][0][
        "evidence_ids"
    ][0]
    state["evidence"] = [
        item for item in state["evidence"] if item["chunk_id"] != cited_id
    ]

    result = validate_citation_membership(state)

    assert result.valid is False
    assert issue_types(result) == [
        CitationIssueType.NOT_IN_MERGED_EVIDENCE,
        CitationIssueType.NOT_IN_MERGED_EVIDENCE,
    ]
    assert {issue.claim_id for issue in result.issues} == {
        "product-claim-001",
        "product-claim-002",
    }


def test_duplicate_chunk_id_in_merged_evidence_is_rejected() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    state["evidence"].append(deepcopy(state["evidence"][0]))

    result = validate_citation_membership(state)

    assert result.valid is False
    assert CitationIssueType.DUPLICATE_EVIDENCE_ID in issue_types(result)


def test_validator_collects_multiple_issues_without_changing_claim_support() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    before = deepcopy(state["specialist_outputs"])
    claims = state["specialist_outputs"]["product"]["claims"]
    claims[0]["evidence_ids"] = []
    claims[1]["evidence_ids"] = ["invented::chunk-999"]
    mutated_support = [claim["supported"] for claim in claims]

    result = validate_citation_membership(state)

    assert result.valid is False
    assert set(issue_types(result)) == {
        CitationIssueType.MISSING_CITATION,
        CitationIssueType.UNKNOWN_CITATION,
    }
    assert [claim["supported"] for claim in claims] == mutated_support
    assert [claim["supported"] for claim in before["product"]["claims"]] == [True, True]


def test_node_writes_structured_failure_without_finalizing() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    state["specialist_outputs"]["product"]["claims"][0]["evidence_ids"] = []

    update = citation_validation_node(state)

    assert update["citation_valid"] is False
    assert update["citation_validation"]["issues"]
    assert "final_answer" not in update


def test_citation_node_events_follow_merge_events() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    pairs = [(event["node"], event["status"]) for event in state["execution_events"]]

    assert pairs.index((GraphNode.CITATION_VALIDATION.value, "active")) > pairs.index(
        (GraphNode.MERGE.value, "complete")
    )
    assert pairs.index((GraphNode.CITATION_VALIDATION.value, "complete")) < pairs.index(
        (GraphNode.SOURCE_VALIDATION.value, "active")
    )


def test_validation_result_rejects_inconsistent_valid_flag() -> None:
    with pytest.raises(ValidationError, match="valid exactly when issues are empty"):
        CitationValidationResult(valid=False, issues=[])
