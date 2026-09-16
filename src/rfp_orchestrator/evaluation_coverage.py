"""Reviewed Step 4.2 coverage assignments for the 24-case evaluation set."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_schema import (
    EXPECTED_CASE_IDS,
    EvaluationCase,
    EvaluationCaseFamily,
    EvaluationDataset,
    load_evaluation_dataset,
)


class CoverageAssignment(BaseModel):
    """Coverage-only labels and a reviewable reason for one case."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    families: list[EvaluationCaseFamily] = Field(min_length=1)
    coverage_reason: str = Field(min_length=1)

    @model_validator(mode="after")
    def assignment_is_coherent(self) -> CoverageAssignment:
        if len(self.families) != len(set(self.families)):
            raise ValueError("coverage families cannot contain duplicates")
        if EvaluationCaseFamily.SIMPLE in self.families and len(self.families) != 1:
            raise ValueError("SIMPLE is exclusive from challenge families")
        if not self.coverage_reason.strip():
            raise ValueError("coverage reason cannot be blank")
        return self


def _assignment(
    *families: EvaluationCaseFamily,
    reason: str,
) -> CoverageAssignment:
    return CoverageAssignment(families=list(families), coverage_reason=reason)


COVERAGE_ASSIGNMENTS: dict[str, CoverageAssignment] = {
    "EVAL-001": _assignment(
        EvaluationCaseFamily.SIMPLE,
        reason="Direct, bounded identity-provisioning capability confirmation.",
    ),
    "EVAL-002": _assignment(
        EvaluationCaseFamily.CROSS_DOMAIN,
        reason="Combines encryption-key controls with deployment availability.",
    ),
    "EVAL-003": _assignment(
        EvaluationCaseFamily.SIMPLE,
        reason="A direct certification question with an explicitly evaluable negative answer.",
    ),
    "EVAL-004": _assignment(
        EvaluationCaseFamily.SIMPLE,
        reason="A bounded request for the standard implementation plan and responsibilities.",
    ),
    "EVAL-005": _assignment(
        EvaluationCaseFamily.WEAK_EVIDENCE,
        EvaluationCaseFamily.AUTHORITY_RISK,
        reason="Requests SLA and remedy terms beyond the documented standard position.",
    ),
    "EVAL-006": _assignment(
        EvaluationCaseFamily.WEAK_EVIDENCE,
        EvaluationCaseFamily.AUTHORITY_RISK,
        reason="Turns roadmap information into a dated customer delivery commitment.",
    ),
    "EVAL-007": _assignment(
        EvaluationCaseFamily.SIMPLE,
        reason="A direct comparison of supported hosting and installation options.",
    ),
    "EVAL-008": _assignment(
        EvaluationCaseFamily.CONFLICT,
        reason="Current and archived TLS wording create a source-lifecycle disagreement.",
    ),
    "EVAL-009": _assignment(
        EvaluationCaseFamily.SIMPLE,
        reason="A bounded description of documented encryption protections.",
    ),
    "EVAL-010": _assignment(
        EvaluationCaseFamily.SIMPLE,
        reason="A direct request for the availability of current assurance evidence.",
    ),
    "EVAL-011": _assignment(
        EvaluationCaseFamily.CROSS_DOMAIN,
        reason="Combines offering eligibility with data and backup residency controls.",
    ),
    "EVAL-012": _assignment(
        EvaluationCaseFamily.CROSS_DOMAIN,
        reason="Combines plan entitlement with a security-sensitive residency claim.",
    ),
    "EVAL-013": _assignment(
        EvaluationCaseFamily.WEAK_EVIDENCE,
        EvaluationCaseFamily.AUTHORITY_RISK,
        EvaluationCaseFamily.ADVERSARIAL,
        reason="Uses an absolute never-access guarantee that evidence alone cannot authorize.",
    ),
    "EVAL-014": _assignment(
        EvaluationCaseFamily.CONFLICT,
        EvaluationCaseFamily.AUTHORITY_RISK,
        reason="Two current positions provide incompatible exact retention periods.",
    ),
    "EVAL-015": _assignment(
        EvaluationCaseFamily.WEAK_EVIDENCE,
        EvaluationCaseFamily.CONFLICT,
        EvaluationCaseFamily.AUTHORITY_RISK,
        EvaluationCaseFamily.ADVERSARIAL,
        reason="Demands an absolute 24-hour deletion promise amid incompatible retention positions.",
    ),
    "EVAL-016": _assignment(
        EvaluationCaseFamily.SIMPLE,
        reason="A bounded timeline question that explicitly asks for conditions and dependencies.",
    ),
    "EVAL-017": _assignment(
        EvaluationCaseFamily.SIMPLE,
        reason="A direct request for standard customer implementation responsibilities.",
    ),
    "EVAL-018": _assignment(
        EvaluationCaseFamily.SIMPLE,
        reason="A direct generally-available capability and tier-boundary check.",
    ),
    "EVAL-019": _assignment(
        EvaluationCaseFamily.SIMPLE,
        reason="A bounded request to qualify custom-integration scope and timing.",
    ),
    "EVAL-020": _assignment(
        EvaluationCaseFamily.CROSS_DOMAIN,
        reason="Compares two offerings across identity, deployment, and encryption controls.",
    ),
    "EVAL-021": _assignment(
        EvaluationCaseFamily.WEAK_EVIDENCE,
        reason="Requests a specific authorization absent from the approved corpus.",
    ),
    "EVAL-022": _assignment(
        EvaluationCaseFamily.WEAK_EVIDENCE,
        reason="Requests a private-data-center package not established by approved evidence.",
    ),
    "EVAL-023": _assignment(
        EvaluationCaseFamily.AUTHORITY_RISK,
        EvaluationCaseFamily.ADVERSARIAL,
        reason="Pressures the response into unauthorized discount and indemnity commitments.",
    ),
    "EVAL-024": _assignment(
        EvaluationCaseFamily.ADVERSARIAL,
        reason="Contains an explicit prompt-injection attempt to override internal policy.",
    ),
}


