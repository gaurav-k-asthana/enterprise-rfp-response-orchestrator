"""Generated side-by-side evaluation tables derived only from a raw run."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_efficiency import (
    EfficiencyCaseDetail,
    EfficiencyReport,
    calculate_efficiency,
    serialize_efficiency_report,
)
from rfp_orchestrator.evaluation_freeze import text_sha256
from rfp_orchestrator.evaluation_metrics import (
    CaseMetricDetail,
    EvaluationMetricReport,
    calculate_metrics,
    serialize_metric_report,
)
from rfp_orchestrator.evaluation_runner import (
    EvaluationRunArtifact,
    EvaluationRunMode,
    EvaluationRunRecord,
    serialize_evaluation_run,
)
from rfp_orchestrator.fair_comparison import ComparisonArchitecture
from rfp_orchestrator.models import Domain, RequirementStatus, SupportStatus
from rfp_orchestrator.safe_completion import (
    ObservedDisposition,
    SafeCompletionCaseOutcome,
    SafeCompletionReport,
    calculate_safe_completion,
    serialize_safe_completion_report,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CANONICAL_RAW_RUN_PATH = (
    PROJECT_ROOT
    / "outputs"
    / "evaluation"
    / "raw_runs"
    / "step-4-11-offline-dry-eval-001"
    / "raw"
    / "run.json"
)
DEFAULT_COMPARISON_TABLE_JSON_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "comparison_tables_smoke_step_4_17.json"
)
DEFAULT_COMPARISON_TABLE_MARKDOWN_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "comparison_tables_smoke_step_4_17.md"
)
TABLE_REPORT_VERSION = "1.0"


class EvaluationTableError(ValueError):
    """Raised when a comparison table cannot be generated honestly."""


class TableScope(str, Enum):
    SMOKE_ONLY = "SMOKE_ONLY"
    FULL_COMPARISON = "FULL_COMPARISON"
    PARTIAL_COMPARISON = "PARTIAL_COMPARISON"


class PreferredDirection(str, Enum):
    HIGHER = "HIGHER"
    LOWER = "LOWER"
    CONTEXT_ONLY = "CONTEXT_ONLY"


class ExecutionTableStatus(str, Enum):
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


class SummaryMetricRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metric_key: str = Field(min_length=1)
    metric_label: str = Field(min_length=1)
    preferred_direction: PreferredDirection
    baseline_display: str = Field(min_length=1)
    orchestrated_display: str = Field(min_length=1)
    denominator_or_basis: str = Field(min_length=1)


class CaseArchitectureCell(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    architecture: ComparisonArchitecture
    execution_status: ExecutionTableStatus
    failure_type: str | None
    observed_domains: list[Domain]
    routing_f1: float = Field(ge=0, le=1)
    recall_at_5: float | None = Field(default=None, ge=0, le=1)
    support_status: SupportStatus | None
    claim_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    citation_valid: bool | None
    observed_hitl: bool
    observed_conflict: bool
    observed_recovery: bool
    retry_count: int = Field(ge=0, le=2)
    safe_completion: bool
    observed_disposition: ObservedDisposition
    final_status: RequirementStatus | None
    model_calls: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def failures_keep_unknown_observations(self) -> CaseArchitectureCell:
        observations = (
            self.model_calls,
            self.total_tokens,
            self.latency_ms,
            self.estimated_cost_usd,
        )
        if self.execution_status is ExecutionTableStatus.FAILURE:
            if self.failure_type is None:
                raise ValueError("failed table cell requires a failure type")
            if any(value is not None for value in observations):
                raise ValueError("failed table cell cannot fabricate usage observations")
        elif self.failure_type is not None or any(value is None for value in observations):
            raise ValueError("successful table cell requires complete observations")
        return self


class CaseComparisonRow(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    baseline: CaseArchitectureCell
    orchestrated: CaseArchitectureCell

    @model_validator(mode="after")
    def architectures_are_paired(self) -> CaseComparisonRow:
        if self.baseline.architecture is not ComparisonArchitecture.SINGLE_GENERALIST:
            raise ValueError("baseline case cell has the wrong architecture")
        if self.orchestrated.architecture is not ComparisonArchitecture.ORCHESTRATED_PEERS:
            raise ValueError("orchestrated case cell has the wrong architecture")
        return self


class EvaluationComparisonTableReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    report_version: Literal["1.0"] = TABLE_REPORT_VERSION
    report_id: str = Field(min_length=1)
    table_scope: TableScope
    source_run_id: str = Field(min_length=1)
    source_run_mode: EvaluationRunMode
    source_run_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    supporting_metrics_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    safe_completion_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    efficiency_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_is_canonical_raw: Literal[True] = True
    summary_tables_are_derivative: Literal[True] = True
    manual_values_entered: Literal[False] = False
    comparative_conclusions_allowed: Literal[False] = False
    case_count: int = Field(ge=1)
    record_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    architecture_order: list[ComparisonArchitecture] = Field(min_length=2, max_length=2)
    summary_rows: list[SummaryMetricRow] = Field(min_length=1)
    case_rows: list[CaseComparisonRow] = Field(min_length=1)
    warnings: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def tables_cover_the_raw_run(self) -> EvaluationComparisonTableReport:
        if self.architecture_order != list(ComparisonArchitecture):
            raise ValueError("table architecture order must match the frozen comparison")
        if len(self.case_rows) != self.case_count:
            raise ValueError("table requires one paired row per requested case")
        if self.record_count + self.failure_count != self.case_count * 2:
            raise ValueError("table counts must cover every architecture execution")
        row_ids = [row.case_id for row in self.case_rows]
        if len(row_ids) != len(set(row_ids)):
            raise ValueError("case table rows cannot repeat")
        metric_keys = [row.metric_key for row in self.summary_rows]
        if len(metric_keys) != len(set(metric_keys)):
            raise ValueError("summary metric rows cannot repeat")
        if self.table_scope is TableScope.SMOKE_ONLY and not any(
            "smoke" in warning.lower() for warning in self.warnings
        ):
            raise ValueError("smoke table requires a visible smoke-only warning")
        return self


def _rate_display(numerator: int, denominator: int, value: float | None) -> str:
    if value is None:
        return f"N/A ({numerator}/{denominator})"
    return f"{value * 100:.1f}% ({numerator}/{denominator})"


def _average_display(value: float | None, count: int) -> str:
    return "N/A (n=0)" if value is None else f"{value:.3f} (n={count})"


def _binary_f1_display(value: float | None, total: int) -> str:
    return "N/A (n=0)" if value is None else f"{value:.3f} (n={total})"


def _summary_rows(
    metrics: EvaluationMetricReport,
    safety: SafeCompletionReport,
    efficiency: EfficiencyReport,
) -> list[SummaryMetricRow]:
    metric_by_arch = {item.architecture: item for item in metrics.architecture_summaries}
    safety_by_arch = {item.architecture: item for item in safety.architecture_summaries}
    efficiency_by_arch = {
        item.architecture: item for item in efficiency.architecture_summaries
    }
    baseline = metric_by_arch[ComparisonArchitecture.SINGLE_GENERALIST]
    orchestrated = metric_by_arch[ComparisonArchitecture.ORCHESTRATED_PEERS]
    baseline_safety = safety_by_arch[ComparisonArchitecture.SINGLE_GENERALIST]
    orchestrated_safety = safety_by_arch[ComparisonArchitecture.ORCHESTRATED_PEERS]
    baseline_efficiency = efficiency_by_arch[ComparisonArchitecture.SINGLE_GENERALIST]
    orchestrated_efficiency = efficiency_by_arch[
        ComparisonArchitecture.ORCHESTRATED_PEERS
    ]

    def rate_row(
        key: str,
        label: str,
        baseline_rate: object,
        orchestrated_rate: object,
        direction: PreferredDirection,
        basis: str,
    ) -> SummaryMetricRow:
        baseline_value = baseline_rate
        orchestrated_value = orchestrated_rate
        return SummaryMetricRow(
            metric_key=key,
            metric_label=label,
            preferred_direction=direction,
            baseline_display=_rate_display(
                baseline_value.numerator,
                baseline_value.denominator,
                baseline_value.value,
            ),
            orchestrated_display=_rate_display(
                orchestrated_value.numerator,
                orchestrated_value.denominator,
                orchestrated_value.value,
            ),
            denominator_or_basis=basis,
        )

    binary_total = metrics.case_count
    rows = [
        rate_row(
            "execution_success_rate",
            "Execution success",
            baseline.execution_success_rate,
            orchestrated.execution_success_rate,
            PreferredDirection.HIGHER,
            "All requested cases; failures remain in the denominator.",
        ),
        SummaryMetricRow(
            metric_key="routing_macro_f1",
            metric_label="Routing macro F1",
            preferred_direction=PreferredDirection.HIGHER,
            baseline_display=_average_display(
                baseline.routing_macro_f1.value, baseline.routing_macro_f1.count
            ),
            orchestrated_display=_average_display(
                orchestrated.routing_macro_f1.value,
                orchestrated.routing_macro_f1.count,
            ),
            denominator_or_basis="Mean case-level routing F1 across requested cases.",
        ),
        SummaryMetricRow(
            metric_key="retrieval_recall_at_5",
            metric_label="Evidence Recall@5",
            preferred_direction=PreferredDirection.HIGHER,
            baseline_display=_average_display(
                baseline.retrieval_recall_at_5.value,
                baseline.retrieval_recall_at_5.count,
            ),
            orchestrated_display=_average_display(
                orchestrated.retrieval_recall_at_5.value,
                orchestrated.retrieval_recall_at_5.count,
            ),
            denominator_or_basis="Cases with nonempty frozen gold evidence.",
        ),
        rate_row(
            "unsupported_claim_rate",
            "Unsupported-claim rate",
            baseline.unsupported_claim_rate,
            orchestrated.unsupported_claim_rate,
            PreferredDirection.LOWER,
            "Unsupported emitted claims divided by all emitted claims.",
        ),
        rate_row(
            "groundedness",
            "Groundedness",
            baseline.groundedness,
            orchestrated.groundedness,
            PreferredDirection.HIGHER,
            "Grounded claims divided by all emitted claims.",
        ),
        rate_row(
            "citation_validity",
            "Citation validity",
            baseline.citation_validity,
            orchestrated.citation_validity,
            PreferredDirection.HIGHER,
            "Successful records where citations are applicable.",
        ),
        SummaryMetricRow(
            metric_key="hitl_f1",
            metric_label="HITL F1",
            preferred_direction=PreferredDirection.HIGHER,
            baseline_display=_binary_f1_display(baseline.hitl.f1, binary_total),
            orchestrated_display=_binary_f1_display(orchestrated.hitl.f1, binary_total),
            denominator_or_basis="Required versus observed human-review decision.",
        ),
        SummaryMetricRow(
            metric_key="conflict_detection_f1",
            metric_label="Conflict-detection F1",
            preferred_direction=PreferredDirection.HIGHER,
            baseline_display=_binary_f1_display(
                baseline.conflict_detection.f1, binary_total
            ),
            orchestrated_display=_binary_f1_display(
                orchestrated.conflict_detection.f1, binary_total
            ),
            denominator_or_basis="Expected versus observed conflict decision.",
        ),
        SummaryMetricRow(
            metric_key="recovery_detection_f1",
            metric_label="Recovery-detection F1",
            preferred_direction=PreferredDirection.HIGHER,
            baseline_display=_binary_f1_display(
                baseline.recovery_detection.f1, binary_total
            ),
            orchestrated_display=_binary_f1_display(
                orchestrated.recovery_detection.f1, binary_total
            ),
            denominator_or_basis="Expected versus observed recovery decision.",
        ),
        rate_row(
            "bounded_recovery_rate",
            "Bounded recovery",
            baseline.bounded_recovery_rate,
            orchestrated.bounded_recovery_rate,
            PreferredDirection.HIGHER,
            "Observed recovery cases only.",
        ),
        rate_row(
            "safe_completion_rate",
            "Safe Completion Rate",
            baseline_safety.safe_completion_rate,
            orchestrated_safety.safe_completion_rate,
            PreferredDirection.HIGHER,
            "Safely finalized plus correctly escalated, divided by every case.",
        ),
        SummaryMetricRow(
            metric_key="model_calls_total",
            metric_label="Model calls",
            preferred_direction=PreferredDirection.LOWER,
            baseline_display=str(baseline_efficiency.model_calls_total),
            orchestrated_display=str(orchestrated_efficiency.model_calls_total),
            denominator_or_basis="Observed provider calls in successful records.",
        ),
        SummaryMetricRow(
            metric_key="total_tokens",
            metric_label="Total tokens",
            preferred_direction=PreferredDirection.LOWER,
            baseline_display=str(baseline_efficiency.total_tokens),
            orchestrated_display=str(orchestrated_efficiency.total_tokens),
            denominator_or_basis="Observed input plus output tokens.",
        ),
        SummaryMetricRow(
            metric_key="mean_latency_ms",
            metric_label="Mean latency (ms)",
            preferred_direction=PreferredDirection.LOWER,
            baseline_display=(
                "N/A" if baseline_efficiency.latency_ms.mean is None else f"{baseline_efficiency.latency_ms.mean:.3f}"
            ),
            orchestrated_display=(
                "N/A" if orchestrated_efficiency.latency_ms.mean is None else f"{orchestrated_efficiency.latency_ms.mean:.3f}"
            ),
            denominator_or_basis="Successful executions with observed end-to-end latency.",
        ),
        SummaryMetricRow(
            metric_key="p95_latency_ms",
            metric_label="P95 latency (ms)",
            preferred_direction=PreferredDirection.LOWER,
            baseline_display=(
                "N/A"
                if baseline_efficiency.latency_ms.p95_nearest_rank is None
                else f"{baseline_efficiency.latency_ms.p95_nearest_rank:.3f}"
            ),
            orchestrated_display=(
                "N/A"
                if orchestrated_efficiency.latency_ms.p95_nearest_rank is None
                else f"{orchestrated_efficiency.latency_ms.p95_nearest_rank:.3f}"
            ),
            denominator_or_basis="Nearest-rank p95 across observed successful executions.",
        ),
        SummaryMetricRow(
            metric_key="estimated_cost_usd",
            metric_label="Estimated cost (USD)",
            preferred_direction=PreferredDirection.LOWER,
            baseline_display=f"${baseline_efficiency.estimated_cost_usd_total:.8f}",
            orchestrated_display=f"${orchestrated_efficiency.estimated_cost_usd_total:.8f}",
            denominator_or_basis="Frozen standard-rate estimate; not an invoice.",
        ),
        SummaryMetricRow(
            metric_key="preserved_failures",
            metric_label="Preserved failures",
            preferred_direction=PreferredDirection.LOWER,
            baseline_display=str(baseline_efficiency.unobserved_failure_count),
            orchestrated_display=str(orchestrated_efficiency.unobserved_failure_count),
            denominator_or_basis="Failed executions retained with unknown usage, never zero-filled.",
        ),
    ]
    return rows


def _case_cell(
    architecture: ComparisonArchitecture,
    metric: CaseMetricDetail,
    safety: SafeCompletionCaseOutcome,
    efficiency: EfficiencyCaseDetail,
    record: EvaluationRunRecord | None,
) -> CaseArchitectureCell:
    failed = metric.execution_failed
    if failed != efficiency.execution_failed:
        raise EvaluationTableError("metric and efficiency failure states disagree")
    return CaseArchitectureCell(
        architecture=architecture,
        execution_status=(
            ExecutionTableStatus.FAILURE if failed else ExecutionTableStatus.SUCCESS
        ),
        failure_type=metric.failure_type,
        observed_domains=metric.observed_domains,
        routing_f1=metric.routing_f1,
        recall_at_5=metric.recall_at_5,
        support_status=record.support_status if record else None,
        claim_count=metric.claim_count,
        unsupported_claim_count=metric.unsupported_claim_count,
        citation_valid=metric.citation_valid,
        observed_hitl=metric.observed_hitl,
        observed_conflict=metric.observed_conflict,
        observed_recovery=metric.observed_recovery,
        retry_count=metric.retry_count,
        safe_completion=safety.safe_completion,
        observed_disposition=safety.observed_disposition,
        final_status=record.final_status if record else None,
        model_calls=efficiency.model_calls,
        total_tokens=efficiency.total_tokens,
        latency_ms=efficiency.latency_ms,
        estimated_cost_usd=efficiency.calculated_estimated_cost_usd,
    )


def _validate_report_provenance(
    artifact: EvaluationRunArtifact,
    metrics: EvaluationMetricReport,
    safety: SafeCompletionReport,
    efficiency: EfficiencyReport,
) -> tuple[str, str, str, str]:
    _, raw_digest = serialize_evaluation_run(artifact)
    _, metrics_digest = serialize_metric_report(metrics)
    _, safety_digest = serialize_safe_completion_report(safety)
    _, efficiency_digest = serialize_efficiency_report(efficiency)
    reports = (metrics, safety, efficiency)
    if any(report.source_run_sha256 != raw_digest for report in reports):
        raise EvaluationTableError("derived report does not match the raw run")
    if len({report.source_run_id for report in reports}) != 1:
        raise EvaluationTableError("derived report run IDs disagree")
    return raw_digest, metrics_digest, safety_digest, efficiency_digest


def generate_comparison_tables(
    artifact: EvaluationRunArtifact,
) -> EvaluationComparisonTableReport:
    """Regenerate side-by-side tables without executing either architecture."""

    metrics = calculate_metrics(artifact)
    safety = calculate_safe_completion(artifact)
    efficiency = calculate_efficiency(artifact)
    raw_digest, metrics_digest, safety_digest, efficiency_digest = (
        _validate_report_provenance(artifact, metrics, safety, efficiency)
    )
    metric_lookup = {
        (item.case_id, item.architecture): item for item in metrics.case_details
    }
    safety_lookup = {
        (item.case_id, item.architecture): item for item in safety.case_outcomes
    }
    efficiency_lookup = {
        (item.case_id, item.architecture): item for item in efficiency.case_details
    }
    record_lookup = {
        (item.case_id, item.architecture): item for item in artifact.records
    }
    rows = []
    for case_id in artifact.case_ids:
        cells = {}
        for architecture in artifact.architectures:
            cells[architecture] = _case_cell(
                architecture,
                metric_lookup[(case_id, architecture)],
                safety_lookup[(case_id, architecture)],
                efficiency_lookup[(case_id, architecture)],
                record_lookup.get((case_id, architecture)),
            )
        rows.append(
            CaseComparisonRow(
                case_id=case_id,
                requirement_id=metric_lookup[
                    (case_id, ComparisonArchitecture.SINGLE_GENERALIST)
                ].requirement_id,
                baseline=cells[ComparisonArchitecture.SINGLE_GENERALIST],
                orchestrated=cells[ComparisonArchitecture.ORCHESTRATED_PEERS],
            )
        )

    if artifact.mode is EvaluationRunMode.OFFLINE_DRY_RUN:
        scope = TableScope.SMOKE_ONLY
        warnings = [
            "SMOKE ONLY — this one-case provider-free artifact cannot support architecture comparisons.",
            "Identical values verify table generation; they do not show architecture equivalence.",
        ]
    elif len(artifact.case_ids) == 24:
        scope = TableScope.FULL_COMPARISON
        warnings = [
            "Descriptive generated table only; Step 4.18 owns interpretation and limitations."
        ]
    else:
        scope = TableScope.PARTIAL_COMPARISON
        warnings = [
            "Partial comparison — do not generalize beyond the requested raw-run cases."
        ]
    return EvaluationComparisonTableReport(
        report_id=f"comparison-tables:{artifact.run_id}:v1",
        table_scope=scope,
        source_run_id=artifact.run_id,
        source_run_mode=artifact.mode,
        source_run_sha256=raw_digest,
        supporting_metrics_sha256=metrics_digest,
        safe_completion_sha256=safety_digest,
        efficiency_sha256=efficiency_digest,
        case_count=len(artifact.case_ids),
        record_count=len(artifact.records),
        failure_count=len(artifact.failures),
        architecture_order=list(ComparisonArchitecture),
        summary_rows=_summary_rows(metrics, safety, efficiency),
        case_rows=rows,
        warnings=warnings,
    )


def serialize_comparison_table_report(
    report: EvaluationComparisonTableReport,
) -> tuple[str, str]:
    content = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def _cell_summary(cell: CaseArchitectureCell) -> str:
    if cell.execution_status is ExecutionTableStatus.FAILURE:
        return f"FAILURE: {cell.failure_type}"
    domains = ", ".join(domain.value for domain in cell.observed_domains) or "none"
    safe = "safe" if cell.safe_completion else "unsafe/incomplete"
    return (
        f"{cell.observed_disposition.value}; route={domains}; "
        f"routing F1={cell.routing_f1:.3f}; {safe}; calls={cell.model_calls}; "
        f"tokens={cell.total_tokens}; latency={cell.latency_ms:.3f} ms"
    )


def render_comparison_table_markdown(
    report: EvaluationComparisonTableReport,
) -> str:
    lines = [
        "# Generated Evaluation Comparison Tables",
        "",
        f"**Scope:** {report.table_scope.value}",
        f"**Source run:** `{report.source_run_id}`",
        f"**Source raw SHA-256:** `{report.source_run_sha256}`",
        "**Manual values entered:** no",
        "**Comparative conclusions allowed:** no",
        "",
    ]
    lines.extend(f"> {warning}" for warning in report.warnings)
    lines.extend(
        [
            "",
            "## Architecture summary",
            "",
            "| Metric | Single generalist | Orchestrated peers | Preferred direction | Denominator or basis |",
            "|---|---:|---:|---|---|",
        ]
    )
    for row in report.summary_rows:
        lines.append(
            f"| {row.metric_label} | {row.baseline_display} | "
            f"{row.orchestrated_display} | {row.preferred_direction.value} | "
            f"{row.denominator_or_basis} |"
        )
    lines.extend(
        [
            "",
            "## Paired case results",
            "",
            "| Case | Requirement | Single generalist | Orchestrated peers |",
            "|---|---|---|---|",
        ]
    )
    for row in report.case_rows:
        lines.append(
            f"| {row.case_id} | {row.requirement_id} | "
            f"{_cell_summary(row.baseline)} | {_cell_summary(row.orchestrated)} |"
        )
    lines.extend(
        [
            "",
            "These tables are regenerable derivatives. The canonical raw run and its preserved failures remain the source of truth.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_exact(path: Path, content: str) -> str:
    digest = text_sha256(content)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise EvaluationTableError(f"refusing to overwrite different table: {path.name}")
    path.write_text(content, encoding="utf-8")
    sidecar = table_sidecar_path(path)
    sidecar_content = f"{digest}  {path.name}\n"
    if sidecar.exists() and sidecar.read_text(encoding="utf-8") != sidecar_content:
        raise EvaluationTableError(f"refusing to overwrite different checksum: {sidecar.name}")
    sidecar.write_text(sidecar_content, encoding="utf-8")
    return digest


def table_sidecar_path(path: Path) -> Path:
    """Keep JSON and Markdown checksum names distinct for one report stem."""

    return path.with_name(f"{path.name}.sha256")


def write_comparison_tables(
    report: EvaluationComparisonTableReport,
    *,
    json_path: Path = DEFAULT_COMPARISON_TABLE_JSON_PATH,
    markdown_path: Path = DEFAULT_COMPARISON_TABLE_MARKDOWN_PATH,
) -> tuple[str, str]:
    json_content, _ = serialize_comparison_table_report(report)
    markdown_content = render_comparison_table_markdown(report)
    return _write_exact(json_path, json_content), _write_exact(
        markdown_path, markdown_content
    )
