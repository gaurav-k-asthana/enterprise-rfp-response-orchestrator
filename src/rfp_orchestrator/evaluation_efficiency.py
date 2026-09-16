"""Step 4.14 calls, tokens, latency, and estimated-cost reporting."""

from __future__ import annotations

import json
import statistics
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from math import ceil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_freeze import text_sha256
from rfp_orchestrator.evaluation_metrics import (
    AverageMetric,
    EvaluationMetricsError,
    calculate_metrics,
    load_evaluation_run,
)
from rfp_orchestrator.evaluation_runner import (
    DEFAULT_DRY_RUN_OUTPUT_PATH,
    EvaluationModelUsage,
    EvaluationRunArtifact,
    EvaluationRunMode,
    EvaluationRunRecord,
    serialize_evaluation_run,
)
from rfp_orchestrator.fair_comparison import ComparisonArchitecture
from rfp_orchestrator.provider_config import OPENAI_GENERATION_MODEL

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PRICING_SNAPSHOT_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "openai_pricing_snapshot_step_4_14.json"
)
DEFAULT_PRICING_SNAPSHOT_DIGEST_PATH = DEFAULT_PRICING_SNAPSHOT_PATH.with_suffix(".sha256")
DEFAULT_EFFICIENCY_OUTPUT_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "efficiency_smoke_step_4_14.json"
)
DEFAULT_EFFICIENCY_DIGEST_PATH = DEFAULT_EFFICIENCY_OUTPUT_PATH.with_suffix(".sha256")
EFFICIENCY_REPORT_VERSION = "1.0"
PRICING_SNAPSHOT_ID = "openai-gpt-5.6-terra-standard-text-2026-09-12"
PRICING_CHECKED_AT = "2026-09-12"
PRICING_SOURCE_URL = "https://developers.openai.com/api/docs/models/gpt-5.6-terra"
USD_QUANTUM = Decimal("0.00000001")


class EfficiencyMetricsError(ValueError):
    """Raised when usage or pricing cannot be summarized honestly."""


class CostStatus(str, Enum):
    ZERO_USAGE = "ZERO_USAGE"
    STANDARD_RATE_ESTIMATE = "STANDARD_RATE_ESTIMATE"
    UNOBSERVED_EXECUTION_FAILURE = "UNOBSERVED_EXECUTION_FAILURE"


class OpenAIPricingSnapshot(BaseModel):
    """Dated official standard text-token prices used by the estimator."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    pricing_snapshot_id: Literal["openai-gpt-5.6-terra-standard-text-2026-09-12"] = (
        PRICING_SNAPSHOT_ID
    )
    checked_at: Literal["2026-09-12"] = PRICING_CHECKED_AT
    provider: Literal["OpenAI API"] = "OpenAI API"
    model: Literal["gpt-5.6-terra"] = OPENAI_GENERATION_MODEL
    currency: Literal["USD"] = "USD"
    billing_unit_tokens: Literal[1_000_000] = 1_000_000
    input_usd_per_unit: Literal[2.0] = 2.0
    cached_input_usd_per_unit: Literal[0.2] = 0.2
    output_usd_per_unit: Literal[12.0] = 12.0
    source_title: Literal["GPT-5.6 Terra Model | OpenAI API"] = "GPT-5.6 Terra Model | OpenAI API"
    source_url: Literal["https://developers.openai.com/api/docs/models/gpt-5.6-terra"] = (
        PRICING_SOURCE_URL
    )
    estimate_assumption: str = Field(min_length=1)
    cache_accounting: str = Field(min_length=1)
    long_context_accounting: str = Field(min_length=1)


class DistributionMetric(BaseModel):
    """An auditable distribution summary for successful observations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_count: int = Field(ge=0)
    missing_count: int = Field(ge=0)
    total: float = Field(ge=0)
    mean: float | None = Field(default=None, ge=0)
    median: float | None = Field(default=None, ge=0)
    p95_nearest_rank: float | None = Field(default=None, ge=0)
    minimum: float | None = Field(default=None, ge=0)
    maximum: float | None = Field(default=None, ge=0)


