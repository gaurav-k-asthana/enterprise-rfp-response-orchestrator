from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.commitment_consistency import (
    CommitmentComparison,
    CommitmentComparisonStatus,
    CommitmentConsistencyError,
    CommitmentConsistencyResult,
    commitment_comparison_key,
    commitment_consistency_node,
    compare_commitments,
)
from rfp_orchestrator.commitment_promotion import AuthoritativeCommitment
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.models import CommitmentType
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


def graph():
    return build_selected_fanout_graph(
        build_offline_retrievers(KB_DIRECTORY),
        event_clock=lambda: "fixed",
    )


def initial(requirement_id: str, text: str):
    return new_requirement_state("case-1", requirement_id, text)


def invoke(requirement_id: str, text: str, *, commitments=None):
    state = initial(requirement_id, text)
    if commitments is not None:
        state["commitments"] = commitments
    return graph().invoke(state)


def saml_state(*, commitments=None):
    return invoke(
        "RFP-001",
        "Confirm support for SAML 2.0 and SCIM 2.0.",
        commitments=commitments,
    )


def authoritative_from_proposal(
    proposal: dict,
    *,
    proposal_id: str = "prior-approved-proposal",
    normalized_value: str | None = None,
):
    return AuthoritativeCommitment(
        proposal_id=proposal_id,
        commitment_type=proposal["commitment_type"],
        normalized_value=normalized_value or proposal["normalized_value"],
        source_requirement_id="RFP-PRIOR",
        source_claim_id="prior-claim",
        specialist=proposal["specialist"],
        evidence_ids=["prior-evidence"],
        approval_decision="APPROVE",
        approved_by="prior-reviewer@example.test",
        approved_at="2026-08-29T12:00:00Z",
    ).model_dump(mode="json")


def test_no_prior_memory_marks_saml_and_scim_as_new_without_false_conflict() -> None:
    state = saml_state()

    assert state["commitment_consistent"] is True
    assert [
        item["status"] for item in state["commitment_consistency"]["comparisons"]
    ] == ["NEW", "NEW"]
    assert state["commitment_consistency"]["conflicts"] == []


def test_exact_prior_value_is_consistent_while_unrelated_sibling_is_new() -> None:
    draft = saml_state()
    prior = authoritative_from_proposal(draft["proposed_commitments"][0])

    state = saml_state(commitments=[prior])
    statuses = {
        item["proposed_value"]: item["status"]
        for item in state["commitment_consistency"]["comparisons"]
    }

    assert statuses["saml-2.0:ga:enterprise-cloud,standard-cloud"] == "CONSISTENT"
    assert statuses["scim-2.0:ga:enterprise-cloud"] == "NEW"
    assert state["commitment_consistent"] is True


def test_different_prior_value_for_same_subject_creates_prior_conflict() -> None:
    draft = saml_state()
    prior = authoritative_from_proposal(
        draft["proposed_commitments"][0],
        normalized_value="saml-2.0:ga:enterprise-cloud",
    )

    state = saml_state(commitments=[prior])
    conflicts = state["commitment_consistency"]["conflicts"]

    assert state["commitment_consistent"] is False
    assert len(conflicts) == 1
    assert conflicts[0]["conflict_kind"] == "PRIOR_AUTHORITATIVE"
    assert conflicts[0]["prior_values"] == ["saml-2.0:ga:enterprise-cloud"]
    assert conflicts[0]["proposed_values"] == [
        "saml-2.0:ga:enterprise-cloud,standard-cloud"
    ]


def test_different_integration_subject_does_not_create_false_conflict() -> None:
    draft = saml_state()
    salesforce_prior = authoritative_from_proposal(
        draft["proposed_commitments"][0],
        normalized_value="salesforce:ga:enterprise-cloud",
    )

    state = saml_state(commitments=[salesforce_prior])

    assert state["commitment_consistent"] is True
    assert all(
        item["status"] == "NEW"
        for item in state["commitment_consistency"]["comparisons"]
    )


def test_seeded_30_and_90_day_retention_proposals_conflict_with_each_other() -> None:
    state = invoke(
        "RFP-014",
        (
            "State exactly how many calendar days customer content is retained after "
            "contract termination."
        ),
    )
    result = state["commitment_consistency"]

    assert state["commitment_consistent"] is False
    assert [item["status"] for item in result["comparisons"]] == [
        "CONFLICT",
        "CONFLICT",
    ]
    assert len(result["conflicts"]) == 1
    assert result["conflicts"][0]["conflict_kind"] == "CURRENT_PROPOSALS"
    assert result["conflicts"][0]["comparison_key"] == (
        "RETENTION_PERIOD:customer-content-post-termination"
    )
    assert result["conflicts"][0]["proposed_values"] == [
        "post-termination:30-calendar-days",
        "post-termination-recovery:90-calendar-days",
    ]


def test_non_commitment_response_has_valid_empty_comparison() -> None:
    state = invoke(
        "RFP-004",
        (
            "Describe the typical implementation plan, prerequisites, and customer "
            "responsibilities."
        ),
    )

    assert state["proposed_commitments"] == []
    assert state["commitment_consistent"] is True
    assert state["commitment_consistency"] == {
        "consistent": True,
        "comparisons": [],
        "conflicts": [],
    }


