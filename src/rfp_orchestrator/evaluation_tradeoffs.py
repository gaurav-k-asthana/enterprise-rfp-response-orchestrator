"""Evidence-bounded Step 4.18 tradeoff and limitation analysis."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_freeze import KNOWN_IMPLEMENTATION_GAPS, file_sha256, text_sha256
from rfp_orchestrator.evaluation_tables import (
    DEFAULT_CANONICAL_RAW_RUN_PATH,
    DEFAULT_COMPARISON_TABLE_JSON_PATH,
    EvaluationComparisonTableReport,
    TableScope,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPEAT_TRIAL_APPROVAL_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "repeat_trial_approval_v1.json"
)
DEFAULT_TRADEOFF_JSON_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "tradeoff_analysis_smoke_step_4_18.json"
)
DEFAULT_TRADEOFF_MARKDOWN_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "tradeoff_analysis_smoke_step_4_18.md"
)
TRADEOFF_REPORT_VERSION = "1.0"


class TradeoffAnalysisError(ValueError):
    """Raised when an analysis exceeds or misstates its evidence boundary."""


class EvidenceStrength(str, Enum):
    OBSERVED_SMOKE = "OBSERVED_SMOKE"
    DESIGN_HYPOTHESIS = "DESIGN_HYPOTHESIS"
    EXPLICIT_LIMITATION = "EXPLICIT_LIMITATION"
    REQUIRED_NEXT_EVIDENCE = "REQUIRED_NEXT_EVIDENCE"


class AnalysisStatement(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    statement_id: str = Field(min_length=1)
    evidence_strength: EvidenceStrength
    statement: str = Field(min_length=1)
    evidence_paths: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def evidence_paths_are_clean(self) -> AnalysisStatement:
        if len(self.evidence_paths) != len(set(self.evidence_paths)):
            raise ValueError("analysis evidence paths cannot repeat")
        if any(not path.strip() for path in self.evidence_paths):
            raise ValueError("analysis evidence paths cannot be blank")
        return self


class ArchitectureDecisionRule(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rule_id: str = Field(min_length=1)
    situation: str = Field(min_length=1)
    provisional_preference: Literal[
        "single_generalist",
        "orchestrated_peer_specialists",
        "no_architecture_preference",
    ]
    condition: str = Field(min_length=1)
    evidence_status: Literal["UNTESTED_DECISION_RULE"] = "UNTESTED_DECISION_RULE"


class TradeoffAnalysisArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    report_version: Literal["1.0"] = TRADEOFF_REPORT_VERSION
    report_id: Literal["tradeoff-analysis:step-4-11-offline-dry-eval-001:v1"] = (
        "tradeoff-analysis:step-4-11-offline-dry-eval-001:v1"
    )
    status: Literal["DRAFT_FOR_HUMAN_REVIEW"] = "DRAFT_FOR_HUMAN_REVIEW"
    analysis_scope: Literal["SMOKE_ONLY"] = "SMOKE_ONLY"
    source_table_path: Literal[
        "outputs/evaluation/comparison_tables_smoke_step_4_17.json"
    ] = "outputs/evaluation/comparison_tables_smoke_step_4_17.json"
    source_table_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_raw_path: Literal[
        "outputs/evaluation/raw_runs/step-4-11-offline-dry-eval-001/raw/run.json"
    ] = "outputs/evaluation/raw_runs/step-4-11-offline-dry-eval-001/raw/run.json"
    source_raw_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    repeat_trial_approval_path: Literal[
        "data/evaluation/repeat_trial_approval_v1.json"
    ] = "data/evaluation/repeat_trial_approval_v1.json"
    repeat_trial_approval_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    approved_repeat_proposal_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    headline_finding: str = Field(min_length=1)
    comparative_winner: None = None
    universal_multi_agent_superiority_claimed: Literal[False] = False
    provider_comparison_completed: Literal[False] = False
    repeated_trials_completed: Literal[False] = False
    phase_4_exit_gate_passed: Literal[False] = False
    source_case_count: Literal[1] = 1
    source_record_count: Literal[2] = 2
    source_failure_count: Literal[0] = 0
    observations: list[AnalysisStatement] = Field(min_length=1)
    architecture_hypotheses: list[AnalysisStatement] = Field(min_length=1)
    limitations: list[AnalysisStatement] = Field(min_length=1)
    decision_rules: list[ArchitectureDecisionRule] = Field(min_length=1)
    required_next_evidence: list[AnalysisStatement] = Field(min_length=1)
    known_implementation_gaps: list[str] = Field(min_length=1)
    new_architecture_or_provider_calls_made: Literal[0] = 0

    @model_validator(mode="after")
    def analysis_does_not_overclaim(self) -> TradeoffAnalysisArtifact:
        if "insufficient comparative evidence" not in self.headline_finding.lower():
            raise ValueError("headline must state the insufficient-evidence finding")
        expected_strengths = {
            "observations": EvidenceStrength.OBSERVED_SMOKE,
            "architecture_hypotheses": EvidenceStrength.DESIGN_HYPOTHESIS,
            "limitations": EvidenceStrength.EXPLICIT_LIMITATION,
            "required_next_evidence": EvidenceStrength.REQUIRED_NEXT_EVIDENCE,
        }
        for field, strength in expected_strengths.items():
            if any(item.evidence_strength is not strength for item in getattr(self, field)):
                raise ValueError(f"{field} contains a mismatched evidence strength")
        claims = " ".join(
            item.statement for item in self.observations + self.architecture_hypotheses
        ).lower()
        prohibited = ("is universally better", "proved superior", "outperforms the")
        if any(phrase in claims for phrase in prohibited):
            raise ValueError("analysis contains an unsupported superiority claim")
        if self.known_implementation_gaps != list(KNOWN_IMPLEMENTATION_GAPS):
            raise ValueError("known implementation gaps drifted from the frozen review")
        statement_ids = [
            item.statement_id
            for group in (
                self.observations,
                self.architecture_hypotheses,
                self.limitations,
                self.required_next_evidence,
            )
            for item in group
        ]
        if len(statement_ids) != len(set(statement_ids)):
            raise ValueError("analysis statement IDs cannot repeat")
        return self


TABLE_PATH = "outputs/evaluation/comparison_tables_smoke_step_4_17.json"
RAW_PATH = "outputs/evaluation/raw_runs/step-4-11-offline-dry-eval-001/raw/run.json"
APPROVAL_PATH = "data/evaluation/repeat_trial_approval_v1.json"
GOLD_REVIEW_PATH = "data/evaluation/gold_review_packet_v1.md"


def load_comparison_table(
    path: Path = DEFAULT_COMPARISON_TABLE_JSON_PATH,
) -> EvaluationComparisonTableReport:
    return EvaluationComparisonTableReport.model_validate_json(
        path.read_text(encoding="utf-8")
    )


def build_tradeoff_analysis() -> TradeoffAnalysisArtifact:
    table = load_comparison_table()
    if table.table_scope is not TableScope.SMOKE_ONLY:
        raise TradeoffAnalysisError("Step 4.18 smoke analysis requires a smoke-only table")
    if table.comparative_conclusions_allowed:
        raise TradeoffAnalysisError("source table unexpectedly permits comparison claims")
    if table.source_run_sha256 != file_sha256(DEFAULT_CANONICAL_RAW_RUN_PATH):
        raise TradeoffAnalysisError("source table does not match the canonical raw run")
    approval = json.loads(DEFAULT_REPEAT_TRIAL_APPROVAL_PATH.read_text(encoding="utf-8"))
    if approval.get("comparative_runs_completed") != 0 or approval.get("provider_calls_made") != 0:
        raise TradeoffAnalysisError("approval record unexpectedly claims completed provider work")

    return TradeoffAnalysisArtifact(
        source_table_sha256=file_sha256(DEFAULT_COMPARISON_TABLE_JSON_PATH),
        source_raw_sha256=table.source_run_sha256,
        repeat_trial_approval_sha256=file_sha256(DEFAULT_REPEAT_TRIAL_APPROVAL_PATH),
        approved_repeat_proposal_sha256=str(approval["proposal_sha256"]),
        headline_finding=(
            "There is insufficient comparative evidence to select an architecture winner. "
            "The current result validates the raw-to-metrics-to-table pipeline only."
        ),
        observations=[
            AnalysisStatement(
                statement_id="OBS-001",
                evidence_strength=EvidenceStrength.OBSERVED_SMOKE,
                statement=(
                    "Both architectures completed the single EVAL-001 offline fixture safely "
                    "with 1/1 execution success and 1/1 Safe Completion."
                ),
                evidence_paths=[TABLE_PATH, RAW_PATH],
            ),
            AnalysisStatement(
                statement_id="OBS-002",
                evidence_strength=EvidenceStrength.OBSERVED_SMOKE,
                statement=(
                    "Both fixture records produced routing F1 1.000, Evidence Recall@5 1.000, "
                    "groundedness 2/2, citation validity 1/1, and zero unsupported claims."
                ),
                evidence_paths=[TABLE_PATH],
            ),
            AnalysisStatement(
                statement_id="OBS-003",
                evidence_strength=EvidenceStrength.OBSERVED_SMOKE,
                statement=(
                    "HITL, conflict, recovery, and bounded-recovery metrics are not applicable "
                    "to EVAL-001 and therefore remain N/A rather than zero."
                ),
                evidence_paths=[TABLE_PATH],
            ),
            AnalysisStatement(
                statement_id="OBS-004",
                evidence_strength=EvidenceStrength.OBSERVED_SMOKE,
                statement=(
                    "Both offline fixtures report zero model calls, tokens, and estimated cost, "
                    "plus deterministic 1.000 ms timing; these are not provider-performance measurements."
                ),
                evidence_paths=[TABLE_PATH, RAW_PATH],
            ),
        ],
        architecture_hypotheses=[
            AnalysisStatement(
                statement_id="HYP-001",
                evidence_strength=EvidenceStrength.DESIGN_HYPOTHESIS,
                statement=(
                    "A single generalist may be preferable for simple, directly evidenced cases "
                    "if it matches safety and quality with fewer calls, lower latency, and lower cost."
                ),
                evidence_paths=[GOLD_REVIEW_PATH, APPROVAL_PATH],
            ),
            AnalysisStatement(
                statement_id="HYP-002",
                evidence_strength=EvidenceStrength.DESIGN_HYPOTHESIS,
                statement=(
                    "Orchestrated peers may justify additional overhead on cross-domain, conflict, "
                    "and recovery cases only if measured safety or evidence handling improves."
                ),
                evidence_paths=[GOLD_REVIEW_PATH, APPROVAL_PATH],
            ),
            AnalysisStatement(
                statement_id="HYP-003",
                evidence_strength=EvidenceStrength.DESIGN_HYPOTHESIS,
                statement=(
                    "Deterministic preflight, authority, consistency, and HITL gates may account for "
                    "safety gains independently of the number of reasoning agents."
                ),
                evidence_paths=[GOLD_REVIEW_PATH],
            ),
        ],
        limitations=[
            AnalysisStatement(
                statement_id="LIM-001",
                evidence_strength=EvidenceStrength.EXPLICIT_LIMITATION,
                statement="Only one of 24 frozen cases has a generated table row.",
                evidence_paths=[TABLE_PATH],
            ),
            AnalysisStatement(
                statement_id="LIM-002",
                evidence_strength=EvidenceStrength.EXPLICIT_LIMITATION,
                statement=(
                    "The source is a deterministic offline fixture, not a GPT-5.6 Terra provider run."
                ),
                evidence_paths=[TABLE_PATH, RAW_PATH],
            ),
            AnalysisStatement(
                statement_id="LIM-003",
                evidence_strength=EvidenceStrength.EXPLICIT_LIMITATION,
                statement=(
                    "No cross-domain, weak-evidence, conflict, authority-risk, adversarial, or recovery "
                    "outcome is present in the observed table."
                ),
                evidence_paths=[TABLE_PATH, GOLD_REVIEW_PATH],
            ),
            AnalysisStatement(
                statement_id="LIM-004",
                evidence_strength=EvidenceStrength.EXPLICIT_LIMITATION,
                statement=(
                    "Zero calls, tokens, and cost reflect the offline fixture and cannot estimate live overhead."
                ),
                evidence_paths=[TABLE_PATH],
            ),
            AnalysisStatement(
                statement_id="LIM-005",
                evidence_strength=EvidenceStrength.EXPLICIT_LIMITATION,
                statement=(
                    "The approved repeated trials and full paired provider comparison have not run."
                ),
                evidence_paths=[APPROVAL_PATH],
            ),
        ],
        decision_rules=[
            ArchitectureDecisionRule(
                rule_id="RULE-001",
                situation="Simple, single-domain, directly evidenced requirement",
                provisional_preference="single_generalist",
                condition=(
                    "Prefer only if provider results match orchestrated safety and quality while "
                    "using fewer calls, tokens, latency, or cost."
                ),
            ),
            ArchitectureDecisionRule(
                rule_id="RULE-002",
                situation="Cross-domain, conflicting, or recovery-dependent requirement",
                provisional_preference="orchestrated_peer_specialists",
                condition=(
                    "Prefer only if measured Safe Completion, conflict detection, recovery, or "
                    "grounding gains justify the observed overhead."
                ),
            ),
            ArchitectureDecisionRule(
                rule_id="RULE-003",
                situation="Pre-retrieval prompt injection or commercial/legal authority stop",
                provisional_preference="no_architecture_preference",
                condition=(
                    "Use the shared deterministic safety gate; do not attribute the stop to agent count."
                ),
            ),
        ],
        required_next_evidence=[
            AnalysisStatement(
                statement_id="NEXT-001",
                evidence_strength=EvidenceStrength.REQUIRED_NEXT_EVIDENCE,
                statement="Implement and review both provider-backed executors and the exact guarded command.",
                evidence_paths=[APPROVAL_PATH],
            ),
            AnalysisStatement(
                statement_id="NEXT-002",
                evidence_strength=EvidenceStrength.REQUIRED_NEXT_EVIDENCE,
                statement="Run all 24 frozen cases once through both architectures under the approved ceiling.",
                evidence_paths=[APPROVAL_PATH, GOLD_REVIEW_PATH],
            ),
            AnalysisStatement(
                statement_id="NEXT-003",
                evidence_strength=EvidenceStrength.REQUIRED_NEXT_EVIDENCE,
                statement="Run Trials 2 and 3 only for EVAL-001, EVAL-002, EVAL-015, and EVAL-021.",
                evidence_paths=[APPROVAL_PATH],
            ),
            AnalysisStatement(
                statement_id="NEXT-004",
                evidence_strength=EvidenceStrength.REQUIRED_NEXT_EVIDENCE,
                statement="Archive raw successes and failures, then regenerate metrics and tables.",
                evidence_paths=[RAW_PATH, TABLE_PATH],
            ),
            AnalysisStatement(
                statement_id="NEXT-005",
                evidence_strength=EvidenceStrength.REQUIRED_NEXT_EVIDENCE,
                statement=(
                    "Report per-case differences and repeat variability before making a bounded portfolio claim."
                ),
                evidence_paths=[APPROVAL_PATH, TABLE_PATH],
            ),
        ],
        known_implementation_gaps=list(KNOWN_IMPLEMENTATION_GAPS),
    )


def serialize_tradeoff_analysis(
    analysis: TradeoffAnalysisArtifact,
) -> tuple[str, str]:
    content = json.dumps(analysis.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def _render_statements(items: list[AnalysisStatement]) -> list[str]:
    lines = []
    for item in items:
        paths = ", ".join(f"`{path}`" for path in item.evidence_paths)
        lines.append(
            f"- **{item.statement_id} — {item.evidence_strength.value}:** "
            f"{item.statement} Evidence: {paths}."
        )
    return lines


def render_tradeoff_analysis_markdown(analysis: TradeoffAnalysisArtifact) -> str:
    lines = [
        "# Architecture Tradeoff Analysis — Smoke Evidence",
        "",
        "**Status:** DRAFT FOR HUMAN REVIEW",
        "**Scope:** SMOKE ONLY",
        "**Comparative winner:** none",
        "**Phase 4 exit gate:** not passed",
        "",
        "> This report does not claim that multi-agent orchestration is universally better. The full provider comparison and approved repeated trials have not run.",
        "",
        "## Executive finding",
        "",
        analysis.headline_finding,
        "",
        "## What the current artifact actually shows",
        "",
        *_render_statements(analysis.observations),
        "",
        "## Architecture hypotheses—not measured results",
        "",
        *_render_statements(analysis.architecture_hypotheses),
        "",
        "## Explicit limitations",
        "",
        *_render_statements(analysis.limitations),
        "",
        "## Conditional decision framework",
        "",
        "| Situation | Provisional preference | Required condition | Evidence status |",
        "|---|---|---|---|",
    ]
    for rule in analysis.decision_rules:
        lines.append(
            f"| {rule.situation} | {rule.provisional_preference} | "
            f"{rule.condition} | {rule.evidence_status} |"
        )
    lines.extend(
        [
            "",
            "## Known implementation gaps",
            "",
            *(f"- {gap}" for gap in analysis.known_implementation_gaps),
            "",
            "## Evidence required before a portfolio performance claim",
            "",
            *_render_statements(analysis.required_next_evidence),
            "",
            "## Provenance",
            "",
            f"- Source table SHA-256: `{analysis.source_table_sha256}`",
            f"- Source raw SHA-256: `{analysis.source_raw_sha256}`",
            f"- Repeat-trial approval SHA-256: `{analysis.repeat_trial_approval_sha256}`",
            f"- Approved proposal SHA-256: `{analysis.approved_repeat_proposal_sha256}`",
            "- New architecture or provider calls made: 0",
            "",
            "## Conclusion",
            "",
            "The defensible conclusion today is restraint: the architecture and evaluation controls are implemented and auditable, but comparative performance remains unmeasured. A later claim must be bounded to the frozen 24-case set, the approved repeat subset, observed failures, and measured quality-versus-efficiency tradeoffs.",
            "",
        ]
    )
    return "\n".join(lines)


def tradeoff_sidecar_path(path: Path) -> Path:
    return path.with_name(f"{path.name}.sha256")


def _write_exact(path: Path, content: str) -> str:
    digest = text_sha256(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise TradeoffAnalysisError(f"refusing to overwrite different analysis: {path.name}")
    path.write_text(content, encoding="utf-8")
    sidecar = tradeoff_sidecar_path(path)
    sidecar_content = f"{digest}  {path.name}\n"
    if sidecar.exists() and sidecar.read_text(encoding="utf-8") != sidecar_content:
        raise TradeoffAnalysisError(f"refusing to overwrite different checksum: {sidecar.name}")
    sidecar.write_text(sidecar_content, encoding="utf-8")
    return digest


def write_tradeoff_analysis(
    analysis: TradeoffAnalysisArtifact,
    *,
    json_path: Path = DEFAULT_TRADEOFF_JSON_PATH,
    markdown_path: Path = DEFAULT_TRADEOFF_MARKDOWN_PATH,
) -> tuple[str, str]:
    json_content, _ = serialize_tradeoff_analysis(analysis)
    markdown_content = render_tradeoff_analysis_markdown(analysis)
    return _write_exact(json_path, json_content), _write_exact(markdown_path, markdown_content)
