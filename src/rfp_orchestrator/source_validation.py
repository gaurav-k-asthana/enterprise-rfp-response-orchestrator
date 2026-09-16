"""Source lifecycle and authority-metadata validation for Step 2.12."""

from __future__ import annotations

from datetime import date, datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field, model_validator

from rfp_orchestrator.state import GraphState


class SourceIssueType(str, Enum):
    UPSTREAM_CITATION_INVALID = "UPSTREAM_CITATION_INVALID"
    CITED_EVIDENCE_MISSING = "CITED_EVIDENCE_MISSING"
    MISSING_CHUNK_ID = "MISSING_CHUNK_ID"
    MISSING_DOC_ID = "MISSING_DOC_ID"
    MISSING_VERSION = "MISSING_VERSION"
    INVALID_EFFECTIVE_DATE = "INVALID_EFFECTIVE_DATE"
    FUTURE_EFFECTIVE_DATE = "FUTURE_EFFECTIVE_DATE"
    INVALID_AUTHORITY_RANK = "INVALID_AUTHORITY_RANK"
    UNKNOWN_SOURCE_STATUS = "UNKNOWN_SOURCE_STATUS"
    ARCHIVED_CITATION = "ARCHIVED_CITATION"


class SourceIssue(BaseModel):
    issue_type: SourceIssueType
    evidence_id: str | None = None
    doc_id: str | None = None
    detail: str = Field(min_length=1)


class SourceValidationResult(BaseModel):
    valid: bool
    as_of_date: str
    current_evidence_ids: list[str] = Field(default_factory=list)
    archived_evidence_ids: list[str] = Field(default_factory=list)
    eligible_cited_evidence_ids: list[str] = Field(default_factory=list)
    authority_by_evidence: dict[str, int] = Field(default_factory=dict)
    lowest_cited_authority_rank: int | None = None
    issues: list[SourceIssue] = Field(default_factory=list)

    @model_validator(mode="after")
    def result_is_consistent(self) -> SourceValidationResult:
        if self.valid != (not self.issues):
            raise ValueError("source validation is valid exactly when issues are empty")
        if set(self.current_evidence_ids) & set(self.archived_evidence_ids):
            raise ValueError("evidence cannot be both current and archived")
        ranks = [
            self.authority_by_evidence[evidence_id]
            for evidence_id in self.eligible_cited_evidence_ids
            if evidence_id in self.authority_by_evidence
        ]
        expected_lowest = min(ranks) if ranks else None
        if self.lowest_cited_authority_rank != expected_lowest:
            raise ValueError("lowest cited authority rank does not match cited evidence")
        return self


def _issue(
    issue_type: SourceIssueType,
    *,
    detail: str,
    evidence_id: str | None = None,
    doc_id: str | None = None,
) -> SourceIssue:
    return SourceIssue(
        issue_type=issue_type,
        evidence_id=evidence_id,
        doc_id=doc_id,
        detail=detail,
    )


