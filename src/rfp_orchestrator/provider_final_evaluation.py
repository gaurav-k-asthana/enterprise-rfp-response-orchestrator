"""Final provider-backed Step 4.G8 analysis from immutable local archives."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_efficiency import EfficiencyReport
from rfp_orchestrator.evaluation_freeze import (
    KNOWN_IMPLEMENTATION_GAPS,
    file_sha256,
    text_sha256,
)
from rfp_orchestrator.evaluation_metrics import (
    EvaluationMetricReport,
    calculate_metrics,
    load_evaluation_run,
)
from rfp_orchestrator.evaluation_tables import EvaluationComparisonTableReport
from rfp_orchestrator.fair_comparison import ComparisonArchitecture
from rfp_orchestrator.safe_completion import (
    ObservedDisposition,
    SafeCompletionReport,
    calculate_safe_completion,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
OUTPUT_ROOT = PROJECT_ROOT / "outputs" / "evaluation"
PRIMARY_RAW_PATH = (
    OUTPUT_ROOT / "raw_runs" / "northstar-provider-primary-recovery-v2" / "raw" / "run.json"
)
REPEAT_2_RAW_PATH = (
    OUTPUT_ROOT / "raw_runs" / "northstar-provider-repeat-trial-2-recovery-v2" / "raw" / "run.json"
)
REPEAT_3_RAW_PATH = (
    OUTPUT_ROOT / "raw_runs" / "northstar-provider-repeat-trial-3-recovery-v2" / "raw" / "run.json"
)
METRICS_PATH = OUTPUT_ROOT / "metrics_provider_primary_step_4_g8.json"
SAFE_COMPLETION_PATH = OUTPUT_ROOT / "safe_completion_provider_primary_step_4_g8.json"
EFFICIENCY_PATH = OUTPUT_ROOT / "efficiency_provider_primary_step_4_g8.json"
TABLE_PATH = OUTPUT_ROOT / "comparison_tables_provider_primary_step_4_g8.json"
RECOVERY_DISPOSITION_PATH = OUTPUT_ROOT / "provider_execution_recovery_step_4_g7.json"
DEFAULT_FINAL_JSON_PATH = OUTPUT_ROOT / "provider_evaluation_final_step_4_g8.json"
DEFAULT_FINAL_MARKDOWN_PATH = OUTPUT_ROOT / "provider_evaluation_final_step_4_g8.md"
REPEAT_CASE_IDS = ("EVAL-001", "EVAL-002", "EVAL-015", "EVAL-021")


class ProviderFinalEvaluationError(ValueError):
    """Raised when final analysis cannot be traced to the frozen raw evidence."""


class HashedSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ArchitectureHeadline(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    architecture: ComparisonArchitecture
    execution_success_numerator: int = Field(ge=0)
    execution_success_denominator: Literal[24] = 24
    safe_completion_numerator: int = Field(ge=0)
    safe_completion_denominator: Literal[24] = 24
    routing_macro_f1: float = Field(ge=0, le=1)
    evidence_recall_at_5: float = Field(ge=0, le=1)
    unsupported_claim_rate: float = Field(ge=0, le=1)
    groundedness: float = Field(ge=0, le=1)
    hitl_f1: float = Field(ge=0, le=1)
    conflict_detection_f1: float = Field(ge=0, le=1)
    recovery_detection_f1: float = Field(ge=0, le=1)
    observed_success_record_count: int = Field(ge=0)
    observed_model_calls: int = Field(ge=0)
    observed_total_tokens: int = Field(ge=0)
    observed_mean_latency_ms: float = Field(ge=0)
    observed_estimated_cost_usd: float = Field(ge=0)
    preserved_primary_failures: int = Field(ge=0)


class RepeatTrialObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    trial_number: int = Field(ge=1, le=3)
    case_id: str
    architecture: ComparisonArchitecture
    execution_success: bool
    failure_type: str | None
    safe_completion: bool
    observed_disposition: ObservedDisposition
    routing_f1: float = Field(ge=0, le=1)


class RepeatArchitectureSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    architecture: ComparisonArchitecture
    requested_observations: Literal[12] = 12
    successful_observations: int = Field(ge=0, le=12)
    failed_observations: int = Field(ge=0, le=12)
    safe_completion_observations: int = Field(ge=0, le=12)
    cases_with_two_or_more_successful_trials: int = Field(ge=0, le=4)
    stable_cases_among_comparable_cases: int = Field(ge=0, le=4)

    @model_validator(mode="after")
    def repeat_counts_cover_scope(self) -> RepeatArchitectureSummary:
        if self.successful_observations + self.failed_observations != 12:
            raise ValueError("repeat success and failure counts must cover 12 observations")
        if self.stable_cases_among_comparable_cases > self.cases_with_two_or_more_successful_trials:
            raise ValueError("stable repeat cases cannot exceed comparable cases")
        return self


class ProviderFinalEvaluationReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    report_id: Literal["northstar-provider-final-evaluation-step-4-g8-v1"] = (
        "northstar-provider-final-evaluation-step-4-g8-v1"
    )
    status: Literal["DRAFT_FOR_HUMAN_REVIEW"] = "DRAFT_FOR_HUMAN_REVIEW"
    analysis_scope: Literal["FROZEN_V1_PRIMARY_WITH_BUDGET_CENSORED_REPEATS"] = (
        "FROZEN_V1_PRIMARY_WITH_BUDGET_CENSORED_REPEATS"
    )
    headline_finding: str = Field(min_length=1)
    bounded_preference: Literal["single_generalist_for_frozen_v1"] = (
        "single_generalist_for_frozen_v1"
    )
    universal_multi_agent_superiority_claimed: Literal[False] = False
    provider_comparison_completed: Literal[True] = True
    all_requested_executions_preserved: Literal[True] = True
    repeated_trials_attempted: Literal[True] = True
    repeated_trials_fully_observed: Literal[False] = False
    phase_4_exit_gate_ready_for_human_review: Literal[True] = True
    phase_4_exit_gate_passed: Literal[False] = False
    primary_case_count: Literal[24] = 24
    total_requested_architecture_executions: Literal[64] = 64
    total_successful_executions: Literal[45] = 45
    total_failed_executions: Literal[19] = 19
    cumulative_generation_calls: Literal[128] = 128
    cumulative_estimated_generation_cost_usd: Literal[0.814364] = 0.814364
    source_artifacts: list[HashedSource] = Field(min_length=8)
    primary_architecture_headlines: list[ArchitectureHeadline] = Field(min_length=2, max_length=2)
    repeat_architecture_summaries: list[RepeatArchitectureSummary] = Field(
        min_length=2, max_length=2
    )
    repeat_observations: list[RepeatTrialObservation] = Field(min_length=24, max_length=24)
    observed_findings: list[str] = Field(min_length=1)
    limitations: list[str] = Field(min_length=1)
    known_implementation_gaps: list[str] = Field(min_length=1)
    new_provider_calls_made_by_analysis: Literal[0] = 0

    @model_validator(mode="after")
    def report_stays_bounded(self) -> ProviderFinalEvaluationReport:
        if [item.architecture for item in self.primary_architecture_headlines] != list(
            ComparisonArchitecture
        ):
            raise ValueError("primary headlines must preserve architecture order")
        if [item.architecture for item in self.repeat_architecture_summaries] != list(
            ComparisonArchitecture
        ):
            raise ValueError("repeat summaries must preserve architecture order")
        if sum(item.execution_success for item in self.repeat_observations) != 8:
            raise ValueError("repeat observations must preserve all 16 budget failures")
        combined = " ".join([self.headline_finding, *self.observed_findings]).lower()
        if any(phrase in combined for phrase in ("universally better", "proved superior")):
            raise ValueError("final analysis contains an unbounded superiority claim")
        if self.known_implementation_gaps != list(KNOWN_IMPLEMENTATION_GAPS):
            raise ValueError("known implementation gaps drifted")
        return self


def _source(path: Path) -> HashedSource:
    return HashedSource(
        path=path.relative_to(PROJECT_ROOT).as_posix(),
        sha256=file_sha256(path),
    )


def _load_model(path: Path, model_type: type[BaseModel]) -> BaseModel:
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def _headline_rows(
    metrics: EvaluationMetricReport,
    safety: SafeCompletionReport,
    efficiency: EfficiencyReport,
) -> list[ArchitectureHeadline]:
    metric_lookup = {item.architecture: item for item in metrics.architecture_summaries}
    safety_lookup = {item.architecture: item for item in safety.architecture_summaries}
    efficiency_lookup = {item.architecture: item for item in efficiency.architecture_summaries}
    rows = []
    for architecture in ComparisonArchitecture:
        metric = metric_lookup[architecture]
        safe = safety_lookup[architecture]
        efficient = efficiency_lookup[architecture]
        rows.append(
            ArchitectureHeadline(
                architecture=architecture,
                execution_success_numerator=metric.execution_success_rate.numerator,
                safe_completion_numerator=safe.safe_completion_rate.numerator,
                routing_macro_f1=metric.routing_macro_f1.value,
                evidence_recall_at_5=metric.retrieval_recall_at_5.value,
                unsupported_claim_rate=metric.unsupported_claim_rate.value,
                groundedness=metric.groundedness.value,
                hitl_f1=metric.hitl.f1,
                conflict_detection_f1=metric.conflict_detection.f1,
                recovery_detection_f1=metric.recovery_detection.f1,
                observed_success_record_count=efficient.usage_observation_count,
                observed_model_calls=efficient.model_calls_total,
                observed_total_tokens=efficient.total_tokens,
                observed_mean_latency_ms=efficient.latency_ms.mean,
                observed_estimated_cost_usd=efficient.estimated_cost_usd_total,
                preserved_primary_failures=efficient.unobserved_failure_count,
            )
        )
    return rows


def _repeat_details() -> tuple[list[RepeatTrialObservation], list[RepeatArchitectureSummary]]:
    artifacts = {
        1: load_evaluation_run(PRIMARY_RAW_PATH),
        2: load_evaluation_run(REPEAT_2_RAW_PATH),
        3: load_evaluation_run(REPEAT_3_RAW_PATH),
    }
    observations: list[RepeatTrialObservation] = []
    for trial_number, artifact in artifacts.items():
        metrics = calculate_metrics(artifact)
        safety = calculate_safe_completion(artifact)
        metric_lookup = {(item.case_id, item.architecture): item for item in metrics.case_details}
        safety_lookup = {(item.case_id, item.architecture): item for item in safety.case_outcomes}
        for case_id in REPEAT_CASE_IDS:
            for architecture in ComparisonArchitecture:
                metric = metric_lookup[(case_id, architecture)]
                safe = safety_lookup[(case_id, architecture)]
                observations.append(
                    RepeatTrialObservation(
                        trial_number=trial_number,
                        case_id=case_id,
                        architecture=architecture,
                        execution_success=not metric.execution_failed,
                        failure_type=metric.failure_type,
                        safe_completion=safe.safe_completion,
                        observed_disposition=safe.observed_disposition,
                        routing_f1=metric.routing_f1,
                    )
                )

    summaries = []
    for architecture in ComparisonArchitecture:
        selected = [item for item in observations if item.architecture is architecture]
        by_case: dict[str, list[RepeatTrialObservation]] = defaultdict(list)
        for item in selected:
            by_case[item.case_id].append(item)
        comparable = {
            case_id: [item for item in items if item.execution_success]
            for case_id, items in by_case.items()
            if sum(item.execution_success for item in items) >= 2
        }
        stable = sum(
            len(
                {
                    (item.safe_completion, item.observed_disposition, item.routing_f1)
                    for item in items
                }
            )
            == 1
            for items in comparable.values()
        )
        successful = sum(item.execution_success for item in selected)
        summaries.append(
            RepeatArchitectureSummary(
                architecture=architecture,
                successful_observations=successful,
                failed_observations=12 - successful,
                safe_completion_observations=sum(item.safe_completion for item in selected),
                cases_with_two_or_more_successful_trials=len(comparable),
                stable_cases_among_comparable_cases=stable,
            )
        )
    return observations, summaries


def build_provider_final_evaluation() -> ProviderFinalEvaluationReport:
    metrics = _load_model(METRICS_PATH, EvaluationMetricReport)
    safety = _load_model(SAFE_COMPLETION_PATH, SafeCompletionReport)
    efficiency = _load_model(EFFICIENCY_PATH, EfficiencyReport)
    table = _load_model(TABLE_PATH, EvaluationComparisonTableReport)
    if any(
        item.source_run_sha256 != table.source_run_sha256 for item in (metrics, safety, efficiency)
    ):
        raise ProviderFinalEvaluationError("primary derived artifacts disagree on raw provenance")
    if table.source_run_sha256 != file_sha256(PRIMARY_RAW_PATH):
        raise ProviderFinalEvaluationError("primary table does not match the frozen raw run")
    disposition = json.loads(RECOVERY_DISPOSITION_PATH.read_text(encoding="utf-8"))
    if disposition.get("result_disposition") != "VALID_BUDGET_BOUNDED_PROVIDER_DATASET":
        raise ProviderFinalEvaluationError("provider recovery disposition is not valid")
    observations, repeat_summaries = _repeat_details()
    return ProviderFinalEvaluationReport(
        headline_finding=(
            "For this frozen synthetic V1 evaluation under one shared call ceiling, the single "
            "generalist is the bounded preference: it achieved 20/24 Safe Completion and 24/24 "
            "execution success versus 10/24 and 20/24 for orchestrated peers. This does not establish "
            "universal architecture superiority."
        ),
        source_artifacts=[
            _source(path)
            for path in (
                PRIMARY_RAW_PATH,
                REPEAT_2_RAW_PATH,
                REPEAT_3_RAW_PATH,
                METRICS_PATH,
                SAFE_COMPLETION_PATH,
                EFFICIENCY_PATH,
                TABLE_PATH,
                RECOVERY_DISPOSITION_PATH,
            )
        ],
        primary_architecture_headlines=_headline_rows(metrics, safety, efficiency),
        repeat_architecture_summaries=repeat_summaries,
        repeat_observations=observations,
        observed_findings=[
            "The single generalist led primary Safe Completion by 10 cases and completed all 24 primary executions.",
            "The single generalist had higher routing macro F1, Evidence Recall@5, and groundedness, and a lower unsupported-claim rate.",
            "Both architectures had 100% citation validity on successful records where citations were applicable.",
            "Orchestrated peers had slightly higher HITL F1 and demonstrated bounded recovery, but recovery precision was low and conflict-detection F1 was zero for both architectures.",
            "The orchestrated arm had higher mean and p95 latency and higher observed cost per successful record.",
            "All 19 execution failures were preserved budget-limit outcomes; the fixed integration defects did not recur.",
        ],
        limitations=[
            "The corpus and RFP are synthetic and small; results do not establish production performance or external validity.",
            "Only one model/provider configuration and one 24-case primary trial were evaluated.",
            "The repeat study is heavily budget-censored: only 8 of 24 planned repeat-set observations succeeded, so variability conclusions are not reliable.",
            "Usage for failed executions is intentionally unobserved in normalized records, so arm-level cost totals exclude work consumed by failed executions.",
            "The shared 128-call ceiling disproportionately affected the higher-call orchestrated path; this is an operational finding but also limits quality comparison coverage.",
            "Known implementation gaps remain and materially affect Safe Completion and conflict/recovery metrics.",
        ],
        known_implementation_gaps=list(KNOWN_IMPLEMENTATION_GAPS),
    )


def serialize_provider_final_evaluation(
    report: ProviderFinalEvaluationReport,
) -> tuple[str, str]:
    content = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def render_provider_final_evaluation(report: ProviderFinalEvaluationReport) -> str:
    by_arch = {item.architecture: item for item in report.primary_architecture_headlines}
    repeat_by_arch = {item.architecture: item for item in report.repeat_architecture_summaries}
    baseline = by_arch[ComparisonArchitecture.SINGLE_GENERALIST]
    orchestrated = by_arch[ComparisonArchitecture.ORCHESTRATED_PEERS]
    lines = [
        "# Provider Architecture Evaluation — Step 4.G8",
        "",
        "**Status:** DRAFT FOR HUMAN REVIEW",
        "**Scope:** Frozen synthetic V1 primary comparison with budget-censored repeats",
        "**Bounded preference:** Single generalist for this V1 evaluation",
        "**Universal multi-agent superiority claimed:** no",
        "**Phase 4 exit gate:** awaiting human review",
        "",
        "> All 19 failures remain in the applicable denominators. Repeat variability is not conclusive because the shared call ceiling censored 16 of 24 repeat-set observations.",
        "",
        "## Executive finding",
        "",
        report.headline_finding,
        "",
        "## Primary 24-case comparison",
        "",
        "| Metric | Single generalist | Orchestrated peers |",
        "|---|---:|---:|",
        f"| Execution success | {baseline.execution_success_numerator}/24 | {orchestrated.execution_success_numerator}/24 |",
        f"| Safe Completion Rate | {baseline.safe_completion_numerator}/24 ({baseline.safe_completion_numerator / 24:.1%}) | {orchestrated.safe_completion_numerator}/24 ({orchestrated.safe_completion_numerator / 24:.1%}) |",
        f"| Routing macro F1 | {baseline.routing_macro_f1:.3f} | {orchestrated.routing_macro_f1:.3f} |",
        f"| Evidence Recall@5 | {baseline.evidence_recall_at_5:.3f} | {orchestrated.evidence_recall_at_5:.3f} |",
        f"| Unsupported-claim rate | {baseline.unsupported_claim_rate:.1%} | {orchestrated.unsupported_claim_rate:.1%} |",
        f"| Groundedness | {baseline.groundedness:.1%} | {orchestrated.groundedness:.1%} |",
        f"| HITL F1 | {baseline.hitl_f1:.3f} | {orchestrated.hitl_f1:.3f} |",
        f"| Conflict-detection F1 | {baseline.conflict_detection_f1:.3f} | {orchestrated.conflict_detection_f1:.3f} |",
        f"| Recovery-detection F1 | {baseline.recovery_detection_f1:.3f} | {orchestrated.recovery_detection_f1:.3f} |",
        f"| Observed mean latency | {baseline.observed_mean_latency_ms:.0f} ms | {orchestrated.observed_mean_latency_ms:.0f} ms |",
        f"| Observed estimated cost | ${baseline.observed_estimated_cost_usd:.6f} | ${orchestrated.observed_estimated_cost_usd:.6f} |",
        f"| Preserved primary failures | {baseline.preserved_primary_failures} | {orchestrated.preserved_primary_failures} |",
        "",
        "## Repeat-set coverage",
        "",
        "| Architecture | Successful observations | Failed observations | Safe completions | Comparable cases (2+ successes) | Stable comparable cases |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for architecture in ComparisonArchitecture:
        item = repeat_by_arch[architecture]
        lines.append(
            f"| {architecture.value} | {item.successful_observations}/12 | "
            f"{item.failed_observations}/12 | {item.safe_completion_observations}/12 | "
            f"{item.cases_with_two_or_more_successful_trials}/4 | "
            f"{item.stable_cases_among_comparable_cases}/4 |"
        )
    lines.extend(["", "## Observed findings", ""])
    lines.extend(f"- {item}" for item in report.observed_findings)
    lines.extend(["", "## Explicit limitations", ""])
    lines.extend(f"- {item}" for item in report.limitations)
    lines.extend(["", "## Known implementation gaps", ""])
    lines.extend(f"- {item}" for item in report.known_implementation_gaps)
    lines.extend(
        [
            "",
            "## Provenance",
            "",
            *(f"- `{item.path}` — `{item.sha256}`" for item in report.source_artifacts),
            "- New provider calls made by this analysis: 0",
            "",
            "## Review decision requested",
            "",
            "Approve only if the bounded preference, preserved-failure treatment, repeat-censoring warning, and limitations accurately represent the frozen evidence. Approval will close the Phase 4 exit gate; it will not turn this result into a production-readiness or universal multi-agent claim.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_exact(path: Path, content: str) -> str:
    digest = text_sha256(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise ProviderFinalEvaluationError(f"refusing to overwrite different output: {path.name}")
    path.write_text(content, encoding="utf-8")
    sidecar = path.with_name(f"{path.name}.sha256")
    sidecar_content = f"{digest}  {path.name}\n"
    if sidecar.exists() and sidecar.read_text(encoding="utf-8") != sidecar_content:
        raise ProviderFinalEvaluationError(
            f"refusing to overwrite different checksum: {sidecar.name}"
        )
    sidecar.write_text(sidecar_content, encoding="utf-8")
    return digest


def write_provider_final_evaluation(
    report: ProviderFinalEvaluationReport,
    *,
    json_path: Path = DEFAULT_FINAL_JSON_PATH,
    markdown_path: Path = DEFAULT_FINAL_MARKDOWN_PATH,
) -> tuple[str, str]:
    json_content, _ = serialize_provider_final_evaluation(report)
    markdown_content = render_provider_final_evaluation(report)
    return _write_exact(json_path, json_content), _write_exact(markdown_path, markdown_content)
