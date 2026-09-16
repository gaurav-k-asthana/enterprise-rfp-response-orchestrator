"""Auditable Step 4.12 metrics calculated from saved evaluation records."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.comparison_safety import DEFAULT_SHARED_SAFETY_POLICY_PATH
from rfp_orchestrator.evaluation_freeze import (
    file_sha256,
    text_sha256,
    validate_frozen_gold,
)
from rfp_orchestrator.evaluation_runner import (
    DEFAULT_DRY_RUN_OUTPUT_PATH,
    EvaluationRunArtifact,
    EvaluationRunMode,
    EvaluationRunRecord,
    serialize_evaluation_run,
)
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    EvaluationCase,
    EvaluationDataset,
    EvaluationFailureCategory,
    ExpectedHitlBehavior,
    load_evaluation_dataset,
)
from rfp_orchestrator.fair_comparison import (
    DEFAULT_FAIR_COMPARISON_PATH,
    ComparisonArchitecture,
)
from rfp_orchestrator.models import Domain, RequirementStatus, RiskClass

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_METRICS_OUTPUT_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "metrics_smoke_step_4_12.json"
)
DEFAULT_METRICS_DIGEST_PATH = DEFAULT_METRICS_OUTPUT_PATH.with_suffix(".sha256")
METRIC_REPORT_VERSION = "1.0"


class EvaluationMetricsError(ValueError):
    """Raised when a run cannot be scored without breaking evaluation controls."""


class RateMetric(BaseModel):
    """One integer ratio with its calculation visible in the artifact."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    numerator: int = Field(ge=0)
    denominator: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def value_matches_counts(self) -> RateMetric:
        expected = (
            None
            if self.denominator == 0
            else round(self.numerator / self.denominator, 12)
        )
        if self.value != expected:
            raise ValueError("rate value must equal numerator divided by denominator")
        return self


class AverageMetric(BaseModel):
    """One arithmetic mean with its total and observation count exposed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    total: float = Field(ge=0)
    count: int = Field(ge=0)
    value: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def value_matches_total(self) -> AverageMetric:
        expected = None if self.count == 0 else round(self.total / self.count, 12)
        if self.value != expected:
            raise ValueError("average value must equal total divided by count")
        return self


class BinaryMetricSummary(BaseModel):
    """Precision, recall, F1, and accuracy for a binary decision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    true_negative: int = Field(ge=0)
    precision: float | None = Field(default=None, ge=0, le=1)
    recall: float | None = Field(default=None, ge=0, le=1)
    f1: float | None = Field(default=None, ge=0, le=1)
    accuracy: float | None = Field(default=None, ge=0, le=1)


class CaseMetricDetail(BaseModel):
    """Case-level inputs needed to regenerate every Step 4.12 summary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    requirement_id: str
    architecture: ComparisonArchitecture
    execution_failed: bool
    failure_type: str | None
    expected_domains: list[Domain]
    observed_domains: list[Domain]
    routing_precision: float
    routing_recall: float
    routing_f1: float
    gold_evidence_ids: list[str]
    retrieved_evidence_ids: list[str]
    recall_at_5: float | None
    claim_count: int = Field(ge=0)
    unsupported_claim_count: int = Field(ge=0)
    grounded_claim_count: int = Field(ge=0)
    citation_applicable: bool
    citation_valid: bool | None
    expected_hitl: bool
    observed_hitl: bool
    expected_conflict: bool
    observed_conflict: bool
    expected_recovery: bool
    observed_recovery: bool
    retry_count: int = Field(ge=0, le=2)
    recovery_bounded: bool | None


class ArchitectureMetricSummary(BaseModel):
    """All Step 4.12 metrics for one comparison arm."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    architecture: ComparisonArchitecture
    requested_case_count: int = Field(ge=1)
    execution_success_rate: RateMetric
    routing_micro: BinaryMetricSummary
    routing_macro_f1: AverageMetric
    retrieval_recall_at_5: AverageMetric
    unsupported_claim_rate: RateMetric
    groundedness: RateMetric
    citation_validity: RateMetric
    hitl: BinaryMetricSummary
    conflict_detection: BinaryMetricSummary
    recovery_detection: BinaryMetricSummary
    bounded_recovery_rate: RateMetric
    mean_retry_count: AverageMetric