@pytest.mark.parametrize(
    ("commitment_type", "normalized_value", "expected_key"),
    [
        (
            CommitmentType.DATA_RESIDENCY,
            "enterprise-cloud:eu-residency-supported",
            "DATA_RESIDENCY:enterprise-cloud",
        ),
        (
            CommitmentType.RETENTION_PERIOD,
            "post-termination:30-calendar-days",
            "RETENTION_PERIOD:customer-content-post-termination",
        ),
        (
            CommitmentType.UPTIME_SLA,
            "standard-monthly-service-availability:99.9-percent",
            "UPTIME_SLA:standard-monthly-service-availability",
        ),
        (
            CommitmentType.DEPLOYMENT_MODEL,
            "customer-operated-on-premises:unsupported",
            "DEPLOYMENT_MODEL:customer-operated-on-premises",
        ),
        (
            CommitmentType.SUPPORTED_INTEGRATION,
            "saml-2.0:ga:enterprise-cloud,standard-cloud",
            "SUPPORTED_INTEGRATION:saml-2.0",
        ),
        (
            CommitmentType.PRODUCT_AVAILABILITY,
            "sap-s4hana:roadmap:not-ga",
            "PRODUCT_AVAILABILITY:sap-s4hana",
        ),
        (
            CommitmentType.ROADMAP_COMMITMENT,
            "sap-s4hana:roadmap-status",
            "ROADMAP_COMMITMENT:sap-s4hana",
        ),
    ],
)
def test_all_seven_types_have_stable_material_comparison_keys(
    commitment_type: CommitmentType,
    normalized_value: str,
    expected_key: str,
) -> None:
    assert commitment_comparison_key(commitment_type, normalized_value) == expected_key


@pytest.mark.parametrize(
    "invalid_value",
    ["", "not canonical", "UPPERCASE:value", "missing-colon"],
)
def test_noncanonical_normalized_values_fail_closed(invalid_value: str) -> None:
    with pytest.raises(CommitmentConsistencyError, match="canonical"):
        commitment_comparison_key(CommitmentType.UPTIME_SLA, invalid_value)


def test_unapproved_authoritative_record_cannot_participate_in_comparison() -> None:
    state = saml_state()
    proposal = state["proposed_commitments"][0]
    prior = authoritative_from_proposal(proposal)
    prior["approved"] = False
    state["commitments"] = [prior]

    with pytest.raises(CommitmentConsistencyError, match="malformed"):
        compare_commitments(state)


def test_proposal_from_another_requirement_fails_closed() -> None:
    state = saml_state()
    state["proposed_commitments"][0]["source_requirement_id"] = "RFP-OTHER"

    with pytest.raises(CommitmentConsistencyError, match="another requirement"):
        compare_commitments(state)


@pytest.mark.parametrize("collection", ["proposed_commitments", "commitments"])
def test_duplicate_proposal_or_authoritative_ids_fail_closed(collection: str) -> None:
    state = saml_state()
    if collection == "proposed_commitments":
        state[collection] = [
            state[collection][0],
            deepcopy(state[collection][0]),
        ]
    else:
        prior = authoritative_from_proposal(state["proposed_commitments"][0])
        state[collection] = [prior, deepcopy(prior)]

    with pytest.raises(CommitmentConsistencyError, match="IDs cannot repeat"):
        compare_commitments(state)


def test_multiple_prior_values_conflict_even_when_one_matches() -> None:
    draft = saml_state()
    proposal = draft["proposed_commitments"][0]
    matching = authoritative_from_proposal(proposal, proposal_id="prior-match")
    differing = authoritative_from_proposal(
        proposal,
        proposal_id="prior-different",
        normalized_value="saml-2.0:ga:enterprise-cloud",
    )

    state = saml_state(commitments=[matching, differing])
    comparison = state["commitment_consistency"]["comparisons"][0]

    assert comparison["status"] == "CONFLICT"
    assert comparison["prior_commitment_ids"] == [
        "prior-match",
        "prior-different",
    ]


def test_consistency_node_does_not_mutate_either_ledger_or_route_state() -> None:
    state = saml_state()
    proposals_before = deepcopy(state["proposed_commitments"])
    commitments_before = deepcopy(state["commitments"])
    strategy_before = state["strategy"]

    update = commitment_consistency_node(state)

    assert set(update) == {"commitment_consistent", "commitment_consistency"}
    assert state["proposed_commitments"] == proposals_before
    assert state["commitments"] == commitments_before
    assert state["strategy"] == strategy_before


def test_graph_events_place_consistency_between_extraction_and_promotion() -> None:
    state = saml_state()
    nodes = [item["node"] for item in state["execution_events"]]

    assert nodes.index(GraphNode.COMMITMENT_LEDGER.value) < nodes.index(
        GraphNode.COMMITMENT_CONSISTENCY.value
    )
    assert nodes.index(GraphNode.COMMITMENT_CONSISTENCY.value) < nodes.index(
        GraphNode.COMMITMENT_PROMOTION.value
    )


def test_exhausted_recovery_never_reaches_consistency() -> None:
    state = invoke(
        "RFP-021",
        "Confirm that Northstar is authorized for FedRAMP High.",
    )
    event_nodes = [item["node"] for item in state["execution_events"]]

    assert state["recovery_exhausted"] is True
    assert state["commitment_consistent"] is None
    assert state["commitment_consistency"] is None
    assert GraphNode.COMMITMENT_CONSISTENCY.value not in event_nodes


def test_comparison_is_repeatable_for_the_same_state() -> None:
    state = saml_state()

    first = compare_commitments(state)
    second = compare_commitments(state)

    assert first == second


def test_result_model_rejects_unknown_conflict_reference() -> None:
    comparison = CommitmentComparison(
        proposal_id="proposal-1",
        commitment_type="UPTIME_SLA",
        comparison_key="UPTIME_SLA:standard-monthly-service-availability",
        proposed_value="standard-monthly-service-availability:99.9-percent",
        status=CommitmentComparisonStatus.CONFLICT,
        conflict_ids=["missing-conflict"],
    )

    with pytest.raises(ValidationError, match="unknown conflict"):
        CommitmentConsistencyResult(
            consistent=True,
            comparisons=[comparison],
            conflicts=[],
        )