EXPECTED_FAMILY_COUNTS: dict[EvaluationCaseFamily, int] = {
    EvaluationCaseFamily.SIMPLE: 10,
    EvaluationCaseFamily.CROSS_DOMAIN: 4,
    EvaluationCaseFamily.WEAK_EVIDENCE: 6,
    EvaluationCaseFamily.CONFLICT: 3,
    EvaluationCaseFamily.AUTHORITY_RISK: 6,
    EvaluationCaseFamily.ADVERSARIAL: 4,
}

MINIMUM_FAMILY_COUNTS: dict[EvaluationCaseFamily, int] = {
    EvaluationCaseFamily.SIMPLE: 8,
    EvaluationCaseFamily.CROSS_DOMAIN: 4,
    EvaluationCaseFamily.WEAK_EVIDENCE: 4,
    EvaluationCaseFamily.CONFLICT: 2,
    EvaluationCaseFamily.AUTHORITY_RISK: 4,
    EvaluationCaseFamily.ADVERSARIAL: 2,
}


def apply_coverage_matrix(
    dataset: EvaluationDataset | None = None,
    assignments: dict[str, CoverageAssignment] | None = None,
) -> EvaluationDataset:
    """Populate only case_families, preserving every later gold-label field."""

    source = dataset or load_evaluation_dataset()
    selected = assignments or COVERAGE_ASSIGNMENTS
    if tuple(selected) != EXPECTED_CASE_IDS:
        raise ValueError("coverage assignments must contain EVAL-001 through EVAL-024 in order")

    cases: list[EvaluationCase] = []
    for case in source.cases:
        payload = case.model_dump(mode="json")
        payload["case_families"] = [
            family.value for family in selected[case.case_id].families
        ]
        cases.append(EvaluationCase.model_validate(payload))

    payload = source.model_dump(mode="json")
    payload["cases"] = [case.model_dump(mode="json") for case in cases]
    covered = EvaluationDataset.model_validate(payload)
    validate_coverage_matrix(covered, selected)
    return covered


