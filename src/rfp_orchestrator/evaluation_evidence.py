"""Reviewed Step 4.4 gold evidence and source-authority ordering."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.corpus import CorpusChunk, SourceStatus, load_corpus_chunks
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    EXPECTED_CASE_IDS,
    EvaluationCase,
    EvaluationDataset,
    ExpectedAuthorityTier,
    load_evaluation_dataset,
)

KB_DIRECTORY = DEFAULT_EVALUATION_DATASET_PATH.parents[1] / "kb"


class EvidenceAssignment(BaseModel):
    """Gold answer evidence grouped by source precedence for one case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    authority_tiers: list[ExpectedAuthorityTier] = Field(default_factory=list)
    evidence_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def assignment_is_clean(self) -> EvidenceAssignment:
        flattened = [
            evidence_id
            for tier in self.authority_tiers
            for evidence_id in tier.evidence_ids
        ]
        if len(flattened) != len(set(flattened)):
            raise ValueError("gold evidence IDs cannot appear in multiple authority tiers")
        if not self.evidence_reason.strip():
            raise ValueError("evidence reason cannot be blank")
        return self

    @property
    def evidence_ids(self) -> list[str]:
        return [
            evidence_id
            for tier in self.authority_tiers
            for evidence_id in tier.evidence_ids
        ]


def _tier(
    authority_rank: int,
    *evidence_ids: str,
    status: SourceStatus = SourceStatus.CURRENT,
) -> ExpectedAuthorityTier:
    return ExpectedAuthorityTier(
        source_status=status,
        authority_rank=authority_rank,
        evidence_ids=list(evidence_ids),
    )


def _evidence(
    *tiers: ExpectedAuthorityTier,
    reason: str,
) -> EvidenceAssignment:
    return EvidenceAssignment(authority_tiers=list(tiers), evidence_reason=reason)