class EfficiencyCaseDetail(BaseModel):
    """One saved execution's observed efficiency facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    architecture: ComparisonArchitecture
    execution_failed: bool
    failure_type: str | None
    provider: str | None
    model: str | None
    model_calls: int | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)
    latency_ms: float | None = Field(default=None, ge=0)
    recorded_estimated_cost_usd: float | None = Field(default=None, ge=0)
    calculated_estimated_cost_usd: float | None = Field(default=None, ge=0)
    cost_status: CostStatus

    @model_validator(mode="after")
    def failure_has_no_fabricated_usage(self) -> EfficiencyCaseDetail:
        required_observations = (
            self.provider,
            self.model,
            self.model_calls,
            self.input_tokens,
            self.output_tokens,
            self.total_tokens,
            self.latency_ms,
            self.calculated_estimated_cost_usd,
        )
        if self.execution_failed:
            if any(value is not None for value in required_observations) or (
                self.recorded_estimated_cost_usd is not None
            ):
                raise ValueError("failed execution cannot fabricate unrecorded usage")
            if self.cost_status is not CostStatus.UNOBSERVED_EXECUTION_FAILURE:
                raise ValueError("failed execution requires unobserved cost status")
        elif any(value is None for value in required_observations):
            raise ValueError("successful execution requires complete usage observations")
        return self


class EfficiencyArchitectureSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    architecture: ComparisonArchitecture
    requested_case_count: int = Field(ge=1)
    usage_observation_count: int = Field(ge=0)
    unobserved_failure_count: int = Field(ge=0)
    usage_complete: bool
    model_calls_total: int = Field(ge=0)
    model_calls_per_observed_record: AverageMetric
    input_tokens_total: int = Field(ge=0)
    output_tokens_total: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    total_tokens_per_observed_record: AverageMetric
    latency_ms: DistributionMetric
    estimated_cost_usd_total: float = Field(ge=0)
    estimated_cost_usd_per_observed_record: AverageMetric

    @model_validator(mode="after")
    def summary_counts_are_consistent(self) -> EfficiencyArchitectureSummary:
        if (
            self.usage_observation_count + self.unobserved_failure_count
            != self.requested_case_count
        ):
            raise ValueError("usage observations and failures must cover every case")
        if self.usage_complete is not (self.unobserved_failure_count == 0):
            raise ValueError("usage completeness must reflect unobserved failures")
        if self.total_tokens != self.input_tokens_total + self.output_tokens_total:
            raise ValueError("summary token total must equal input plus output")
        return self


class EfficiencyReport(BaseModel):
    """Calls, tokens, latency, and estimated cost for one saved paired run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    report_version: Literal["1.0"] = EFFICIENCY_REPORT_VERSION
    report_id: str = Field(min_length=1)
    report_scope: Literal["SMOKE_ONLY", "RAW_METRICS_ONLY"]
    source_run_id: str = Field(min_length=1)
    source_run_mode: EvaluationRunMode
    source_run_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pricing_snapshot_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fair_comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    shared_safety_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    new_provider_calls_made_by_reporter: Literal[0] = 0
    comparative_conclusions_allowed: Literal[False] = False
    case_count: int = Field(ge=1)
    record_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    architecture_summaries: list[EfficiencyArchitectureSummary]
    case_details: list[EfficiencyCaseDetail]
    methodology: dict[str, str]

    @model_validator(mode="after")
    def report_covers_every_requested_execution(self) -> EfficiencyReport:
        if [item.architecture for item in self.architecture_summaries] != list(
            ComparisonArchitecture
        ):
            raise ValueError("efficiency summaries must preserve architecture order")
        expected_details = self.case_count * len(ComparisonArchitecture)
        if len(self.case_details) != expected_details:
            raise ValueError("every case and architecture requires efficiency detail")
        if self.record_count + self.failure_count != expected_details:
            raise ValueError("records and failures must cover every requested execution")
        return self


def build_pricing_snapshot() -> OpenAIPricingSnapshot:
    return OpenAIPricingSnapshot(
        estimate_assumption=(
            "Use standard uncached text-token rates for the frozen GPT-5.6 Terra "
            "model. The output is an estimate, not an invoice."
        ),
        cache_accounting=(
            "The normalized V1 usage record does not separate cached input tokens, "
            "so all observed input tokens use the standard input rate."
        ),
        long_context_accounting=(
            "The small synthetic evaluation is designed to remain below the published "
            "long-context threshold; per-request long-context token detail is not present "
            "in the normalized V1 usage record."
        ),
    )


