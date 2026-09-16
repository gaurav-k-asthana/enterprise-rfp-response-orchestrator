"""Deterministic offline Product, Security, and Implementation specialist nodes."""

from __future__ import annotations

import re
from dataclasses import dataclass

from pydantic import BaseModel, Field, model_validator

from rfp_orchestrator.models import (
    Claim,
    Domain,
    Requirement,
    SpecialistOutput,
    aggregate_support,
)
from rfp_orchestrator.retrieval import (
    EvidenceChunk,
    RetrievalMethod,
    SpecialistRetriever,
)


class SpecialistBoundaryError(ValueError):
    """Raised when a specialist is invoked outside its locked boundary."""


class SpecialistNodeResult(BaseModel):
    output: SpecialistOutput
    evidence: list[EvidenceChunk] = Field(max_length=5)

    @model_validator(mode="after")
    def citations_refer_to_returned_domain_evidence(self) -> SpecialistNodeResult:
        specialist = self.output.specialist
        if any(item.domain is not specialist for item in self.evidence):
            raise ValueError("specialist evidence must remain inside its domain")
        evidence_ids = {item.chunk_id for item in self.evidence}
        if any(
            citation_id not in evidence_ids
            for claim in self.output.claims
            for citation_id in claim.evidence_ids
        ):
            raise ValueError("specialist claim cites evidence not returned by its tool")
        return self


@dataclass(frozen=True)
class _ResponseRule:
    query_pattern: re.Pattern[str]
    doc_id: str | None
    evidence_phrase: str | None
    claim_text: str
    response_text: str


def _rule(
    query_pattern: str,
    *,
    doc_id: str | None,
    evidence_phrase: str | None,
    claim_text: str,
    response_text: str | None = None,
) -> _ResponseRule:
    return _ResponseRule(
        query_pattern=re.compile(query_pattern, re.IGNORECASE),
        doc_id=doc_id,
        evidence_phrase=evidence_phrase,
        claim_text=claim_text,
        response_text=response_text or claim_text,
    )


_PRODUCT_RULES = (
    _rule(
        r"\bsaml\b",
        doc_id="PROD-AVAIL-001",
        evidence_phrase="SAML 2.0: GA on Enterprise Cloud and Standard Cloud",
        claim_text=(
            "SAML 2.0 is generally available on Enterprise Cloud and Standard Cloud."
        ),
    ),
    _rule(
        r"\bscim\b|identity provisioning",
        doc_id="PROD-AVAIL-001",
        evidence_phrase="SCIM 2.0: GA on Enterprise Cloud",
        claim_text="SCIM 2.0 is generally available on Enterprise Cloud.",
    ),
    _rule(
        r"customer-managed (?:encryption )?keys?|\bcmk\b|\bbyok\b",
        doc_id="PROD-AVAIL-001",
        evidence_phrase="Customer-managed encryption keys: GA on Enterprise Cloud for AWS only",
        claim_text=(
            "Customer-managed encryption keys are generally available only for "
            "AWS-hosted Enterprise Cloud."
        ),
    ),
    _rule(
        r"deployment (?:models?|environments?)|\bstandard cloud\b|\benterprise cloud\b",
        doc_id="PROD-DEPLOY-001",
        evidence_phrase="Northstar-operated",
        claim_text=(
            "Standard Cloud and Enterprise Cloud are Northstar-operated cloud "
            "deployment models with different capability boundaries."
        ),
    ),
    _rule(
        r"on-premises|kubernetes|private data center|customer-operated",
        doc_id="PROD-DEPLOY-001",
        evidence_phrase="Customer-operated on-premises deployment is unsupported",
        claim_text=(
            "Customer-operated on-premises deployment, a customer-managed Kubernetes "
            "distribution, and private data-center installation are unsupported in V1."
        ),
        response_text=(
            "No. Customer-operated on-premises deployment, a customer-managed "
            "Kubernetes distribution, and private data-center installation are "
            "unsupported in V1."
        ),
    ),
    _rule(
        r"\bsalesforce\b",
        doc_id="PROD-AVAIL-001",
        evidence_phrase="Salesforce connector: GA on Enterprise Cloud",
        claim_text="The Salesforce connector is generally available on Enterprise Cloud.",
    ),
    _rule(
        r"sap\s+s/4hana",
        doc_id="PROD-AVAIL-001",
        evidence_phrase="SAP S/4HANA connector: ROADMAP",
        claim_text=(
            "The SAP S/4HANA connector is a roadmap item and is not generally available."
        ),
        response_text=(
            "The SAP S/4HANA connector is ROADMAP, not generally available, and has no "
            "customer-committable delivery date."
        ),
    ),
    _rule(
        r"uptime|\bsla\b|service credits?",
        doc_id="PROD-SLA-001",
        evidence_phrase="standard monthly service-availability target",
        claim_text=(
            "The documented standard monthly service-availability target is 99.9%."
        ),
        response_text=(
            "The documented standard target is 99.9%; the requested 99.99% SLA and "
            "service-credit commitment are not accepted without required approval."
        ),
    ),
)


