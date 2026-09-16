"""Structural citation and retrieved-evidence membership checks for Step 2.11."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, model_validator

from rfp_orchestrator.state import GraphState


class CitationIssueType(str, Enum):
    MISSING_CITATION = "MISSING_CITATION"
    UNKNOWN_CITATION = "UNKNOWN_CITATION"
    CROSS_SPECIALIST_CITATION = "CROSS_SPECIALIST_CITATION"
    DUPLICATE_CITATION = "DUPLICATE_CITATION"
    NOT_IN_MERGED_EVIDENCE = "NOT_IN_MERGED_EVIDENCE"
    DUPLICATE_EVIDENCE_ID = "DUPLICATE_EVIDENCE_ID"


class CitationIssue(BaseModel):
    issue_type: CitationIssueType
    specialist: str
    claim_id: str
    citation_id: str | None = None
    detail: str = Field(min_length=1)


class CitationValidationResult(BaseModel):
    valid: bool
    cited_evidence_ids: list[str] = Field(default_factory=list)
    issues: list[CitationIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_matches_issues(self) -> CitationValidationResult:
        if self.valid != (not self.issues):
            raise ValueError("citation validation is valid exactly when issues are empty")
        if len(self.cited_evidence_ids) != len(set(self.cited_evidence_ids)):
            raise ValueError("cited_evidence_ids cannot contain duplicates")
        return self


def _issue(
    issue_type: CitationIssueType,
    *,
    specialist: str,
    claim_id: str,
    detail: str,
    citation_id: str | None = None,
) -> CitationIssue:
    return CitationIssue(
        issue_type=issue_type,
        specialist=specialist,
        claim_id=claim_id,
        citation_id=citation_id,
        detail=detail,
    )


def validate_citation_membership(state: GraphState) -> CitationValidationResult:
    """Validate citation IDs without deciding whether claim meaning is supported."""

    specialist_outputs = state.get("specialist_outputs", {})
    specialist_evidence = state.get("specialist_evidence", {})
    merged_evidence = state.get("evidence", [])
    merged_ids = [str(item.get("chunk_id", "")) for item in merged_evidence]
    merged_id_set = set(merged_ids)
    all_branch_ids = {
        str(item.get("chunk_id", ""))
        for items in specialist_evidence.values()
        for item in items
    }

    issues: list[CitationIssue] = []
    duplicate_merged_ids = {
        evidence_id
        for evidence_id in merged_id_set
        if evidence_id and merged_ids.count(evidence_id) > 1
    }
    for evidence_id in sorted(duplicate_merged_ids):
        issues.append(
            _issue(
                CitationIssueType.DUPLICATE_EVIDENCE_ID,
                specialist="merge",
                claim_id="",
                citation_id=evidence_id,
                detail="Merged evidence contains the same chunk ID more than once.",
            )
        )

    cited_ids: list[str] = []
    for specialist in state.get("merge_order", []):
        output = specialist_outputs.get(specialist, {})
        branch_ids = {
            str(item.get("chunk_id", ""))
            for item in specialist_evidence.get(specialist, [])
        }
        for raw_claim in output.get("claims", []):
            claim_id = str(raw_claim.get("claim_id", ""))
            citation_ids = [str(value) for value in raw_claim.get("evidence_ids", [])]
            if raw_claim.get("supported") is True and not citation_ids:
                issues.append(
                    _issue(
                        CitationIssueType.MISSING_CITATION,
                        specialist=specialist,
                        claim_id=claim_id,
                        detail="A provisionally supported claim has no citation ID.",
                    )
                )

            seen_in_claim: set[str] = set()
            for citation_id in citation_ids:
                if citation_id in seen_in_claim:
                    issues.append(
                        _issue(
                            CitationIssueType.DUPLICATE_CITATION,
                            specialist=specialist,
                            claim_id=claim_id,
                            citation_id=citation_id,
                            detail="The claim repeats the same citation ID.",
                        )
                    )
                    continue
                seen_in_claim.add(citation_id)
                if citation_id not in all_branch_ids:
                    issues.append(
                        _issue(
                            CitationIssueType.UNKNOWN_CITATION,
                            specialist=specialist,
                            claim_id=claim_id,
                            citation_id=citation_id,
                            detail="Citation ID was not returned by any specialist retrieval.",
                        )
                    )
                    continue
                if citation_id not in branch_ids:
                    issues.append(
                        _issue(
                            CitationIssueType.CROSS_SPECIALIST_CITATION,
                            specialist=specialist,
                            claim_id=claim_id,
                            citation_id=citation_id,
                            detail="Citation belongs to another specialist branch.",
                        )
                    )
                    continue
                if citation_id not in merged_id_set:
                    issues.append(
                        _issue(
                            CitationIssueType.NOT_IN_MERGED_EVIDENCE,
                            specialist=specialist,
                            claim_id=claim_id,
                            citation_id=citation_id,
                            detail="Citation was retrieved but is absent from merged evidence.",
                        )
                    )
                    continue
                if citation_id not in cited_ids:
                    cited_ids.append(citation_id)

    return CitationValidationResult(
        valid=not issues,
        cited_evidence_ids=cited_ids,
        issues=issues,
    )


def citation_validation_node(state: GraphState) -> GraphState:
    result = validate_citation_membership(state)
    return {
        "citation_valid": result.valid,
        "citation_validation": result.model_dump(mode="json"),
    }