class EvaluationMetricReport(BaseModel):
    """Content-addressed metric report derived from one saved raw run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    metric_version: Literal["1.0"] = METRIC_REPORT_VERSION
    report_id: str
    report_scope: Literal["SMOKE_ONLY", "RAW_METRICS_ONLY"]
    source_run_id: str
    source_run_mode: EvaluationRunMode
    source_run_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fair_comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    shared_safety_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gold_scoring_performed: Literal[True] = True
    gold_labels_exposed_to_executors: Literal[False] = False
    safe_completion_rate_calculated: Literal[False] = False
    comparative_conclusions_allowed: Literal[False] = False
    provider_calls_in_source_run: int = Field(ge=0)
    case_count: int = Field(ge=1)
    record_count: int = Field(ge=0)
    failure_count: int = Field(ge=0)
    architecture_summaries: list[ArchitectureMetricSummary]
    case_details: list[CaseMetricDetail]
    definitions: dict[str, str]

    @model_validator(mode="after")
    def report_is_complete(self) -> EvaluationMetricReport:
        if [item.architecture for item in self.architecture_summaries] != list(
            ComparisonArchitecture
        ):
            raise ValueError("metric summaries must preserve architecture order")
        expected_details = self.case_count * len(ComparisonArchitecture)
        if len(self.case_details) != expected_details:
            raise ValueError("every case and architecture requires metric detail")
        if self.record_count + self.failure_count != expected_details:
            raise ValueError("records and failures must cover every requested execution")
        return self


METRIC_DEFINITIONS = {
    "routing_f1": (
        "Micro domain-label precision, recall, and F1 plus mean per-case F1; "
        "all requested cases remain in the denominator."
    ),
    "recall_at_5": (
        "Per case, unique retrieved evidence IDs matching frozen gold evidence IDs "
        "divided by gold evidence count; cases with no gold evidence are not applicable."
    ),
    "unsupported_claim_rate": (
        "Emitted atomic material claims with supported=false divided by all emitted "
        "claims. This diagnoses evidence coverage and does not alone judge safe refusal."
    ),
    "groundedness": (
        "Claims that are supported, cite present evidence, and belong to a record with "
        "valid citations and source metadata divided by all emitted material claims."
    ),
    "citation_validity": (
        "Applicable successful records with citation_valid=true divided by applicable "
        "successful records; pre-retrieval records without claims or retrieval are excluded."
    ),
    "hitl": (
        "Binary precision, recall, F1, and accuracy for required human review versus "
        "an observed NEEDS_HUMAN or awaiting-human state. CONDITIONAL gold is not a positive."
    ),
    "conflict_detection": (
        "Binary metrics for frozen CONFLICTING_EVIDENCE expectations versus an observed "
        "conflict record or CONFLICTING_EVIDENCE risk class."
    ),
    "recovery": (
        "Binary metrics for frozen recovery-failure cases versus retry activity or a "
        "RETRY_BUDGET_EXHAUSTED risk; bounded recovery means no more than two retries."
    ),
    "execution_success": (
        "Successful normalized records divided by all requested case/architecture pairs; "
        "preserved failures are never discarded."
    ),
    "safe_completion_rate": "Not calculated until Step 4.13.",
}


def _round_ratio(numerator: int, denominator: int) -> float | None:
    return None if denominator == 0 else round(numerator / denominator, 12)


def rate_metric(numerator: int, denominator: int) -> RateMetric:
    return RateMetric(
        numerator=numerator,
        denominator=denominator,
        value=_round_ratio(numerator, denominator),
    )


def average_metric(values: Sequence[float]) -> AverageMetric:
    total = round(sum(values), 12)
    return AverageMetric(
        total=total,
        count=len(values),
        value=None if not values else round(total / len(values), 12),
    )


def binary_metrics(
    expected: Sequence[bool], observed: Sequence[bool]
) -> BinaryMetricSummary:
    if len(expected) != len(observed):
        raise EvaluationMetricsError("binary metric inputs must have equal length")
    true_positive = sum(want and got for want, got in zip(expected, observed, strict=True))
    false_positive = sum(not want and got for want, got in zip(expected, observed, strict=True))
    false_negative = sum(want and not got for want, got in zip(expected, observed, strict=True))
    true_negative = sum(not want and not got for want, got in zip(expected, observed, strict=True))
    precision = _round_ratio(true_positive, true_positive + false_positive)
    recall = _round_ratio(true_positive, true_positive + false_negative)
    f1_denominator = (2 * true_positive) + false_positive + false_negative
    f1 = (
        None
        if f1_denominator == 0
        else round((2 * true_positive) / f1_denominator, 12)
    )
    accuracy = _round_ratio(true_positive + true_negative, len(expected))
    return BinaryMetricSummary(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
        true_negative=true_negative,
        precision=precision,
        recall=recall,
        f1=f1,
        accuracy=accuracy,
    )


def _routing_scores(
    expected: set[Domain], observed: set[Domain]
) -> tuple[float, float, float]:
    true_positive = len(expected & observed)
    precision = 1.0 if not observed and not expected else (
        true_positive / len(observed) if observed else 0.0
    )
    recall = 1.0 if not expected and not observed else (
        true_positive / len(expected) if expected else 0.0
    )
    denominator = len(expected) + len(observed)
    f1 = 1.0 if denominator == 0 else (2 * true_positive) / denominator
    return round(precision, 12), round(recall, 12), round(f1, 12)


def _retrieved_ids(record: EvaluationRunRecord | None) -> list[str]:
    if record is None:
        return []
    return list(
        dict.fromkeys(
            result_id
            for call in record.retrieval_calls
            for result_id in call.result_ids
        )
    )


def _case_detail(
    *,
    case: EvaluationCase,
    architecture: ComparisonArchitecture,
    record: EvaluationRunRecord | None,
    failure_type: str | None,
) -> CaseMetricDetail:
    labels = case.gold_labels
    expected_domains = set(labels.expected_domains)
    observed_domains = set(record.consulted_domains if record else [])
    routing_precision, routing_recall, routing_f1 = _routing_scores(
        expected_domains, observed_domains
    )
    retrieved_ids = _retrieved_ids(record)
    gold_ids = labels.gold_evidence_ids
    recall_at_5 = (
        None
        if not gold_ids
        else round(len(set(gold_ids) & set(retrieved_ids)) / len(gold_ids), 12)
    )
    claims = record.claims if record else []
    evidence_ids = {item.chunk_id for item in record.evidence} if record else set()
    grounded_claim_count = sum(
        claim.supported
        and bool(claim.evidence_ids)
        and set(claim.evidence_ids).issubset(evidence_ids)
        and record is not None
        and record.citation_valid is True
        and record.source_metadata_valid is True
        for claim in claims
    )
    expected_hitl = labels.expected_hitl_behavior is ExpectedHitlBehavior.REQUIRED
    observed_hitl = bool(
        record
        and (
            record.awaiting_human_review
            or record.final_status is RequirementStatus.NEEDS_HUMAN
        )
    )
    expected_conflict = RiskClass.CONFLICTING_EVIDENCE in labels.expected_risk_classes
    observed_conflict = bool(
        record
        and (
            record.conflicts
            or RiskClass.CONFLICTING_EVIDENCE in record.risk_classes
        )
    )
    expected_recovery = (
        labels.failure_category is EvaluationFailureCategory.RECOVERY_FAILURE
        or RiskClass.RETRY_BUDGET_EXHAUSTED in labels.expected_risk_classes
    )
    observed_recovery = bool(
        record
        and (
            record.retry_count > 0
            or RiskClass.RETRY_BUDGET_EXHAUSTED in record.risk_classes
        )
    )
    retry_count = record.retry_count if record else 0
    return CaseMetricDetail(
        case_id=case.case_id,
        requirement_id=case.requirement_id,
        architecture=architecture,
        execution_failed=record is None,
        failure_type=failure_type,
        expected_domains=list(labels.expected_domains),
        observed_domains=list(record.consulted_domains if record else []),
        routing_precision=routing_precision,
        routing_recall=routing_recall,
        routing_f1=routing_f1,
        gold_evidence_ids=list(gold_ids),
        retrieved_evidence_ids=retrieved_ids,
        recall_at_5=recall_at_5,
        claim_count=len(claims),
        unsupported_claim_count=sum(not claim.supported for claim in claims),
        grounded_claim_count=grounded_claim_count,
        citation_applicable=bool(record and (record.claims or record.retrieval_calls)),
        citation_valid=record.citation_valid if record else None,
        expected_hitl=expected_hitl,
        observed_hitl=observed_hitl,
        expected_conflict=expected_conflict,
        observed_conflict=observed_conflict,
        expected_recovery=expected_recovery,
        observed_recovery=observed_recovery,
        retry_count=retry_count,
        recovery_bounded=retry_count <= 2 if observed_recovery else None,
    )


def _architecture_summary(
    architecture: ComparisonArchitecture,
    details: Sequence[CaseMetricDetail],
) -> ArchitectureMetricSummary:
    routing_expected: list[bool] = []
    routing_observed: list[bool] = []
    for detail in details:
        expected = set(detail.expected_domains)
        observed = set(detail.observed_domains)
        for domain in Domain:
            routing_expected.append(domain in expected)
            routing_observed.append(domain in observed)

    claim_count = sum(item.claim_count for item in details)
    unsupported_count = sum(item.unsupported_claim_count for item in details)
    grounded_count = sum(item.grounded_claim_count for item in details)
    citation_details = [item for item in details if item.citation_applicable]
    recovery_details = [item for item in details if item.observed_recovery]
    return ArchitectureMetricSummary(
        architecture=architecture,
        requested_case_count=len(details),
        execution_success_rate=rate_metric(
            sum(not item.execution_failed for item in details), len(details)
        ),
        routing_micro=binary_metrics(routing_expected, routing_observed),
        routing_macro_f1=average_metric([item.routing_f1 for item in details]),
        retrieval_recall_at_5=average_metric(
            [item.recall_at_5 for item in details if item.recall_at_5 is not None]
        ),
        unsupported_claim_rate=rate_metric(unsupported_count, claim_count),
        groundedness=rate_metric(grounded_count, claim_count),
        citation_validity=rate_metric(
            sum(item.citation_valid is True for item in citation_details),
            len(citation_details),
        ),
        hitl=binary_metrics(
            [item.expected_hitl for item in details],
            [item.observed_hitl for item in details],
        ),
        conflict_detection=binary_metrics(
            [item.expected_conflict for item in details],
            [item.observed_conflict for item in details],
        ),
        recovery_detection=binary_metrics(
            [item.expected_recovery for item in details],
            [item.observed_recovery for item in details],
        ),
        bounded_recovery_rate=rate_metric(
            sum(item.recovery_bounded is True for item in recovery_details),
            len(recovery_details),
        ),
        mean_retry_count=average_metric(
            [float(item.retry_count) for item in details]
        ),
    )


def _validate_source_provenance(artifact: EvaluationRunArtifact) -> None:
    expected = {
        "frozen dataset": file_sha256(DEFAULT_EVALUATION_DATASET_PATH),
        "fair comparison": file_sha256(DEFAULT_FAIR_COMPARISON_PATH),
        "shared safety policy": file_sha256(DEFAULT_SHARED_SAFETY_POLICY_PATH),
    }
    actual = {
        "frozen dataset": artifact.frozen_dataset_sha256,
        "fair comparison": artifact.fair_comparison_sha256,
        "shared safety policy": artifact.shared_safety_policy_sha256,
    }
    drifted = [name for name in expected if expected[name] != actual[name]]
    if drifted:
        raise EvaluationMetricsError(
            "source run provenance drifted for: " + ", ".join(drifted)
        )


def calculate_metrics(
    artifact: EvaluationRunArtifact,
    dataset: EvaluationDataset | None = None,
) -> EvaluationMetricReport:
    """Score one validated, already-completed run after executor isolation ends."""

    dataset = dataset or load_evaluation_dataset()
    validate_frozen_gold(dataset)
    _validate_source_provenance(artifact)
    if artifact.gold_labels_exposed or artifact.scoring_performed:
        raise EvaluationMetricsError("source run must be unscored and gold-isolated")
    case_lookup = {case.case_id: case for case in dataset.cases}
    unknown = [case_id for case_id in artifact.case_ids if case_id not in case_lookup]
    if unknown:
        raise EvaluationMetricsError("source run contains unknown frozen case IDs")

    record_lookup = {
        (record.case_id, record.architecture): record for record in artifact.records
    }
    failure_lookup = {
        (failure.case_id, failure.architecture): failure
        for failure in artifact.failures
    }
    details: list[CaseMetricDetail] = []
    for case_id in artifact.case_ids:
        case = case_lookup[case_id]
        for architecture in artifact.architectures:
            record = record_lookup.get((case_id, architecture))
            failure = failure_lookup.get((case_id, architecture))
            if record and record.requirement_id != case.requirement_id:
                raise EvaluationMetricsError("run requirement ID does not match frozen case")
            if failure and failure.requirement_id != case.requirement_id:
                raise EvaluationMetricsError("failure requirement ID does not match frozen case")
            details.append(
                _case_detail(
                    case=case,
                    architecture=architecture,
                    record=record,
                    failure_type=failure.error_type if failure else None,
                )
            )

    _, source_digest = serialize_evaluation_run(artifact)
    report_scope = (
        "SMOKE_ONLY"
        if artifact.mode is EvaluationRunMode.OFFLINE_DRY_RUN
        else "RAW_METRICS_ONLY"
    )
    return EvaluationMetricReport(
        report_id=f"metrics:{artifact.run_id}:v1",
        report_scope=report_scope,
        source_run_id=artifact.run_id,
        source_run_mode=artifact.mode,
        source_run_sha256=source_digest,
        frozen_dataset_sha256=artifact.frozen_dataset_sha256,
        fair_comparison_sha256=artifact.fair_comparison_sha256,
        shared_safety_policy_sha256=artifact.shared_safety_policy_sha256,
        provider_calls_in_source_run=artifact.provider_calls_made,
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
        definitions=METRIC_DEFINITIONS,
    )


def load_evaluation_run(path: Path) -> EvaluationRunArtifact:
    return EvaluationRunArtifact.model_validate_json(path.read_text(encoding="utf-8"))


def build_step_4_12_smoke_report() -> EvaluationMetricReport:
    return calculate_metrics(load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH))


def serialize_metric_report(report: EvaluationMetricReport) -> tuple[str, str]:
    content = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def write_metric_report(
    report: EvaluationMetricReport, output_path: Path
) -> tuple[str, str]:
    content, digest = serialize_metric_report(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != content:
        raise EvaluationMetricsError("refusing to overwrite a different metric report")
    output_path.write_text(content, encoding="utf-8")
    digest_path = output_path.with_suffix(".sha256")
    digest_content = f"{digest}  {output_path.name}\n"
    if digest_path.exists() and digest_path.read_text(encoding="utf-8") != digest_content:
        raise EvaluationMetricsError("refusing to overwrite a different metric checksum")
    digest_path.write_text(digest_content, encoding="utf-8")
    return content, digest