def validate_source_metadata(
    state: GraphState,
    *,
    as_of: date | None = None,
) -> SourceValidationResult:
    """Validate source metadata without making organizational-authority decisions."""

    validation_date = as_of or datetime.now(timezone.utc).date()
    issues: list[SourceIssue] = []
    if state.get("citation_valid") is not True:
        issues.append(
            _issue(
                SourceIssueType.UPSTREAM_CITATION_INVALID,
                detail="Citation membership must pass before source validation can pass.",
            )
        )

    cited_ids = set(
        (state.get("citation_validation") or {}).get("cited_evidence_ids", [])
    )
    evidence_by_id: dict[str, dict] = {}
    current_ids: list[str] = []
    archived_ids: list[str] = []
    eligible_cited_ids: list[str] = []
    authority_by_evidence: dict[str, int] = {}

    for index, item in enumerate(state.get("evidence", []), start=1):
        raw_chunk_id = item.get("chunk_id")
        chunk_id = raw_chunk_id.strip() if isinstance(raw_chunk_id, str) else ""
        raw_doc_id = item.get("doc_id")
        doc_id = raw_doc_id.strip() if isinstance(raw_doc_id, str) else ""
        raw_version = item.get("version")
        version = raw_version.strip() if isinstance(raw_version, str) else ""
        evidence_label = chunk_id or f"evidence-position-{index}"
        if not chunk_id:
            issues.append(
                _issue(
                    SourceIssueType.MISSING_CHUNK_ID,
                    evidence_id=evidence_label,
                    doc_id=doc_id or None,
                    detail="Evidence is missing a nonblank chunk ID.",
                )
            )
        else:
            evidence_by_id[chunk_id] = item
        if not doc_id:
            issues.append(
                _issue(
                    SourceIssueType.MISSING_DOC_ID,
                    evidence_id=evidence_label,
                    detail="Evidence is missing a nonblank document ID.",
                )
            )
        if not version:
            issues.append(
                _issue(
                    SourceIssueType.MISSING_VERSION,
                    evidence_id=evidence_label,
                    doc_id=doc_id or None,
                    detail="Evidence is missing a nonblank version.",
                )
            )

        raw_rank = item.get("authority_rank")
        rank_valid = (
            isinstance(raw_rank, int)
            and not isinstance(raw_rank, bool)
            and 1 <= raw_rank <= 5
        )
        if not rank_valid:
            issues.append(
                _issue(
                    SourceIssueType.INVALID_AUTHORITY_RANK,
                    evidence_id=evidence_label,
                    doc_id=doc_id or None,
                    detail="Authority rank must be an integer from 1 through 5.",
                )
            )
        elif chunk_id:
            authority_by_evidence[chunk_id] = raw_rank

        raw_date = item.get("effective_date")
        try:
            effective_date = date.fromisoformat(raw_date)
        except (TypeError, ValueError):
            effective_date = None
            issues.append(
                _issue(
                    SourceIssueType.INVALID_EFFECTIVE_DATE,
                    evidence_id=evidence_label,
                    doc_id=doc_id or None,
                    detail="Effective date must be a valid ISO calendar date.",
                )
            )
        if effective_date and effective_date > validation_date:
            issues.append(
                _issue(
                    SourceIssueType.FUTURE_EFFECTIVE_DATE,
                    evidence_id=evidence_label,
                    doc_id=doc_id or None,
                    detail="Evidence is not yet effective on the validation date.",
                )
            )

        status = item.get("source_status")
        if status == "current":
            if chunk_id:
                current_ids.append(chunk_id)
        elif status == "archived":
            if chunk_id:
                archived_ids.append(chunk_id)
            if chunk_id in cited_ids:
                issues.append(
                    _issue(
                        SourceIssueType.ARCHIVED_CITATION,
                        evidence_id=chunk_id,
                        doc_id=doc_id or None,
                        detail="Archived evidence may be diagnostic but cannot support a current claim.",
                    )
                )
        else:
            issues.append(
                _issue(
                    SourceIssueType.UNKNOWN_SOURCE_STATUS,
                    evidence_id=evidence_label,
                    doc_id=doc_id or None,
                    detail="Source status must be current or archived.",
                )
            )

        item_is_eligible = (
            bool(chunk_id)
            and bool(doc_id)
            and bool(version)
            and rank_valid
            and effective_date is not None
            and effective_date <= validation_date
            and status == "current"
        )
        if chunk_id in cited_ids and item_is_eligible:
            eligible_cited_ids.append(chunk_id)

    for cited_id in sorted(cited_ids - set(evidence_by_id)):
        issues.append(
            _issue(
                SourceIssueType.CITED_EVIDENCE_MISSING,
                evidence_id=cited_id,
                detail="Cited evidence is absent from the merged evidence view.",
            )
        )

    cited_ranks = [authority_by_evidence[item] for item in eligible_cited_ids]
    return SourceValidationResult(
        valid=not issues,
        as_of_date=validation_date.isoformat(),
        current_evidence_ids=current_ids,
        archived_evidence_ids=archived_ids,
        eligible_cited_evidence_ids=eligible_cited_ids,
        authority_by_evidence=authority_by_evidence,
        lowest_cited_authority_rank=min(cited_ranks) if cited_ranks else None,
        issues=issues,
    )


def source_validation_node(state: GraphState) -> GraphState:
    result = validate_source_metadata(state)
    return {
        "source_metadata_valid": result.valid,
        "source_validation": result.model_dump(mode="json"),
    }