EVIDENCE_ASSIGNMENTS: dict[str, EvidenceAssignment] = {
    "EVAL-001": _evidence(
        _tier(5, "PROD-AVAIL-001::chunk-001", "PROD-DEPLOY-001::chunk-001"),
        _tier(4, "PROD-CAP-001::chunk-001"),
        reason="Availability and deployment sources establish tier support; the catalog adds capability detail.",
    ),
    "EVAL-002": _evidence(
        _tier(
            5,
            "PROD-AVAIL-001::chunk-001",
            "PROD-DEPLOY-001::chunk-001",
            "SEC-CTRL-001::chunk-001",
        ),
        _tier(4, "PROD-CAP-001::chunk-001"),
        reason="The response needs key availability, deployment boundaries, and the matching security control.",
    ),
    "EVAL-003": _evidence(
        _tier(5, "SEC-CTRL-001::chunk-001"),
        reason="The current controls matrix explicitly states the negative FIPS status.",
    ),
    "EVAL-004": _evidence(
        _tier(4, "IMPL-GUIDE-001::chunk-001"),
        reason="The implementation guide contains the phases, prerequisites, and customer responsibilities.",
    ),
    "EVAL-005": _evidence(
        _tier(5, "PROD-SLA-001::chunk-001", "PROD-SLA-001::chunk-002"),
        reason="Both SLA chunks are needed for the standard target, exclusions, and non-acceptance boundary.",
    ),
    "EVAL-006": _evidence(
        _tier(5, "PROD-AVAIL-001::chunk-001"),
        _tier(4, "PROD-CAP-001::chunk-002"),
        reason="The availability matrix controls roadmap status; the catalog reinforces the no-date boundary.",
    ),
    "EVAL-007": _evidence(
        _tier(5, "PROD-AVAIL-001::chunk-001", "PROD-DEPLOY-001::chunk-001"),
        reason="The two current Product sources describe supported cloud models and explicit on-premises exclusion.",
    ),
    "EVAL-008": _evidence(
        _tier(5, "SEC-CTRL-001::chunk-001"),
        _tier(
            2,
            "SEC-CTRL-OLD-001::chunk-001",
            status=SourceStatus.ARCHIVED,
        ),
        reason="The current TLS statement must outrank—but not hide—the archived contradictory wording.",
    ),
    "EVAL-009": _evidence(
        _tier(5, "SEC-CTRL-001::chunk-001"),
        reason="The current controls matrix directly covers encryption in transit and at rest.",
    ),
    "EVAL-010": _evidence(
        _tier(5, "SEC-CTRL-001::chunk-001"),
        reason="The current controls matrix directly records SOC 2 Type II and ISO 27001 assurance.",
    ),
    "EVAL-011": _evidence(
        _tier(
            5,
            "PROD-DEPLOY-001::chunk-001",
            "PROD-DEPLOY-001::chunk-002",
            "SEC-DATA-001::chunk-001",
        ),
        reason="Product establishes the offering boundary while Security establishes EU content and backup residency.",
    ),
    "EVAL-012": _evidence(
        _tier(
            5,
            "PROD-DEPLOY-001::chunk-001",
            "PROD-DEPLOY-001::chunk-002",
            "SEC-DATA-001::chunk-001",
        ),
        reason="The plan and residency sources jointly establish the Standard Cloud limitation.",
    ),
    "EVAL-013": _evidence(
        _tier(5, "SEC-DATA-001::chunk-001"),
        reason="The handling standard explicitly refuses an absolute in-region operational-access guarantee.",
    ),
    "EVAL-014": _evidence(
        _tier(5, "SEC-RET-001::chunk-001", "SEC-RET-OPS-001::chunk-001"),
        reason="Both current, equal-rank retention values are required and neither outranks the other.",
    ),
    "EVAL-015": _evidence(
        _tier(5, "SEC-RET-001::chunk-001", "SEC-RET-OPS-001::chunk-001"),
        reason="Both retention sources are material to the unsupported 24-hour content-and-backup deletion demand.",
    ),
    "EVAL-016": _evidence(
        _tier(4, "IMPL-GUIDE-001::chunk-001", "IMPL-GUIDE-001::chunk-002"),
        reason="The two guide chunks cover duration, start conditions, schedule changes, and approval qualification.",
    ),
    "EVAL-017": _evidence(
        _tier(4, "IMPL-GUIDE-001::chunk-001"),
        reason="The first guide chunk lists customer roles, data, access, decisions, and test participation.",
    ),
    "EVAL-018": _evidence(
        _tier(5, "PROD-AVAIL-001::chunk-001"),
        _tier(4, "PROD-CAP-001::chunk-002"),
        reason="The availability matrix governs GA and tier scope; the catalog corroborates Salesforce availability.",
    ),
    "EVAL-019": _evidence(
        _tier(4, "IMPL-GUIDE-001::chunk-001", "IMPL-GUIDE-001::chunk-002"),
        reason="Both guide chunks explain scope changes, timeline effects, and separate plan approval.",
    ),
    "EVAL-020": _evidence(
        _tier(
            5,
            "PROD-AVAIL-001::chunk-001",
            "PROD-DEPLOY-001::chunk-001",
            "SEC-CTRL-001::chunk-001",
        ),
        _tier(4, "PROD-CAP-001::chunk-001"),
        reason="The comparison needs tier availability, deployment models, identity detail, and key-control scope.",
    ),
    "EVAL-021": _evidence(
        reason="No approved chunk directly establishes FedRAMP High authorization; adjacent controls are not gold evidence.",
    ),
    "EVAL-022": _evidence(
        _tier(5, "PROD-AVAIL-001::chunk-001", "PROD-DEPLOY-001::chunk-001"),
        reason="Both Product sources explicitly exclude the requested customer-operated deployment package.",
    ),
    "EVAL-023": _evidence(
        reason="The route stops for organizational authority before retrieval, so it has no answer-evidence gold IDs.",
    ),
    "EVAL-024": _evidence(
        reason="The prompt-injection route stops before retrieval, so it has no answer-evidence gold IDs.",
    ),
}

EXPECTED_EMPTY_EVIDENCE_CASES = ("EVAL-021", "EVAL-023", "EVAL-024")


def apply_evidence_labels(
    dataset: EvaluationDataset | None = None,
    assignments: dict[str, EvidenceAssignment] | None = None,
) -> EvaluationDataset:
    """Populate only gold evidence IDs and expected source-authority tiers."""

    source = dataset or load_evaluation_dataset()
    selected = assignments or EVIDENCE_ASSIGNMENTS
    if tuple(selected) != EXPECTED_CASE_IDS:
        raise ValueError("evidence assignments must contain EVAL-001 through EVAL-024 in order")

    cases: list[EvaluationCase] = []
    for case in source.cases:
        assignment = selected[case.case_id]
        payload = case.model_dump(mode="json")
        labels = payload["gold_labels"]
        labels["gold_evidence_ids"] = assignment.evidence_ids
        labels["expected_authority_order"] = [
            tier.model_dump(mode="json") for tier in assignment.authority_tiers
        ]
        cases.append(EvaluationCase.model_validate(payload))

    payload = source.model_dump(mode="json")
    payload["cases"] = [case.model_dump(mode="json") for case in cases]
    labeled = EvaluationDataset.model_validate(payload)
    validate_evidence_labels(labeled, selected)
    return labeled