_SECURITY_RULES = (
    _rule(
        r"fips\s+140-3",
        doc_id="SEC-CTRL-001",
        evidence_phrase="not certified to FIPS 140-3",
        claim_text="Northstar is not certified to FIPS 140-3.",
        response_text="No. The platform is not certified to FIPS 140-3.",
    ),
    _rule(
        r"fedramp\s+high",
        doc_id=None,
        evidence_phrase=None,
        claim_text="The available approved evidence establishes FedRAMP High authorization.",
        response_text=(
            "The available approved evidence does not establish FedRAMP High "
            "authorization, so the requirement cannot be confirmed."
        ),
    ),
    _rule(
        r"\btls\b|encrypted in transit",
        doc_id="SEC-CTRL-001",
        evidence_phrase="TLS 1.2 or later",
        claim_text=(
            "Supported application and API connections use TLS 1.2 or later in transit."
        ),
    ),
    _rule(
        r"aes-?256|encrypted .{0,30}at rest|encryption .{0,30}at rest",
        doc_id="SEC-CTRL-001",
        evidence_phrase="Data at rest is encrypted using AES-256",
        claim_text="Data at rest is encrypted using AES-256.",
    ),
    _rule(
        r"soc 2(?: type ii)?",
        doc_id="SEC-CTRL-001",
        evidence_phrase="current SOC 2 Type II report",
        claim_text="Northstar has a current SOC 2 Type II report.",
    ),
    _rule(
        r"iso 27001",
        doc_id="SEC-CTRL-001",
        evidence_phrase="certified to ISO 27001",
        claim_text="Northstar is certified to ISO 27001.",
    ),
    _rule(
        r"customer-managed (?:encryption )?keys?|\bcmk\b|\bbyok\b",
        doc_id="SEC-CTRL-001",
        evidence_phrase="AWS-hosted Enterprise Cloud deployments",
        claim_text=(
            "Security evidence covers customer-managed encryption keys only for "
            "AWS-hosted Enterprise Cloud deployments."
        ),
    ),
    _rule(
        r"enterprise cloud.{0,80}(?:european union|eu)|(?:european union|eu).{0,80}enterprise cloud",
        doc_id="SEC-DATA-001",
        evidence_phrase="European Union for Enterprise Cloud",
        claim_text=(
            "Enterprise Cloud supports customer-data residency in the European Union."
        ),
    ),
    _rule(
        r"standard cloud.{0,80}(?:european union|eu)|(?:european union|eu).{0,80}standard cloud",
        doc_id="SEC-DATA-001",
        evidence_phrase="Standard Cloud is hosted in the United States",
        claim_text=(
            "Standard Cloud is hosted in the United States and does not offer "
            "customer-selected European Union residency."
        ),
        response_text=(
            "No. Standard Cloud is hosted in the United States and does not offer "
            "customer-selected European Union residency."
        ),
    ),
    _rule(
        r"outside the european union|outside (?:the )?eu|ever access",
        doc_id="SEC-DATA-001",
        evidence_phrase="does not guarantee that every operational activity",
        claim_text=(
            "European Union residency does not guarantee that every support or "
            "operational activity remains inside the region."
        ),
        response_text=(
            "The requested absolute no-cross-border-access guarantee is not supported "
            "by the standard and requires security and legal review."
        ),
    ),
    _rule(
        r"retain(?:ed|s|tion)?|retention|how many calendar days",
        doc_id="SEC-RET-001",
        evidence_phrase="retains customer content for 30 calendar days",
        claim_text=(
            "The Customer Data Retention Standard states a 30-calendar-day "
            "post-termination period."
        ),
    ),
    _rule(
        r"retain(?:ed|s|tion)?|retention|how many calendar days",
        doc_id="SEC-RET-OPS-001",
        evidence_phrase="90-calendar-day recovery window",
        claim_text=(
            "The Data Retention Operations Addendum states a 90-calendar-day "
            "post-termination recovery window."
        ),
    ),
    _rule(
        r"delet(?:e|ing).{0,80}(?:24 hours|termination)|24 hours.{0,80}delet",
        doc_id="SEC-RET-001",
        evidence_phrase="does not authorize immediate deletion",
        claim_text=(
            "The approved standard does not authorize immediate or customer-specific "
            "post-termination deletion deadlines."
        ),
        response_text=(
            "The requested 24-hour deletion commitment is not authorized by the "
            "approved standard and requires human review."
        ),
    ),
)


