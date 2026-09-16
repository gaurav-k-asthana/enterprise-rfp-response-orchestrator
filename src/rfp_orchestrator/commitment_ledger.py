"""Narrow, non-authoritative commitment proposal extraction for Step 2.16."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from rfp_orchestrator.claim_support import SpecialistSupportAssessment
from rfp_orchestrator.models import CommitmentType, Domain
from rfp_orchestrator.state import GraphState


class CommitmentLedgerError(ValueError):
    """Raised when proposed commitments cannot be extracted safely."""


class ProposedCommitment(BaseModel):
    """A normalized draft that has not entered authoritative memory."""

    proposal_id: str = Field(min_length=1)
    commitment_type: CommitmentType
    normalized_value: str = Field(min_length=1)
    source_requirement_id: str = Field(min_length=1)
    source_claim_id: str = Field(min_length=1)
    specialist: Domain
    evidence_ids: list[str] = Field(min_length=1)
    approved: Literal[False] = False
    authoritative: Literal[False] = False

    @model_validator(mode="after")
    def proposal_has_stable_provenance(self) -> ProposedCommitment:
        text_fields = {
            "proposal_id": self.proposal_id,
            "normalized_value": self.normalized_value,
            "source_requirement_id": self.source_requirement_id,
            "source_claim_id": self.source_claim_id,
        }
        if any(not value.strip() for value in text_fields.values()):
            raise ValueError("commitment proposal fields cannot be blank")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("commitment proposal evidence IDs cannot repeat")
        if any(not evidence_id.strip() for evidence_id in self.evidence_ids):
            raise ValueError("commitment proposal evidence IDs cannot be blank")
        return self


class CommitmentExtractionResult(BaseModel):
    """Auditable output of the draft-only commitment extraction boundary."""

    valid: Literal[True] = True
    proposed_commitments: list[ProposedCommitment] = Field(default_factory=list)
    non_commitment_claim_ids: list[str] = Field(default_factory=list)
    unsupported_claim_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def extraction_is_deterministic_and_draft_only(self) -> CommitmentExtractionResult:
        proposal_ids = [item.proposal_id for item in self.proposed_commitments]
        if len(proposal_ids) != len(set(proposal_ids)):
            raise ValueError("commitment proposal IDs cannot repeat")
        if set(self.non_commitment_claim_ids) & set(self.unsupported_claim_ids):
            raise ValueError("a claim cannot have two extraction outcomes")
        if any(
            item.approved or item.authoritative
            for item in self.proposed_commitments
        ):
            raise ValueError("Step 2.16 proposals must remain non-authoritative")
        return self


@dataclass(frozen=True)
class _NormalizationRule:
    specialist: Domain
    claim_pattern: re.Pattern[str]
    commitment_type: CommitmentType
    normalized_value: str


def _rule(
    specialist: Domain,
    claim_pattern: str,
    commitment_type: CommitmentType,
    normalized_value: str,
) -> _NormalizationRule:
    return _NormalizationRule(
        specialist=specialist,
        claim_pattern=re.compile(claim_pattern, re.IGNORECASE),
        commitment_type=commitment_type,
        normalized_value=normalized_value,
    )


_NORMALIZATION_RULES = (
    _rule(
        Domain.PRODUCT,
        r"SAML 2\.0 is generally available",
        CommitmentType.SUPPORTED_INTEGRATION,
        "saml-2.0:ga:enterprise-cloud,standard-cloud",
    ),
    _rule(
        Domain.PRODUCT,
        r"SCIM 2\.0 is generally available",
        CommitmentType.SUPPORTED_INTEGRATION,
        "scim-2.0:ga:enterprise-cloud",
    ),
    _rule(
        Domain.PRODUCT,
        r"customer-managed encryption keys are generally available",
        CommitmentType.PRODUCT_AVAILABILITY,
        "customer-managed-encryption-keys:ga:aws-enterprise-cloud",
    ),
    _rule(
        Domain.PRODUCT,
        r"Standard Cloud and Enterprise Cloud are Northstar-operated",
        CommitmentType.DEPLOYMENT_MODEL,
        "standard-cloud,enterprise-cloud:northstar-operated",
    ),
    _rule(
        Domain.PRODUCT,
        r"Customer-operated on-premises deployment.*unsupported",
        CommitmentType.DEPLOYMENT_MODEL,
        "customer-operated-on-premises:unsupported",
    ),
    _rule(
        Domain.PRODUCT,
        r"Salesforce connector is generally available",
        CommitmentType.SUPPORTED_INTEGRATION,
        "salesforce:ga:enterprise-cloud",
    ),
    _rule(
        Domain.PRODUCT,
        r"SAP S/4HANA connector is a roadmap item",
        CommitmentType.PRODUCT_AVAILABILITY,
        "sap-s4hana:roadmap:not-ga",
    ),
    _rule(
        Domain.PRODUCT,
        r"SAP S/4HANA connector is a roadmap item",
        CommitmentType.ROADMAP_COMMITMENT,
        "sap-s4hana:roadmap-status",
    ),
    _rule(
        Domain.PRODUCT,
        r"standard monthly service-availability target is 99\.9%",
        CommitmentType.UPTIME_SLA,
        "standard-monthly-service-availability:99.9-percent",
    ),
    _rule(
        Domain.SECURITY,
        r"Enterprise Cloud supports customer-data residency in the European Union",
        CommitmentType.DATA_RESIDENCY,
        "enterprise-cloud:eu-residency-supported",
    ),
    _rule(
        Domain.SECURITY,
        r"Standard Cloud is hosted in the United States.*does not offer.*European Union residency",
        CommitmentType.DATA_RESIDENCY,
        "standard-cloud:us-hosted:eu-selection-unsupported",
    ),
    _rule(
        Domain.SECURITY,
        r"30-calendar-day post-termination period",
        CommitmentType.RETENTION_PERIOD,
        "post-termination:30-calendar-days",
    ),
    _rule(
        Domain.SECURITY,
        r"90-calendar-day post-termination recovery window",
        CommitmentType.RETENTION_PERIOD,
        "post-termination-recovery:90-calendar-days",
    ),
)


def _proposal_id(
    requirement_id: str,
    specialist: Domain,
    claim_id: str,
    commitment_type: CommitmentType,
) -> str:
    return (
        f"{requirement_id}:{specialist.value}:{claim_id}:"
        f"{commitment_type.value}"
    )


def extract_commitment_proposals(state: GraphState) -> CommitmentExtractionResult:
    """Normalize supported material claims without changing authoritative memory."""

    if state.get("prompt_injection_detected"):
        raise CommitmentLedgerError(
            "prompt-injection content cannot enter commitment extraction"
        )
    if state.get("claim_support_valid") is not True:
        raise CommitmentLedgerError(
            "commitment extraction requires valid independent claim support"
        )
    if state.get("recovery_needed") or state.get("recovery_exhausted"):
        raise CommitmentLedgerError(
            "commitment extraction cannot run while evidence recovery is active"
        )

    raw_validation = state.get("claim_support_validation")
    if not isinstance(raw_validation, dict):
        raise CommitmentLedgerError("claim support validation is missing")

    requirement_id = str(state.get("requirement_id", "")).strip()
    if not requirement_id:
        raise CommitmentLedgerError("requirement_id is required")

    proposals: list[ProposedCommitment] = []
    non_commitment_claim_ids: list[str] = []
    unsupported_claim_ids: list[str] = []
    try:
        assessments = [
            SpecialistSupportAssessment.model_validate(item)
            for item in raw_validation.get("assessments", [])
        ]
    except (TypeError, ValueError) as error:
        raise CommitmentLedgerError(
            "claim support assessments are malformed"
        ) from error

    for assessment in assessments:
        for claim in assessment.claims:
            if not claim.supported:
                unsupported_claim_ids.append(claim.claim_id)
                continue
            matching_rules = [
                rule
                for rule in _NORMALIZATION_RULES
                if rule.specialist is assessment.specialist
                and rule.claim_pattern.search(claim.text)
            ]
            if not matching_rules:
                non_commitment_claim_ids.append(claim.claim_id)
                continue
            for rule in matching_rules:
                proposals.append(
                    ProposedCommitment(
                        proposal_id=_proposal_id(
                            requirement_id,
                            assessment.specialist,
                            claim.claim_id,
                            rule.commitment_type,
                        ),
                        commitment_type=rule.commitment_type,
                        normalized_value=rule.normalized_value,
                        source_requirement_id=requirement_id,
                        source_claim_id=claim.claim_id,
                        specialist=assessment.specialist,
                        evidence_ids=list(claim.evidence_ids),
                    )
                )

    return CommitmentExtractionResult(
        proposed_commitments=proposals,
        non_commitment_claim_ids=non_commitment_claim_ids,
        unsupported_claim_ids=unsupported_claim_ids,
    )


def commitment_ledger_node(state: GraphState) -> GraphState:
    """Write draft proposals only; authoritative commitments remain unchanged."""

    result = extract_commitment_proposals(state)
    return {
        "proposed_commitments": [
            proposal.model_dump(mode="json")
            for proposal in result.proposed_commitments
        ],
        "commitment_extraction": result.model_dump(mode="json"),
    }
