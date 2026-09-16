"""Independent atomic-claim support adjudication for Step 2.13."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from rfp_orchestrator.models import (
    Claim,
    Domain,
    SpecialistOutput,
    SupportStatus,
    aggregate_support,
)
from rfp_orchestrator.state import GraphState


class ClaimSupportIssueType(str, Enum):
    UPSTREAM_CITATION_INVALID = "UPSTREAM_CITATION_INVALID"
    UPSTREAM_SOURCE_INVALID = "UPSTREAM_SOURCE_INVALID"
    MISSING_SPECIALIST_OUTPUT = "MISSING_SPECIALIST_OUTPUT"
    SPECIALIST_MISMATCH = "SPECIALIST_MISMATCH"
    MISSING_ATOMIC_CLAIMS = "MISSING_ATOMIC_CLAIMS"
    BLANK_CLAIM_ID = "BLANK_CLAIM_ID"
    DUPLICATE_CLAIM_ID = "DUPLICATE_CLAIM_ID"
    BLANK_CLAIM_TEXT = "BLANK_CLAIM_TEXT"
    DUPLICATE_CLAIM_TEXT = "DUPLICATE_CLAIM_TEXT"
    INVALID_PROVISIONAL_SUPPORT = "INVALID_PROVISIONAL_SUPPORT"
    INELIGIBLE_EVIDENCE = "INELIGIBLE_EVIDENCE"
    EVIDENCE_DOES_NOT_SUPPORT_CLAIM = "EVIDENCE_DOES_NOT_SUPPORT_CLAIM"
    PROVISIONAL_SUPPORT_MISMATCH = "PROVISIONAL_SUPPORT_MISMATCH"
    AGGREGATE_STATUS_MISMATCH = "AGGREGATE_STATUS_MISMATCH"


class ClaimSupportIssue(BaseModel):
    issue_type: ClaimSupportIssueType
    specialist: str | None = None
    claim_id: str | None = None
    evidence_id: str | None = None
    detail: str = Field(min_length=1)


class AtomicClaimAssessment(BaseModel):
    specialist: Domain
    claim_id: str
    text: str
    evidence_ids: list[str] = Field(default_factory=list)
    supported: bool
    lexical_coverage: float = Field(ge=0.0, le=1.0)
    rationale: str = Field(min_length=1)


class SpecialistSupportAssessment(BaseModel):
    specialist: Domain
    claims: list[AtomicClaimAssessment] = Field(default_factory=list)
    support_status: SupportStatus

    @model_validator(mode="after")
    def aggregate_matches_claims(self) -> SpecialistSupportAssessment:
        expected = aggregate_support(
            [
                Claim(
                    claim_id=claim.claim_id,
                    text=claim.text,
                    evidence_ids=claim.evidence_ids,
                    supported=claim.supported,
                )
                for claim in self.claims
            ]
        )
        if self.support_status is not expected:
            raise ValueError("specialist support status must aggregate assessed claims")
        return self


class ClaimSupportValidationResult(BaseModel):
    valid: bool
    assessments: list[SpecialistSupportAssessment] = Field(default_factory=list)
    support_status_by_specialist: dict[str, SupportStatus] = Field(default_factory=dict)
    issues: list[ClaimSupportIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def result_is_consistent(self) -> ClaimSupportValidationResult:
        if self.valid != (not self.issues):
            raise ValueError("claim support validation is valid exactly when issues are empty")
        expected = {
            assessment.specialist.value: assessment.support_status
            for assessment in self.assessments
        }
        if self.support_status_by_specialist != expected:
            raise ValueError("support status map must match specialist assessments")
        return self


_TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "has",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "through",
        "to",
        "with",
    }
)
_TOKEN_EQUIVALENTS = {
    "availability": "available",
    "certification": "certify",
    "certified": "certify",
    "changes": "change",
    "confirmed": "confirm",
    "connections": "connection",
    "deployments": "deployment",
    "encrypted": "encrypt",
    "encryption": "encrypt",
    "ga": "available",
    "implementation": "implement",
    "integrations": "integration",
    "operated": "operate",
    "operational": "operate",
    "operations": "operate",
    "phases": "phase",
    "prerequisites": "prerequisite",
    "protected": "protect",
    "provides": "provide",
    "retains": "retain",
    "retention": "retain",
    "states": "state",
    "supported": "support",
    "supports": "support",
}
_MINIMUM_COVERAGE = 0.70


def _tokens(text: str) -> set[str]:
    normalized = text.casefold().replace("-", " ")
    return {
        _TOKEN_EQUIVALENTS.get(token, token)
        for token in _TOKEN_PATTERN.findall(normalized)
        if token not in _STOP_WORDS
    }


def _evidence_supports_claim(
    claim_text: str,
    evidence_items: list[dict],
) -> tuple[bool, float]:
    claim_tokens = _tokens(claim_text)
    if not claim_tokens or not evidence_items:
        return False, 0.0
    evidence_tokens = _tokens(
        "\n".join(
            f"{item.get('title', '')}\n{item.get('text', '')}"
            for item in evidence_items
        )
    )
    coverage = len(claim_tokens & evidence_tokens) / len(claim_tokens)
    numeric_anchors = {
        token for token in claim_tokens if any(char.isdigit() for char in token)
    }
    if not numeric_anchors:
        return coverage >= _MINIMUM_COVERAGE, round(coverage, 3)

    best_statement_coverage = 0.0
    for item in evidence_items:
        title = str(item.get("title", ""))
        statements = re.split(r"(?<=[.!?])\s+|\n+", str(item.get("text", "")))
        for statement in statements:
            statement_tokens = _tokens(f"{title} {statement}")
            if not numeric_anchors <= statement_tokens:
                continue
            statement_coverage = len(claim_tokens & statement_tokens) / len(claim_tokens)
            best_statement_coverage = max(
                best_statement_coverage,
                statement_coverage,
            )
    return (
        best_statement_coverage >= _MINIMUM_COVERAGE,
        round(best_statement_coverage, 3),
    )


def _issue(
    issue_type: ClaimSupportIssueType,
    *,
    detail: str,
    specialist: str | None = None,
    claim_id: str | None = None,
    evidence_id: str | None = None,
) -> ClaimSupportIssue:
    return ClaimSupportIssue(
        issue_type=issue_type,
        specialist=specialist,
        claim_id=claim_id,
        evidence_id=evidence_id,
        detail=detail,
    )


def adjudicate_atomic_claims(
    state: GraphState,
) -> tuple[ClaimSupportValidationResult, dict[str, dict]]:
    """Recompute atomic support from eligible cited evidence, not provisional flags."""

    issues: list[ClaimSupportIssue] = []
    if state.get("citation_valid") is not True:
        issues.append(
            _issue(
                ClaimSupportIssueType.UPSTREAM_CITATION_INVALID,
                detail="Citation membership must pass before claim support can pass.",
            )
        )
    if state.get("source_metadata_valid") is not True:
        issues.append(
            _issue(
                ClaimSupportIssueType.UPSTREAM_SOURCE_INVALID,
                detail="Source metadata must pass before claim support can pass.",
            )
        )

    eligible_ids = set(
        (state.get("source_validation") or {}).get(
            "eligible_cited_evidence_ids", []
        )
    )
    evidence_by_id = {
        str(item.get("chunk_id", "")): item for item in state.get("evidence", [])
    }
    raw_outputs = state.get("specialist_outputs", {})
    validated_outputs: dict[str, dict] = {}
    assessments: list[SpecialistSupportAssessment] = []

    for specialist_key in state.get("merge_order", []):
        raw_output = raw_outputs.get(specialist_key)
        if not isinstance(raw_output, dict):
            issues.append(
                _issue(
                    ClaimSupportIssueType.MISSING_SPECIALIST_OUTPUT,
                    specialist=specialist_key,
                    detail="Merged specialist has no structured output.",
                )
            )
            continue

        specialist = Domain(specialist_key)
        if raw_output.get("specialist") != specialist_key:
            issues.append(
                _issue(
                    ClaimSupportIssueType.SPECIALIST_MISMATCH,
                    specialist=specialist_key,
                    detail="Specialist output identity does not match its merge key.",
                )
            )

        raw_claims = raw_output.get("claims", [])
        if not isinstance(raw_claims, list):
            raw_claims = []
        if not raw_claims and str(raw_output.get("proposed_answer", "")).strip():
            issues.append(
                _issue(
                    ClaimSupportIssueType.MISSING_ATOMIC_CLAIMS,
                    specialist=specialist_key,
                    detail="A nonblank specialist draft must expose its atomic claims.",
                )
            )

        seen_ids: set[str] = set()
        seen_texts: set[str] = set()
        assessed_claims: list[AtomicClaimAssessment] = []
        corrected_claims: list[Claim] = []
        for position, raw_claim in enumerate(raw_claims, start=1):
            claim_id = str(raw_claim.get("claim_id", "")).strip()
            claim_text = str(raw_claim.get("text", "")).strip()
            evidence_ids = [str(value) for value in raw_claim.get("evidence_ids", [])]
            label = claim_id or f"{specialist_key}-claim-position-{position}"

            if not claim_id:
                issues.append(
                    _issue(
                        ClaimSupportIssueType.BLANK_CLAIM_ID,
                        specialist=specialist_key,
                        claim_id=label,
                        detail="Every atomic claim requires a nonblank stable ID.",
                    )
                )
            elif claim_id in seen_ids:
                issues.append(
                    _issue(
                        ClaimSupportIssueType.DUPLICATE_CLAIM_ID,
                        specialist=specialist_key,
                        claim_id=claim_id,
                        detail="Atomic claim IDs must be unique inside a specialist output.",
                    )
                )
            seen_ids.add(claim_id)

            normalized_text = " ".join(claim_text.casefold().split())
            if not claim_text:
                issues.append(
                    _issue(
                        ClaimSupportIssueType.BLANK_CLAIM_TEXT,
                        specialist=specialist_key,
                        claim_id=label,
                        detail="Every atomic claim requires nonblank material text.",
                    )
                )
            elif normalized_text in seen_texts:
                issues.append(
                    _issue(
                        ClaimSupportIssueType.DUPLICATE_CLAIM_TEXT,
                        specialist=specialist_key,
                        claim_id=label,
                        detail="Duplicate claim text must not inflate aggregate support.",
                    )
                )
            seen_texts.add(normalized_text)

            provisional = raw_claim.get("supported")
            if not isinstance(provisional, bool):
                issues.append(
                    _issue(
                        ClaimSupportIssueType.INVALID_PROVISIONAL_SUPPORT,
                        specialist=specialist_key,
                        claim_id=label,
                        detail="Provisional atomic support must be a Boolean.",
                    )
                )
                provisional = False

            ineligible_ids = [item for item in evidence_ids if item not in eligible_ids]
            for evidence_id in ineligible_ids:
                issues.append(
                    _issue(
                        ClaimSupportIssueType.INELIGIBLE_EVIDENCE,
                        specialist=specialist_key,
                        claim_id=label,
                        evidence_id=evidence_id,
                        detail="Claim cites evidence that is not eligible current support.",
                    )
                )

            evidence_items = [
                evidence_by_id[evidence_id]
                for evidence_id in evidence_ids
                if evidence_id in evidence_by_id and evidence_id in eligible_ids
            ]
            meaning_supported, coverage = _evidence_supports_claim(
                claim_text,
                evidence_items,
            )
            supported = bool(evidence_ids) and not ineligible_ids and meaning_supported
            if evidence_ids and not ineligible_ids and not meaning_supported:
                issues.append(
                    _issue(
                        ClaimSupportIssueType.EVIDENCE_DOES_NOT_SUPPORT_CLAIM,
                        specialist=specialist_key,
                        claim_id=label,
                        detail=(
                            "Eligible cited evidence does not meet the deterministic "
                            "material-term support threshold."
                        ),
                    )
                )
            if provisional is not supported:
                issues.append(
                    _issue(
                        ClaimSupportIssueType.PROVISIONAL_SUPPORT_MISMATCH,
                        specialist=specialist_key,
                        claim_id=label,
                        detail="Independent support judgment differs from the specialist flag.",
                    )
                )

            rationale = (
                "Eligible cited evidence covers the claim's material terms."
                if supported
                else (
                    "No evidence was cited, so the atomic claim is unsupported."
                    if not evidence_ids
                    else "Cited evidence is ineligible or does not support the material terms."
                )
            )
            assessed_claims.append(
                AtomicClaimAssessment(
                    specialist=specialist,
                    claim_id=label,
                    text=claim_text,
                    evidence_ids=evidence_ids,
                    supported=supported,
                    lexical_coverage=coverage,
                    rationale=rationale,
                )
            )
            corrected_claims.append(
                Claim(
                    claim_id=label,
                    text=claim_text,
                    evidence_ids=evidence_ids,
                    supported=supported,
                )
            )

        support_status = aggregate_support(corrected_claims)
        if raw_output.get("support_status") != support_status.value:
            issues.append(
                _issue(
                    ClaimSupportIssueType.AGGREGATE_STATUS_MISMATCH,
                    specialist=specialist_key,
                    detail=(
                        "Specialist aggregate status does not match independently "
                        "adjudicated atomic claims."
                    ),
                )
            )

        assessment = SpecialistSupportAssessment(
            specialist=specialist,
            claims=assessed_claims,
            support_status=support_status,
        )
        assessments.append(assessment)
        validated_outputs[specialist_key] = SpecialistOutput(
            specialist=specialist,
            claims=corrected_claims,
            proposed_answer=str(raw_output.get("proposed_answer", "")),
            support_status=support_status,
        ).model_dump(mode="json")

    result = ClaimSupportValidationResult(
        valid=not issues,
        assessments=assessments,
        support_status_by_specialist={
            assessment.specialist.value: assessment.support_status
            for assessment in assessments
        },
        issues=issues,
    )
    return result, validated_outputs


def claim_support_validation_node(state: GraphState) -> GraphState:
    result, validated_outputs = adjudicate_atomic_claims(state)
    merge_order = state.get("merge_order", [])
    return {
        "specialist_outputs": validated_outputs,
        "merged_specialist_outputs": [
            validated_outputs[key] for key in merge_order if key in validated_outputs
        ],
        "claim_support_valid": result.valid,
        "claim_support_validation": result.model_dump(mode="json"),
    }