_IMPLEMENTATION_RULES = (
    _rule(
        r"implementation plan|typical implementation|standard (?:delivery|phases)",
        doc_id="IMPL-GUIDE-001",
        evidence_phrase="The standard phases are kickoff and discovery",
        claim_text=(
            "The standard implementation phases run from kickoff and discovery through "
            "production readiness review."
        ),
    ),
    _rule(
        r"duration|timeline|how long|six to eight weeks",
        doc_id="IMPL-GUIDE-001",
        evidence_phrase="six to eight weeks after prerequisites are complete",
        claim_text=(
            "A typical Enterprise Cloud implementation lasts six to eight weeks after "
            "prerequisites are complete."
        ),
        response_text=(
            "The typical planning range is six to eight weeks after prerequisites are "
            "complete; it is not a guaranteed completion date."
        ),
    ),
    _rule(
        r"when the timeline begins|prerequisites?|timeline begins",
        doc_id="IMPL-GUIDE-001",
        evidence_phrase="begins only after scope, access, staffing, and technical prerequisites",
        claim_text=(
            "The implementation schedule begins only after scope, access, staffing, "
            "and technical prerequisites are confirmed."
        ),
    ),
    _rule(
        r"customer (?:responsibilities|roles)|test resources|required during implementation",
        doc_id="IMPL-GUIDE-001",
        evidence_phrase="The customer provides an executive sponsor",
        claim_text=(
            "The customer provides an executive sponsor, project manager, technical "
            "owners, security contacts, and representative test users."
        ),
    ),
    _rule(
        r"conditions that can change|affect scope|complex custom integration|scope change",
        doc_id="IMPL-GUIDE-001",
        evidence_phrase="Complex custom integrations",
        claim_text=(
            "Complex custom integrations or material scope changes can change the "
            "timeline and require a separately approved implementation plan."
        ),
        response_text=(
            "Complex custom integrations can change scope and timeline and require a "
            "separately approved implementation plan; no contractual date is implied."
        ),
    ),
)


_EXPECTED_METHODS = {
    Domain.PRODUCT: RetrievalMethod.HYBRID,
    Domain.SECURITY: RetrievalMethod.HYBRID,
    Domain.IMPLEMENTATION: RetrievalMethod.SEMANTIC_SUBSTITUTE,
}


def _matching_evidence(
    rule: _ResponseRule,
    evidence: list[EvidenceChunk],
) -> EvidenceChunk | None:
    if rule.doc_id is None or rule.evidence_phrase is None:
        return None
    phrase = rule.evidence_phrase.casefold()
    return next(
        (
            item
            for item in evidence
            if item.doc_id == rule.doc_id and phrase in item.text.casefold()
        ),
        None,
    )


