from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.citation_validation import citation_validation_node
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.source_validation import (
    SourceIssueType,
    SourceValidationResult,
    source_validation_node,
    validate_source_metadata,
)
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"
AS_OF = date(2026, 8, 30)


def fixed_clock() -> str:
    return "2026-08-30T12:00:00Z"


def live_state(requirement_id: str, text: str) -> dict:
    graph = build_selected_fanout_graph(
        build_offline_retrievers(KB_DIRECTORY),
        event_clock=fixed_clock,
    )
    return graph.invoke(new_requirement_state("case-1", requirement_id, text))


def issue_types(result: SourceValidationResult) -> list[SourceIssueType]:
    return [issue.issue_type for issue in result.issues]


def test_live_current_single_specialist_sources_are_valid() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")

    assert state["source_metadata_valid"] is True
    assert state["source_validation"]["eligible_cited_evidence_ids"]
    assert state["source_validation"]["lowest_cited_authority_rank"] == 5


def test_live_parallel_source_metadata_is_valid() -> None:
    state = live_state(
        "RFP-002",
        (
            "Describe customer-managed encryption keys and identify supported "
            "deployment environments."
        ),
    )

    assert state["source_metadata_valid"] is True
    assert state["source_validation"]["issues"] == []


def test_archived_retrieval_is_visible_but_valid_when_not_cited() -> None:
    state = live_state(
        "RFP-008",
        "State the supported TLS versions for application and API connections.",
    )

    assert state["source_metadata_valid"] is True
    archived = state["source_validation"]["archived_evidence_ids"]
    assert archived
    assert any(
        item["doc_id"] == "SEC-CTRL-OLD-001" and item["chunk_id"] in archived
        for item in state["evidence"]
    )


def test_citing_archived_evidence_fails_source_validation() -> None:
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
    state.update(citation_validation_node(state))

    result = validate_source_metadata(state, as_of=AS_OF)

    assert state["citation_valid"] is True
    assert result.valid is False
    assert issue_types(result) == [SourceIssueType.ARCHIVED_CITATION]


@pytest.mark.parametrize(
    ("field", "value", "expected_issue"),
    [
        ("authority_rank", 0, SourceIssueType.INVALID_AUTHORITY_RANK),
        ("authority_rank", 6, SourceIssueType.INVALID_AUTHORITY_RANK),
        ("authority_rank", "5", SourceIssueType.INVALID_AUTHORITY_RANK),
        ("source_status", "draft", SourceIssueType.UNKNOWN_SOURCE_STATUS),
        ("effective_date", "not-a-date", SourceIssueType.INVALID_EFFECTIVE_DATE),
        ("version", "   ", SourceIssueType.MISSING_VERSION),
        ("doc_id", "", SourceIssueType.MISSING_DOC_ID),
    ],
)
def test_invalid_source_metadata_fails_closed(
    field: str,
    value,
    expected_issue: SourceIssueType,
) -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    state["evidence"][0][field] = value

    result = validate_source_metadata(state, as_of=AS_OF)

    assert result.valid is False
    assert expected_issue in issue_types(result)


def test_future_effective_source_fails_as_of_validation_date() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    state["evidence"][0]["effective_date"] = "2026-09-01"

    result = validate_source_metadata(state, as_of=AS_OF)

    assert result.valid is False
    assert SourceIssueType.FUTURE_EFFECTIVE_DATE in issue_types(result)


def test_invalid_citation_gate_prevents_source_gate_from_passing() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    state["citation_valid"] = False

    result = validate_source_metadata(state, as_of=AS_OF)

    assert result.valid is False
    assert issue_types(result)[0] is SourceIssueType.UPSTREAM_CITATION_INVALID


def test_missing_cited_evidence_is_reported_independently() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    cited_id = state["citation_validation"]["cited_evidence_ids"][0]
    state["evidence"] = [
        item for item in state["evidence"] if item["chunk_id"] != cited_id
    ]

    result = validate_source_metadata(state, as_of=AS_OF)

    assert SourceIssueType.CITED_EVIDENCE_MISSING in issue_types(result)


def test_source_node_does_not_change_claims_or_finalize() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    claims_before = deepcopy(state["specialist_outputs"])

    update = source_validation_node(state)

    assert update["source_metadata_valid"] is True
    assert state["specialist_outputs"] == claims_before
    assert "final_answer" not in update


def test_source_validation_events_follow_citation_validation() -> None:
    state = live_state("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    pairs = [(event["node"], event["status"]) for event in state["execution_events"]]

    assert pairs.index((GraphNode.SOURCE_VALIDATION.value, "active")) > pairs.index(
        (GraphNode.CITATION_VALIDATION.value, "complete")
    )
    assert pairs.index((GraphNode.SOURCE_VALIDATION.value, "complete")) < pairs.index(
        (GraphNode.CLAIM_SUPPORT_VALIDATION.value, "active")
    )


def test_result_rejects_inconsistent_valid_or_lowest_rank() -> None:
    with pytest.raises(ValidationError, match="valid exactly when issues are empty"):
        SourceValidationResult(valid=False, as_of_date="2026-08-30", issues=[])

    with pytest.raises(ValidationError, match="lowest cited authority rank"):
        SourceValidationResult(
            valid=True,
            as_of_date="2026-08-30",
            eligible_cited_evidence_ids=["chunk-1"],
            authority_by_evidence={"chunk-1": 5},
            lowest_cited_authority_rank=4,
        )