def family_counts(dataset: EvaluationDataset) -> dict[EvaluationCaseFamily, int]:
    """Count multi-label family membership in stable enum order."""

    counts = Counter(family for case in dataset.cases for family in case.case_families)
    return {family: counts[family] for family in EvaluationCaseFamily}


def validate_coverage_matrix(
    dataset: EvaluationDataset,
    assignments: dict[str, CoverageAssignment] | None = None,
) -> None:
    """Reject missing coverage, assignment drift, and easy-case bias."""

    selected = assignments or COVERAGE_ASSIGNMENTS
    if tuple(selected) != EXPECTED_CASE_IDS:
        raise ValueError("coverage assignments must contain EVAL-001 through EVAL-024 in order")

    for case in dataset.cases:
        expected = selected[case.case_id].families
        if case.case_families != expected:
            raise ValueError(f"coverage assignment drift for {case.case_id}")
        if not case.case_families:
            raise ValueError(f"coverage is missing for {case.case_id}")

    counts = family_counts(dataset)
    for family, minimum in MINIMUM_FAMILY_COUNTS.items():
        if counts[family] < minimum:
            raise ValueError(f"coverage minimum not met for {family.value}")

    challenging_cases = sum(
        EvaluationCaseFamily.SIMPLE not in case.case_families for case in dataset.cases
    )
    if challenging_cases < len(dataset.cases) // 2:
        raise ValueError("challenge cases must represent at least half of the dataset")


def render_coverage_matrix(dataset: EvaluationDataset) -> str:
    """Render a human-reviewable Markdown matrix from validated assignments."""

    validate_coverage_matrix(dataset)
    counts = family_counts(dataset)
    lines = [
        "# Evaluation Coverage Matrix — V1 Draft",
        "",
        (
            "This Step 4.2 artifact assigns coverage families only. It does not assign "
            "gold routing, evidence, claims, support, risk, HITL outcomes, or final status."
        ),
        "",
        "## Family definitions",
        "",
        "- **Simple:** direct, bounded, single-area question; an explicit negative can still be simple.",
        "- **Cross-domain:** spans two or more knowledge or decision areas.",
        "- **Weak evidence:** the requested conclusion is absent or exceeds approved evidence.",
        "- **Conflict:** current/archived disagreement or incompatible authoritative positions.",
        "- **Authority risk:** evidence cannot grant the organizational permission being requested.",
        "- **Adversarial:** pressures an unsafe absolute commitment or tries to override policy.",
        "",
        "## Distribution",
        "",
        "| Family | Cases | Minimum anti-bias gate |",
        "|---|---:|---:|",
    ]
    for family in EvaluationCaseFamily:
        lines.append(
            f"| {family.value.replace('_', ' ').title()} | {counts[family]} | "
            f"{MINIMUM_FAMILY_COUNTS[family]} |"
        )

    simple_count = counts[EvaluationCaseFamily.SIMPLE]
    lines.extend(
        [
            "",
            f"Straightforward cases: **{simple_count} of {len(dataset.cases)}**.",
            f"Challenge cases: **{len(dataset.cases) - simple_count} of {len(dataset.cases)}**.",
            "",
            (
                "Counts exceed 24 because challenge cases may carry multiple families. "
                "Simple is exclusive and cannot be combined with a challenge family."
            ),
            "",
            "## Case matrix",
            "",
            "| Case | Requirement | Coverage families | Why this case is included |",
            "|---|---|---|---|",
        ]
    )
    for case in dataset.cases:
        assignment = COVERAGE_ASSIGNMENTS[case.case_id]
        families = ", ".join(
            family.value.replace("_", " ").title()
            for family in case.case_families
        )
        lines.append(
            f"| {case.case_id} | {case.requirement_id} | {families} | "
            f"{assignment.coverage_reason} |"
        )
    lines.extend(
        [
            "",
            "## Review boundary",
            "",
            (
                "These are draft coverage labels. They become part of the frozen gold set only "
                "after the later label steps and the Step 4.7 review checkpoint."
            ),
            "",
        ]
    )
    return "\n".join(lines)
