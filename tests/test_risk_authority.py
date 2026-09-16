from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.graph_fanout import (
    build_selected_fanout_graph,
    route_risk_authority,
)
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.models import RiskClass
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.risk_authority import (
    AuthorityGateStatus,
    AuthorityOwner,
    RiskAuthorityAssessment,
    RiskAuthorityError,
    assess_risk_authority,
    risk_authority_node,
)
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


def graph():
    return build_selected_fanout_graph(
        build_offline_retrievers(KB_DIRECTORY),
        event_clock=lambda: "fixed",
    )


def invoke(requirement_id: str, text: str):
    return graph().invoke(
        new_requirement_state("case-1", requirement_id, text)
    )


def safe_state():
    return invoke("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")


def retention_conflict_state():
    return invoke(
        "RFP-014",
        "State exactly how many calendar days customer content is retained after "
        "contract termination.",
    )


def test_supported_standard_path_clears_authority_gate_and_reaches_promotion() -> None:
    state = safe_state()

    assert state["risk_assessment"]["status"] == "CLEAR"
    assert state["risk_assessment"]["evidence_checks_passed"] is True
    assert state["risk_classes"] == []
    assert state["authority_required"] is False
    assert state["authority_gate_passed"] is True
    assert state["commitment_promotion"]["status"] == "NO_SELECTION"


def test_strong_sla_evidence_still_stops_for_organizational_authority() -> None:
    state = invoke(
        "RFP-005",
        "Commit to a 99.99% uptime SLA with service credits.",
    )

    assert state["citation_valid"] is True
    assert state["source_metadata_valid"] is True
    assert state["claim_support_valid"] is True
    assert state["commitment_consistent"] is True
    assert state["risk_assessment"]["evidence_checks_passed"] is True
    assert state["risk_classes"] == ["SLA_OR_SERVICE_CREDIT"]
    assert state["authority_owners"] == ["COMMERCIAL_LEGAL"]
    assert state["authority_required"] is True
    assert state["authority_gate_passed"] is False
    assert state["strategy"] == "IMMEDIATE_HITL"
    assert state["final_status"] == "NEEDS_HUMAN"
    assert state["final_answer"] is None
    assert state["commitment_promotion"] is None


def test_security_exception_stops_after_evidence_checks() -> None:
    state = invoke(
        "RFP-013",
        "Guarantee that support personnel never access customer data outside the EU.",
    )

    assert state["risk_classes"] == ["SECURITY_EXCEPTION"]
    assert state["authority_owners"] == ["SECURITY_LEGAL"]
    assert state["final_status"] == "NEEDS_HUMAN"
    nodes = [item["node"] for item in state["execution_events"]]
    assert GraphNode.RISK_AUTHORITY.value in nodes
    assert GraphNode.COMMITMENT_PROMOTION.value not in nodes


@pytest.mark.parametrize(
    ("risk_class", "owner"),
    [
        (RiskClass.ROADMAP_COMMITMENT, AuthorityOwner.PRODUCT_OWNER),
        (RiskClass.PRICING_OR_DISCOUNT, AuthorityOwner.COMMERCIAL_LEGAL),
        (RiskClass.SLA_OR_SERVICE_CREDIT, AuthorityOwner.COMMERCIAL_LEGAL),
        (RiskClass.WARRANTY_OR_INDEMNITY, AuthorityOwner.COMMERCIAL_LEGAL),
        (RiskClass.SECURITY_EXCEPTION, AuthorityOwner.SECURITY_LEGAL),
        (RiskClass.DATA_RESIDENCY_AMBIGUITY, AuthorityOwner.SECURITY_LEGAL),
    ],
)
def test_every_initial_authority_category_has_a_deterministic_owner(
    risk_class: RiskClass,
    owner: AuthorityOwner,
) -> None:
    state = safe_state()
    state["initial_risk_flags"] = [risk_class.value]

    assessment = assess_risk_authority(state)

    assert assessment.status is AuthorityGateStatus.NEEDS_HUMAN
    assert assessment.risk_classes == [risk_class]
    assert assessment.authority_owners == [owner]


def test_supported_negative_answer_is_not_an_unsupported_categorical_yes() -> None:
    state = invoke(
        "RFP-003",
        "Confirm whether your platform is FIPS 140-3 certified.",
    )

    assert state["merged_specialist_outputs"][0]["proposed_answer"].startswith("No.")
    assert state["risk_classes"] == []
    assert state["authority_gate_passed"] is True


def test_affirmative_answer_with_unsupported_claim_is_escalated() -> None:
    state = safe_state()
    output = deepcopy(state["merged_specialist_outputs"][0])
    output["proposed_answer"] = "Yes, Northstar supports the requested capability."
    output["claims"][0]["supported"] = False
    output["claims"][0]["evidence_ids"] = []
    output["support_status"] = "PARTIAL"
    state["merged_specialist_outputs"] = [output]

    assessment = assess_risk_authority(state)

    assert assessment.risk_classes == [RiskClass.UNSUPPORTED_CATEGORICAL_YES]
    assert assessment.authority_owners == [AuthorityOwner.PROPOSAL_REVIEWER]