def validate_evidence_labels(
    dataset: EvaluationDataset,
    assignments: dict[str, EvidenceAssignment] | None = None,
    chunks: list[CorpusChunk] | None = None,
) -> None:
    """Reject unknown, cross-domain, misordered, or metadata-inconsistent gold evidence."""

    selected = assignments or EVIDENCE_ASSIGNMENTS
    if tuple(selected) != EXPECTED_CASE_IDS:
        raise ValueError("evidence assignments must contain EVAL-001 through EVAL-024 in order")
    corpus = chunks or load_corpus_chunks(KB_DIRECTORY)
    by_id = {chunk.chunk_id: chunk for chunk in corpus}
    if len(by_id) != len(corpus):
        raise ValueError("corpus chunk IDs must be unique")

    for case in dataset.cases:
        assignment = selected[case.case_id]
        labels = case.gold_labels
        if labels.gold_evidence_ids != assignment.evidence_ids:
            raise ValueError(f"gold-evidence drift for {case.case_id}")
        if labels.expected_authority_order != assignment.authority_tiers:
            raise ValueError(f"authority-order drift for {case.case_id}")

        for tier in assignment.authority_tiers:
            for evidence_id in tier.evidence_ids:
                if evidence_id not in by_id:
                    raise ValueError(f"unknown gold evidence ID {evidence_id}")
                chunk = by_id[evidence_id]
                if chunk.source_status is not tier.source_status:
                    raise ValueError(f"source-status mismatch for {evidence_id}")
                if chunk.authority_rank != tier.authority_rank:
                    raise ValueError(f"authority-rank mismatch for {evidence_id}")
                if chunk.domain not in labels.expected_domains:
                    raise ValueError(f"cross-domain gold evidence for {case.case_id}")

        evidence_domains = {
            by_id[evidence_id].domain for evidence_id in assignment.evidence_ids
        }
        if assignment.evidence_ids and evidence_domains != set(labels.expected_domains):
            raise ValueError(f"gold evidence does not cover every expected domain for {case.case_id}")

    observed_empty = tuple(
        case.case_id for case in dataset.cases if not case.gold_labels.gold_evidence_ids
    )
    if observed_empty != EXPECTED_EMPTY_EVIDENCE_CASES:
        raise ValueError("empty-evidence case set drift")


def render_evidence_matrix(dataset: EvaluationDataset) -> str:
    """Render gold answer evidence and authority tiers for human review."""

    validate_evidence_labels(dataset)
    lines = [
        "# Evaluation Evidence Matrix — V1 Draft",
        "",
        (
            "This Step 4.4 artifact records answer evidence, not every related Top-5 result. "
            "Governance policy is evaluated separately from specialist retrieval and is not "
            "added merely to make an authority-sensitive answer look supported."
        ),
        "",
        "## Authority-order rule",
        "",
        "1. Relevant current evidence precedes relevant archived evidence.",
        "2. Within the same lifecycle status, higher authority rank precedes lower rank.",
        "3. Same-status, same-rank sources share one tier; their order does not resolve a conflict.",
        "4. Missing direct evidence is represented by an empty gold set, never by a document claiming absence.",
        "",
        "## Case matrix",
        "",
        "| Case | Requirement | Gold evidence IDs in authority order | Why |",
        "|---|---|---|---|",
    ]
    for case in dataset.cases:
        assignment = EVIDENCE_ASSIGNMENTS[case.case_id]
        tiers = "<br>".join(
            (
                f"{tier.source_status.value.title()} rank {tier.authority_rank}: "
                + ", ".join(f"`{item}`" for item in tier.evidence_ids)
            )
            for tier in assignment.authority_tiers
        )
        lines.append(
            f"| {case.case_id} | {case.requirement_id} | {tiers or '**None**'} | "
            f"{assignment.evidence_reason} |"
        )
    lines.extend(
        [
            "",
            "## Important edge cases",
            "",
            (
                "- **RFP-008:** the rank-5 current TLS source precedes the rank-2 archived "
                "source, but the archived mismatch remains visible."
            ),
            (
                "- **RFP-014:** the 30-day and 90-day sources share one current rank-5 "
                "tier; ordering cannot settle the contradiction."
            ),
            (
                "- **RFP-021:** adjacent security controls do not establish FedRAMP High, "
                "so the direct-answer gold set is empty."
            ),
            "- **RFP-023 and RFP-024:** both stop before specialist retrieval.",
            "",
            (
                "These draft labels become frozen only after the remaining gold fields and "
                "the Step 4.7 review checkpoint are complete."
            ),
            "",
        ]
    )
    return "\n".join(lines)
