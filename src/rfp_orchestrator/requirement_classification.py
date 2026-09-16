"""Deterministic Step 2.3 requirement domains, attributes, ambiguity, and initial risk."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rfp_orchestrator.models import (
    AmbiguitySignal,
    AmbiguitySignalType,
    Domain,
    Requirement,
    RequirementAttribute,
    RiskClass,
)
from rfp_orchestrator.prompt_injection import assess_prompt_injection
from rfp_orchestrator.requirement_analyzer import analyze_requirement


def _pattern(expression: str) -> re.Pattern[str]:
    return re.compile(expression, re.IGNORECASE)


_DOMAIN_PATTERNS: dict[Domain, tuple[re.Pattern[str], ...]] = {
    Domain.PRODUCT: (
        _pattern(r"\b(?:saml|scim|single sign-on|identity provisioning)\b"),
        _pattern(r"\b(?:salesforce|sap\s+s/4hana|connectors?)\b"),
        _pattern(r"\b(?:deployment models?|on-premises|kubernetes|private data center)\b"),
        _pattern(r"\b(?:standard cloud|enterprise cloud|product availability|generally available)\b"),
        _pattern(r"\b(?:uptime|sla|service credits?)\b"),
        _pattern(r"\bcustomer-managed encryption keys?\b"),
    ),
    Domain.SECURITY: (
        _pattern(r"\b(?:fips|fedramp|soc 2|iso 27001|certif(?:ied|ication))\b"),
        _pattern(r"\b(?:tls|aes-?256|encrypt(?:ed|ion)|security controls?)\b"),
        _pattern(r"\bcustomer-managed encryption keys?\b"),
        _pattern(r"\b(?:data residency|customer content|production backups?)\b"),
        _pattern(r"\b(?:retention|retain(?:ed|s)?|delet(?:e|ing|ion))\b"),
        _pattern(r"\b(?:outside the european union|access customer data)\b"),
    ),
    Domain.IMPLEMENTATION: (
        _pattern(r"\b(?:implementation|onboarding|go-live|rollout)\b"),
        _pattern(r"\b(?:prerequisites?|customer responsibilities|customer roles?)\b"),
        _pattern(r"\b(?:timeline|duration|project manager|test resources?)\b"),
        _pattern(r"\b(?:complex custom integration|scope change|implementation approval)\b"),
    ),
}


@dataclass(frozen=True)
class _AmbiguityRule:
    signal_type: AmbiguitySignalType
    pattern: re.Pattern[str]
    reason: str


_AMBIGUITY_RULES = (
    _AmbiguityRule(
        AmbiguitySignalType.RELATIVE_TIMEFRAME,
        _pattern(r"\b(?:this|next)\s+(?:quarter|month|year)\b"),
        "Relative timeframe requires a concrete reference date before commitment.",
    ),
    _AmbiguityRule(
        AmbiguitySignalType.UNDEFINED_TIMEFRAME,
        _pattern(r"\b(?:as soon as possible|promptly|timely|immediately)\b"),
        "Time expectation has no measurable deadline.",
    ),
    _AmbiguityRule(
        AmbiguitySignalType.UNBOUNDED_SCOPE,
        _pattern(r"\b(?:all|any|every)\s+(?:regions?|environments?|deployment models?)\b"),
        "Scope is universal but the applicable boundary is not defined.",
    ),
    _AmbiguityRule(
        AmbiguitySignalType.ABSOLUTE_LANGUAGE,
        _pattern(
            r"\b(?:never|ever|unlimited|without exception)\b|"
            r"\ball customer content and backup copies\b"
        ),
        "Absolute language may exceed documented scope or organizational authority.",
    ),
)


def assign_domains(text: str) -> list[Domain]:
    """Return stable peer-specialist domains from explicit V1 indicators."""

    return [
        domain
        for domain in (Domain.PRODUCT, Domain.SECURITY, Domain.IMPLEMENTATION)
        if any(pattern.search(text) for pattern in _DOMAIN_PATTERNS[domain])
    ]


def detect_ambiguity(text: str) -> list[AmbiguitySignal]:
    """Return source-grounded ambiguity signals in textual order."""

    signals = [
        AmbiguitySignal(
            signal_type=rule.signal_type,
            matched_text=match.group(0),
            start_index=match.start(),
            end_index=match.end(),
            reason=rule.reason,
        )
        for rule in _AMBIGUITY_RULES
        for match in rule.pattern.finditer(text)
    ]
    signals.sort(key=lambda item: (item.start_index, item.end_index, item.signal_type.value))
    return signals


def classify_attributes(requirement: Requirement) -> list[RequirementAttribute]:
    text = requirement.original_text
    checks = (
        (
            RequirementAttribute.INFORMATION_REQUEST,
            _pattern(r"\b(?:describe|explain|state|list|identify)\b").search(text),
        ),
        (
            RequirementAttribute.CONFIRMATION_REQUEST,
            _pattern(r"\b(?:confirm|whether)\b").search(text),
        ),
        (
            RequirementAttribute.COMMITMENT_REQUEST,
            _pattern(
                r"\b(?:commit|guarantee|accept)\b|\bwill be delivered\b|"
                r"\bwithin\s+\d+\s+(?:hours?|days?)\b"
            ).search(text),
        ),
        (RequirementAttribute.COMPARISON_REQUEST, _pattern(r"\bcompare\b").search(text)),
        (RequirementAttribute.DELIVERABLE_REQUEST, _pattern(r"\bprovide\b").search(text)),
        (
            RequirementAttribute.ABSOLUTE_LANGUAGE,
            bool(detect_ambiguity(text))
            and any(
                signal.signal_type
                in {AmbiguitySignalType.ABSOLUTE_LANGUAGE, AmbiguitySignalType.UNBOUNDED_SCOPE}
                for signal in detect_ambiguity(text)
            ),
        ),
        (
            RequirementAttribute.TIME_BOUND_REQUEST,
            _pattern(
                r"\b(?:this|next)\s+(?:quarter|month|year)\b|"
                r"\bwithin\s+\d+\s+(?:hours?|days?)\b"
            ).search(text),
        ),
        (
            RequirementAttribute.UNTRUSTED_INSTRUCTION,
            requirement.prompt_injection_detected,
        ),
    )
    return [attribute for attribute, matched in checks if matched]


def detect_initial_risks(text: str) -> list[RiskClass]:
    """Return text-only risk candidates; evidence-dependent risks remain unset."""

    checks = (
        (
            RiskClass.ROADMAP_COMMITMENT,
            bool(_pattern(r"\bsap\s+s/4hana\b").search(text))
            and bool(_pattern(r"\b(?:commit|deliver(?:ed|y)?|this quarter)\b").search(text)),
        ),
        (
            RiskClass.SLA_OR_SERVICE_CREDIT,
            _pattern(r"\b99\.99%\b|\bservice credits?\b|\buptime sla\b").search(text),
        ),
        (
            RiskClass.PRICING_OR_DISCOUNT,
            _pattern(r"\b(?:pricing|price|discount)\b").search(text),
        ),
        (
            RiskClass.WARRANTY_OR_INDEMNITY,
            _pattern(r"\b(?:warrant(?:y|ies)|indemnity|indemnification)\b").search(text),
        ),
        (
            RiskClass.SECURITY_EXCEPTION,
            _pattern(
                r"\bguarantee\b.+\b(?:access|security|data)\b|"
                r"\bdelet(?:e|ing)\b.+\bwithin\s+24\s+hours\b|"
                r"\bsecurity exception\b"
            ).search(text),
        ),
        (
            RiskClass.DATA_RESIDENCY_AMBIGUITY,
            _pattern(r"\boutside the european union\b.+\bever\b").search(text),
        ),
    )
    return [risk for risk, matched in checks if matched]


def classify_requirement(requirement: Requirement) -> Requirement:
    """Return a validated copy with Step 2.3 fields and all earlier analysis preserved."""

    searchable_text = "\n".join(
        [requirement.original_text, *requirement.atomic_requirements]
    )
    ambiguity_signals = detect_ambiguity(requirement.original_text)
    payload = requirement.model_dump()
    payload.update(
        {
            "assigned_domains": [domain.value for domain in assign_domains(searchable_text)],
            "attributes": [item.value for item in classify_attributes(requirement)],
            "ambiguity_signals": [signal.model_dump() for signal in ambiguity_signals],
            "initial_risk_flags": [
                risk.value for risk in detect_initial_risks(requirement.original_text)
            ],
        }
    )
    return Requirement.model_validate(payload)


def analyze_requirement_input(requirement: Requirement) -> Requirement:
    """Run Steps 2.1–2.3 in order without mutating the caller's Requirement."""

    decomposed = analyze_requirement(requirement)
    injection_assessed = assess_prompt_injection(decomposed)
    return classify_requirement(injection_assessed)