def serialize_pricing_snapshot(
    snapshot: OpenAIPricingSnapshot,
) -> tuple[str, str]:
    content = json.dumps(snapshot.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def write_pricing_snapshot(
    snapshot: OpenAIPricingSnapshot,
    output_path: Path = DEFAULT_PRICING_SNAPSHOT_PATH,
) -> tuple[str, str]:
    content, digest = serialize_pricing_snapshot(snapshot)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != content:
        raise EfficiencyMetricsError("refusing to overwrite a different pricing snapshot")
    output_path.write_text(content, encoding="utf-8")
    digest_path = output_path.with_suffix(".sha256")
    digest_content = f"{digest}  {output_path.name}\n"
    if digest_path.exists() and digest_path.read_text(encoding="utf-8") != digest_content:
        raise EfficiencyMetricsError("refusing to overwrite a different pricing checksum")
    digest_path.write_text(digest_content, encoding="utf-8")
    return content, digest


def load_pricing_snapshot(
    path: Path = DEFAULT_PRICING_SNAPSHOT_PATH,
) -> OpenAIPricingSnapshot:
    snapshot = OpenAIPricingSnapshot.model_validate_json(path.read_text(encoding="utf-8"))
    if snapshot != build_pricing_snapshot():
        raise EfficiencyMetricsError("checked pricing snapshot drifted from V1 rates")
    return snapshot


def _estimated_cost(
    usage: EvaluationModelUsage,
    pricing: OpenAIPricingSnapshot,
) -> tuple[float, CostStatus]:
    if usage.provider_calls == 0:
        if usage.total_tokens != 0 or usage.estimated_cost_usd not in (None, 0):
            raise EfficiencyMetricsError("zero provider calls cannot report token or cost usage")
        return 0.0, CostStatus.ZERO_USAGE
    provider_matches = usage.provider == pricing.provider or (
        usage.provider.lower(),
        pricing.provider.lower(),
    ) == ("openai", "openai api")
    if not provider_matches or usage.model != pricing.model:
        raise EfficiencyMetricsError("provider usage does not match the frozen pricing model")
    if usage.total_tokens == 0:
        raise EfficiencyMetricsError("provider calls require observed token usage")
    unit = Decimal(pricing.billing_unit_tokens)
    cost = (
        Decimal(usage.input_tokens) * Decimal(str(pricing.input_usd_per_unit)) / unit
        + Decimal(usage.output_tokens) * Decimal(str(pricing.output_usd_per_unit)) / unit
    ).quantize(USD_QUANTUM, rounding=ROUND_HALF_UP)
    calculated = float(cost)
    if usage.estimated_cost_usd is not None and abs(usage.estimated_cost_usd - calculated) > float(
        USD_QUANTUM
    ):
        raise EfficiencyMetricsError("recorded estimated cost disagrees with frozen pricing")
    return calculated, CostStatus.STANDARD_RATE_ESTIMATE


def _case_detail(
    *,
    case_id: str,
    requirement_id: str,
    architecture: ComparisonArchitecture,
    record: EvaluationRunRecord | None,
    failure_type: str | None,
    pricing: OpenAIPricingSnapshot,
) -> EfficiencyCaseDetail:
    if record is None:
        return EfficiencyCaseDetail(
            case_id=case_id,
            requirement_id=requirement_id,
            architecture=architecture,
            execution_failed=True,
            failure_type=failure_type,
            provider=None,
            model=None,
            model_calls=None,
            input_tokens=None,
            output_tokens=None,
            total_tokens=None,
            latency_ms=None,
            recorded_estimated_cost_usd=None,
            calculated_estimated_cost_usd=None,
            cost_status=CostStatus.UNOBSERVED_EXECUTION_FAILURE,
        )
    calculated_cost, status = _estimated_cost(record.model_usage, pricing)
    usage = record.model_usage
    return EfficiencyCaseDetail(
        case_id=record.case_id,
        requirement_id=record.requirement_id,
        architecture=architecture,
        execution_failed=False,
        failure_type=None,
        provider=usage.provider,
        model=usage.model,
        model_calls=usage.provider_calls,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        total_tokens=usage.total_tokens,
        latency_ms=record.latency_ms,
        recorded_estimated_cost_usd=usage.estimated_cost_usd,
        calculated_estimated_cost_usd=calculated_cost,
        cost_status=status,
    )


def average_metric(values: Sequence[int | float]) -> AverageMetric:
    total = round(float(sum(values)), 12)
    return AverageMetric(
        total=total,
        count=len(values),
        value=None if not values else round(total / len(values), 12),
    )


def distribution_metric(values: Sequence[float], *, missing_count: int) -> DistributionMetric:
    ordered = sorted(values)
    if not ordered:
        return DistributionMetric(
            observation_count=0,
            missing_count=missing_count,
            total=0.0,
            mean=None,
            median=None,
            p95_nearest_rank=None,
            minimum=None,
            maximum=None,
        )
    total = round(sum(ordered), 12)
    p95_index = max(0, ceil(0.95 * len(ordered)) - 1)
    return DistributionMetric(
        observation_count=len(ordered),
        missing_count=missing_count,
        total=total,
        mean=round(total / len(ordered), 12),
        median=round(float(statistics.median(ordered)), 12),
        p95_nearest_rank=round(ordered[p95_index], 12),
        minimum=round(ordered[0], 12),
        maximum=round(ordered[-1], 12),
    )


def _architecture_summary(
    architecture: ComparisonArchitecture,
    details: list[EfficiencyCaseDetail],
) -> EfficiencyArchitectureSummary:
    observed = [item for item in details if not item.execution_failed]
    failures = len(details) - len(observed)
    calls = [item.model_calls for item in observed if item.model_calls is not None]
    input_tokens = [item.input_tokens for item in observed if item.input_tokens is not None]
    output_tokens = [item.output_tokens for item in observed if item.output_tokens is not None]
    total_tokens = [item.total_tokens for item in observed if item.total_tokens is not None]
    latencies = [item.latency_ms for item in observed if item.latency_ms is not None]
    costs = [
        item.calculated_estimated_cost_usd
        for item in observed
        if item.calculated_estimated_cost_usd is not None
    ]
    return EfficiencyArchitectureSummary(
        architecture=architecture,
        requested_case_count=len(details),
        usage_observation_count=len(observed),
        unobserved_failure_count=failures,
        usage_complete=failures == 0,
        model_calls_total=sum(calls),
        model_calls_per_observed_record=average_metric(calls),
        input_tokens_total=sum(input_tokens),
        output_tokens_total=sum(output_tokens),
        total_tokens=sum(total_tokens),
        total_tokens_per_observed_record=average_metric(total_tokens),
        latency_ms=distribution_metric(latencies, missing_count=failures),
        estimated_cost_usd_total=round(sum(costs), 8),
        estimated_cost_usd_per_observed_record=average_metric(costs),
    )


def calculate_efficiency(
    artifact: EvaluationRunArtifact,
    pricing: OpenAIPricingSnapshot | None = None,
) -> EfficiencyReport:
    """Summarize only usage already present in a validated raw run."""

    try:
        calculate_metrics(artifact)
    except EvaluationMetricsError as error:
        raise EfficiencyMetricsError(str(error)) from error
    pricing = pricing or load_pricing_snapshot()
    _, pricing_digest = serialize_pricing_snapshot(pricing)
    records = {(item.case_id, item.architecture): item for item in artifact.records}
    failures = {(item.case_id, item.architecture): item for item in artifact.failures}
    details: list[EfficiencyCaseDetail] = []
    for case_id in artifact.case_ids:
        for architecture in artifact.architectures:
            record = records.get((case_id, architecture))
            failure = failures.get((case_id, architecture))
            requirement_id = record.requirement_id if record else failure.requirement_id
            details.append(
                _case_detail(
                    case_id=case_id,
                    requirement_id=requirement_id,
                    architecture=architecture,
                    record=record,
                    failure_type=failure.error_type if failure else None,
                    pricing=pricing,
                )
            )
    _, source_digest = serialize_evaluation_run(artifact)
    report_scope = (
        "SMOKE_ONLY" if artifact.mode is EvaluationRunMode.OFFLINE_DRY_RUN else "RAW_METRICS_ONLY"
    )
    return EfficiencyReport(
        report_id=f"efficiency:{artifact.run_id}:v1",
        report_scope=report_scope,
        source_run_id=artifact.run_id,
        source_run_mode=artifact.mode,
        source_run_sha256=source_digest,
        pricing_snapshot_sha256=pricing_digest,
        frozen_dataset_sha256=artifact.frozen_dataset_sha256,
        fair_comparison_sha256=artifact.fair_comparison_sha256,
        shared_safety_policy_sha256=artifact.shared_safety_policy_sha256,
        case_count=len(artifact.case_ids),
        record_count=len(artifact.records),
        failure_count=len(artifact.failures),
        architecture_summaries=[
            _architecture_summary(
                architecture,
                [item for item in details if item.architecture is architecture],
            )
            for architecture in ComparisonArchitecture
        ],
        case_details=details,
        methodology={
            "model_calls": "Sum provider_calls recorded by successful normalized records.",
            "tokens": "Sum recorded input, output, and total tokens; total must equal input plus output.",
            "latency": "End-to-end record latency in milliseconds; p95 uses nearest rank.",
            "cost": (
                "Input tokens times $2.00 per 1M plus output tokens times $12.00 "
                "per 1M, rounded to 8 decimal places under the dated pricing snapshot."
            ),
            "failures": (
                "Failed executions remain visible but their calls, tokens, latency, and "
                "cost are unobserved rather than treated as zero."
            ),
        },
    )


def build_step_4_14_smoke_report() -> EfficiencyReport:
    return calculate_efficiency(load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH))


def serialize_efficiency_report(report: EfficiencyReport) -> tuple[str, str]:
    content = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def write_efficiency_report(
    report: EfficiencyReport,
    output_path: Path,
) -> tuple[str, str]:
    content, digest = serialize_efficiency_report(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != content:
        raise EfficiencyMetricsError("refusing to overwrite a different efficiency report")
    output_path.write_text(content, encoding="utf-8")
    digest_path = output_path.with_suffix(".sha256")
    digest_content = f"{digest}  {output_path.name}\n"
    if digest_path.exists() and digest_path.read_text(encoding="utf-8") != digest_content:
        raise EfficiencyMetricsError("refusing to overwrite a different efficiency checksum")
    digest_path.write_text(digest_content, encoding="utf-8")
    return content, digest
