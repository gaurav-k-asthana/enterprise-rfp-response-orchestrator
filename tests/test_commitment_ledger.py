from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.commitment_ledger import (
    CommitmentLedgerError,
    ProposedCommitment,
    commitment_ledger_node,
    extract_commitment_proposals,
)
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.models import CommitmentType, Domain
from rfp_orchestrator.retrieval import build_offline_retrievers
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


def supported_state(
    *,
    domain: Domain,
    claim_text: str,
    claim_id: str = "claim-001",
):
    state = new_requirement_state("case-1", "RFP-X", claim_text)
    state.update(
        {
            "claim_support_valid": True,
            "claim_support_validation": {
                "assessments": [
                    {
                        "specialist": domain.value,
                        "claims": [
                            {
                                "specialist": domain.value,
                                "claim_id": claim_id,
                                "text": claim_text,
                                "evidence_ids": ["evidence-001"],
                                "supported": True,
                                "lexical_coverage": 1.0,
                                "rationale": "Supported test claim.",
                            }
                        ],
                        "support_status": "SUPPORTED",
                    }
                ]
            },
        }
    )
    return state


def test_locked_commitment_type_scope_has_exactly_seven_categories() -> None:
    assert {item.value for item in CommitmentType} == {
        "DATA_RESIDENCY",
        "RETENTION_PERIOD",
        "UPTIME_SLA",
        "DEPLOYMENT_MODEL",
        "SUPPORTED_INTEGRATION",
        "PRODUCT_AVAILABILITY",
        "ROADMAP_COMMITMENT",
    }


@pytest.mark.parametrize(
    ("domain", "claim_text", "expected_type", "expected_value"),
    [
        (
            Domain.SECURITY,
            "Enterprise Cloud supports customer-data residency in the European Union.",
            CommitmentType.DATA_RESIDENCY,
            "enterprise-cloud:eu-residency-supported",
        ),
        (
            Domain.SECURITY,
            (
                "The Customer Data Retention Standard states a 30-calendar-day "
                "post-termination period."
            ),
            CommitmentType.RETENTION_PERIOD,
            "post-termination:30-calendar-days",
        ),
        (
            Domain.PRODUCT,
            "The documented standard monthly service-availability target is 99.9%.",
            CommitmentType.UPTIME_SLA,
            "standard-monthly-service-availability:99.9-percent",
        ),
        (
            Domain.PRODUCT,
            (
                "Customer-operated on-premises deployment, a customer-managed "
                "Kubernetes distribution, and private data-center installation are "
                "unsupported in V1."
            ),
            CommitmentType.DEPLOYMENT_MODEL,
            "customer-operated-on-premises:unsupported",
        ),
        (
            Domain.PRODUCT,
            "The Salesforce connector is generally available on Enterprise Cloud.",
            CommitmentType.SUPPORTED_INTEGRATION,
            "salesforce:ga:enterprise-cloud",
        ),
        (
            Domain.PRODUCT,
            (
                "Customer-managed encryption keys are generally available only for "
                "AWS-hosted Enterprise Cloud."
            ),
            CommitmentType.PRODUCT_AVAILABILITY,
            "customer-managed-encryption-keys:ga:aws-enterprise-cloud",
        ),
        (
            Domain.PRODUCT,
            (
                "The SAP S/4HANA connector is a roadmap item and is not generally "
                "available."
            ),
            CommitmentType.ROADMAP_COMMITMENT,
            "sap-s4hana:roadmap-status",
        ),
    ],
)
def test_each_locked_type_has_an_explicit_normalization_rule(
    domain: Domain,
    claim_text: str,
    expected_type: CommitmentType,
    expected_value: str,
) -> None:
    result = extract_commitment_proposals(
        supported_state(domain=domain, claim_text=claim_text)
    )

    matches = [
        item
        for item in result.proposed_commitments
        if item.commitment_type is expected_type
    ]
    assert [item.normalized_value for item in matches] == [expected_value]


def test_live_saml_case_creates_two_draft_integration_proposals() -> None:
    state = invoke("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")

    assert [item["normalized_value"] for item in state["proposed_commitments"]] == [
        "saml-2.0:ga:enterprise-cloud,standard-cloud",
        "scim-2.0:ga:enterprise-cloud",
    ]
    assert all(
        item["commitment_type"] == "SUPPORTED_INTEGRATION"
        for item in state["proposed_commitments"]
    )
    assert all(
        item["approved"] is False and item["authoritative"] is False
        for item in state["proposed_commitments"]
    )
    assert state["commitments"] == []