def _run_specialist(
    requirement: Requirement,
    retriever: SpecialistRetriever,
    *,
    domain: Domain,
    rules: tuple[_ResponseRule, ...],
    query_override: str | None = None,
) -> SpecialistNodeResult:
    if requirement.prompt_injection_detected:
        raise SpecialistBoundaryError("prompt-injection content cannot enter a specialist")
    if domain not in requirement.assigned_domains:
        raise SpecialistBoundaryError(
            f"{domain.value} specialist was not selected for this requirement"
        )
    if retriever.domain is not domain:
        raise SpecialistBoundaryError(
            f"{domain.value} specialist received a {retriever.domain.value} retriever"
        )

    if query_override is not None and not query_override.strip():
        raise SpecialistBoundaryError("specialist query override cannot be blank")
    query = (
        query_override
        if query_override is not None
        else "\n".join(requirement.atomic_requirements) or requirement.original_text
    )
    evidence = retriever.search(query, k=5)
    expected_method = _EXPECTED_METHODS[domain]
    if any(item.retrieval_method is not expected_method for item in evidence):
        raise SpecialistBoundaryError(
            f"{domain.value} specialist received the wrong retrieval method"
        )

    claims: list[Claim] = []
    responses: list[str] = []
    seen_claims: set[str] = set()
    for rule in rules:
        if not rule.query_pattern.search(requirement.original_text):
            continue
        if rule.claim_text in seen_claims:
            continue
        matched_evidence = _matching_evidence(rule, evidence)
        supported = matched_evidence is not None
        claims.append(
            Claim(
                claim_id=f"{domain.value}-claim-{len(claims) + 1:03d}",
                text=rule.claim_text,
                evidence_ids=[matched_evidence.chunk_id] if matched_evidence else [],
                supported=supported,
            )
        )
        responses.append(
            rule.response_text
            if supported or rule.doc_id is None
            else f"Available retrieved evidence does not confirm: {rule.claim_text}"
        )
        seen_claims.add(rule.claim_text)

    if not claims:
        claims = [
            Claim(
                claim_id=f"{domain.value}-claim-001",
                text=(
                    f"The available {domain.value} evidence establishes the requested "
                    "capability or commitment."
                ),
                evidence_ids=[],
                supported=False,
            )
        ]
        responses = [
            (
                f"The available {domain.value} evidence does not establish the requested "
                "capability or commitment."
            )
        ]

    output = SpecialistOutput(
        specialist=domain,
        claims=claims,
        proposed_answer=" ".join(responses),
        support_status=aggregate_support(claims),
    )
    return SpecialistNodeResult(output=output, evidence=evidence)


def product_specialist_node(
    requirement: Requirement,
    retriever: SpecialistRetriever,
    *,
    query_override: str | None = None,
) -> SpecialistNodeResult:
    """Use Product hybrid retrieval and preserve availability boundaries."""

    return _run_specialist(
        requirement,
        retriever,
        domain=Domain.PRODUCT,
        rules=_PRODUCT_RULES,
        query_override=query_override,
    )


def security_specialist_node(
    requirement: Requirement,
    retriever: SpecialistRetriever,
    *,
    query_override: str | None = None,
) -> SpecialistNodeResult:
    """Use Security hybrid retrieval and never infer an unevidenced control."""

    return _run_specialist(
        requirement,
        retriever,
        domain=Domain.SECURITY,
        rules=_SECURITY_RULES,
        query_override=query_override,
    )


def implementation_specialist_node(
    requirement: Requirement,
    retriever: SpecialistRetriever,
    *,
    query_override: str | None = None,
) -> SpecialistNodeResult:
    """Use semantic retrieval and qualify timelines and dependencies."""

    return _run_specialist(
        requirement,
        retriever,
        domain=Domain.IMPLEMENTATION,
        rules=_IMPLEMENTATION_RULES,
        query_override=query_override,
    )