def test_unresolved_conflict_is_classified_for_human_review() -> None:
    state = retention_conflict_state()

    assessment = assess_risk_authority(state)

    assert assessment.evidence_checks_passed is False
    assert RiskClass.CONFLICTING_EVIDENCE in assessment.risk_classes
    assert assessment.requires_human is True


def test_cross_specialist_current_conflict_adds_specialist_disagreement() -> None:
    state = retention_conflict_state()
    state["proposed_commitments"][1]["specialist"] = "product"

    assessment = assess_risk_authority(state)

    assert assessment.risk_classes == [
        RiskClass.CONFLICTING_EVIDENCE,
        RiskClass.SPECIALIST_DISAGREEMENT,
    ]


def test_conflict_reference_to_unknown_proposal_fails_closed() -> None:
    state = retention_conflict_state()
    state["commitment_consistency"]["conflicts"][0]["proposal_ids"] = [
        "unknown-proposal"
    ]

    with pytest.raises(RiskAuthorityError, match="unknown proposal"):
        assess_risk_authority(state)


def test_exhausted_recovery_is_classified_even_without_consistency_state() -> None:
    state = invoke(
        "RFP-021",
        "Confirm that Northstar is authorized for FedRAMP High.",
    )

    assessment = assess_risk_authority(state)

    assert assessment.evidence_checks_passed is False
    assert assessment.risk_classes == [RiskClass.RETRY_BUDGET_EXHAUSTED]
    assert assessment.requires_human is True


def test_node_clears_active_specialists_and_never_fabricates_a_final_answer() -> None:
    state = safe_state()
    state["initial_risk_flags"] = [RiskClass.ROADMAP_COMMITMENT.value]

    update = risk_authority_node(state)

    assert update["strategy"] == "IMMEDIATE_HITL"
    assert update["selected_specialists"] == []
    assert update["final_status"] == "NEEDS_HUMAN"
    assert update["final_answer"] is None


def test_routing_has_only_clear_or_human_stop_outcomes() -> None:
    clear = new_requirement_state("case-1", "RFP-X", "Test.")
    clear["authority_gate_passed"] = True
    assert route_risk_authority(clear) == GraphNode.FINALIZATION_GUARD.value

    human = new_requirement_state("case-1", "RFP-X", "Test.")
    human["authority_required"] = True
    human["authority_gate_passed"] = False
    assert route_risk_authority(human) == "__end__"

    undecided = new_requirement_state("case-1", "RFP-X", "Test.")
    with pytest.raises(ValueError, match="terminal decision"):
        route_risk_authority(undecided)


def test_incomplete_safe_state_fails_closed() -> None:
    state = safe_state()
    state["source_metadata_valid"] = None

    with pytest.raises(RiskAuthorityError, match="cannot clear incomplete"):
        assess_risk_authority(state)


@pytest.mark.parametrize(
    "invalid_risks",
    [
        ["NOT_A_RISK"],
        [RiskClass.SECURITY_EXCEPTION.value, RiskClass.SECURITY_EXCEPTION.value],
    ],
)
def test_unknown_or_duplicate_initial_risks_fail_closed(invalid_risks) -> None:
    state = safe_state()
    state["initial_risk_flags"] = invalid_risks

    with pytest.raises(RiskAuthorityError):
        assess_risk_authority(state)


def test_malformed_specialist_output_fails_closed() -> None:
    state = safe_state()
    state["merged_specialist_outputs"][0]["support_status"] = "UNSUPPORTED"

    with pytest.raises(RiskAuthorityError, match="specialist output"):
        assess_risk_authority(state)


def test_assessment_model_cannot_mark_incomplete_evidence_clear() -> None:
    with pytest.raises(ValidationError, match="incomplete evidence"):
        RiskAuthorityAssessment(
            status="CLEAR",
            evidence_checks_passed=False,
            requires_human=False,
            reason="Unsafe clear.",
        )


def test_assessment_is_repeatable_and_does_not_mutate_input() -> None:
    state = safe_state()
    state["initial_risk_flags"] = [RiskClass.SLA_OR_SERVICE_CREDIT.value]
    before = deepcopy(state)

    first = assess_risk_authority(state)
    second = assess_risk_authority(state)

    assert first == second
    assert state == before


def test_graph_orders_authority_gate_after_conflict_and_before_promotion() -> None:
    edges = {(edge.source, edge.target) for edge in graph().get_graph().edges}

    assert (
        GraphNode.CONFLICT_RESOLUTION.value,
        GraphNode.RISK_AUTHORITY.value,
    ) in edges
    assert (
        GraphNode.RISK_AUTHORITY.value,
        GraphNode.FINALIZATION_GUARD.value,
    ) in edges
    assert (
        GraphNode.FINALIZATION_GUARD.value,
        GraphNode.COMMITMENT_PROMOTION.value,
    ) in edges
    assert (
        GraphNode.RISK_AUTHORITY.value,
        GraphNode.COMMITMENT_PROMOTION.value,
    ) not in edges
    assert (
        GraphNode.CONFLICT_RESOLUTION.value,
        GraphNode.COMMITMENT_PROMOTION.value,
    ) not in edges