def test_conflicting_retention_sources_remain_separate_draft_proposals() -> None:
    state = invoke(
        "RFP-014",
        (
            "State exactly how many calendar days customer content is retained after "
            "contract termination."
        ),
    )

    assert [item["normalized_value"] for item in state["proposed_commitments"]] == [
        "post-termination:30-calendar-days",
        "post-termination-recovery:90-calendar-days",
    ]
    assert state["commitments"] == []


def test_non_commitment_claim_is_audited_without_creating_a_proposal() -> None:
    state = invoke(
        "RFP-004",
        (
            "Describe the typical implementation plan, prerequisites, and customer "
            "responsibilities."
        ),
    )

    assert state["proposed_commitments"] == []
    assert state["commitment_extraction"]["non_commitment_claim_ids"]
    assert state["commitments"] == []


def test_unsupported_claim_cannot_become_a_proposal() -> None:
    state = supported_state(
        domain=Domain.PRODUCT,
        claim_text="The Salesforce connector is generally available on Enterprise Cloud.",
    )
    claim = state["claim_support_validation"]["assessments"][0]["claims"][0]
    claim["supported"] = False
    state["claim_support_validation"]["assessments"][0][
        "support_status"
    ] = "UNSUPPORTED"

    result = extract_commitment_proposals(state)

    assert result.proposed_commitments == []
    assert result.unsupported_claim_ids == ["claim-001"]


def test_proposal_preserves_requirement_claim_specialist_and_evidence_provenance() -> None:
    state = invoke("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    proposal = ProposedCommitment.model_validate(state["proposed_commitments"][0])

    assert proposal.proposal_id == (
        "RFP-001:product:product-claim-001:SUPPORTED_INTEGRATION"
    )
    assert proposal.source_requirement_id == "RFP-001"
    assert proposal.source_claim_id == "product-claim-001"
    assert proposal.specialist is Domain.PRODUCT
    assert proposal.evidence_ids


@pytest.mark.parametrize(
    "unsafe_field",
    [
        {"approved": True},
        {"authoritative": True},
        {"evidence_ids": []},
        {"normalized_value": " "},
    ],
)
def test_proposal_model_rejects_authoritative_or_incomplete_drafts(
    unsafe_field: dict,
) -> None:
    payload = {
        "proposal_id": "RFP-X:product:claim-001:UPTIME_SLA",
        "commitment_type": "UPTIME_SLA",
        "normalized_value": "standard-monthly:99.9-percent",
        "source_requirement_id": "RFP-X",
        "source_claim_id": "claim-001",
        "specialist": "product",
        "evidence_ids": ["evidence-001"],
    }
    payload.update(unsafe_field)

    with pytest.raises(ValidationError):
        ProposedCommitment.model_validate(payload)


@pytest.mark.parametrize(
    "unsafe_update",
    [
        {"claim_support_valid": False},
        {"recovery_needed": True},
        {"recovery_exhausted": True},
        {"prompt_injection_detected": True},
    ],
)
def test_extraction_fails_closed_before_unsafe_state(unsafe_update: dict) -> None:
    state = supported_state(
        domain=Domain.PRODUCT,
        claim_text="The Salesforce connector is generally available on Enterprise Cloud.",
    )
    state.update(unsafe_update)

    with pytest.raises(CommitmentLedgerError):
        extract_commitment_proposals(state)


def test_ledger_node_does_not_write_the_authoritative_commitment_field() -> None:
    state = supported_state(
        domain=Domain.PRODUCT,
        claim_text="The Salesforce connector is generally available on Enterprise Cloud.",
    )
    state["commitments"] = [
        {
            "commitment_type": "UPTIME_SLA",
            "normalized_value": "existing-approved-value",
            "source_requirement_id": "RFP-OLD",
            "approved": True,
        }
    ]

    update = commitment_ledger_node(state)

    assert "commitments" not in update
    assert state["commitments"][0]["normalized_value"] == "existing-approved-value"


def test_persistent_recovery_exhaustion_never_reaches_commitment_ledger() -> None:
    state = invoke(
        "RFP-021",
        "Confirm that Northstar is authorized for FedRAMP High.",
    )
    event_nodes = [item["node"] for item in state["execution_events"]]

    assert state["recovery_exhausted"] is True
    assert state["commitment_extraction"] is None
    assert state["proposed_commitments"] == []
    assert GraphNode.COMMITMENT_LEDGER.value not in event_nodes


def test_proposal_output_is_repeatable_for_the_same_input() -> None:
    first = invoke("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")
    second = invoke("RFP-001", "Confirm support for SAML 2.0 and SCIM 2.0.")

    assert first["proposed_commitments"] == second["proposed_commitments"]
