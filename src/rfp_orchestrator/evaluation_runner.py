"""Reproducible, gold-isolated evaluation runner for Step 4.11."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import date
from enum import Enum
from pathlib import Path
from time import perf_counter
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.comparison_safety import (
    DEFAULT_SHARED_SAFETY_POLICY_PATH,
    PostEvidenceSafetyFacts,
    assess_comparison_preflight,
    assess_generalist_risk_authority,
)
from rfp_orchestrator.evaluation_freeze import (
    file_sha256,
    text_sha256,
    validate_frozen_gold,
)
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    EVALUATION_DATASET_ID,
    EXPECTED_CASE_IDS,
    EvaluationCase,
    load_evaluation_dataset,
)
from rfp_orchestrator.fair_comparison import (
    DEFAULT_FAIR_COMPARISON_PATH,
    NORMALIZED_OUTPUT_FIELDS,
    ComparisonArchitecture,
)
from rfp_orchestrator.generalist_baseline import (
    GeneralistBaselineResult,
    GeneralistDraft,
    GeneralistReasoningRequest,
    GeneralistToolName,
    GeneralistToolSession,
    SingleGeneralistBaseline,
)
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.models import (
    Claim,
    Domain,
    Requirement,
    RequirementStatus,
    RiskClass,
    SpecialistOutput,
    SupportStatus,
    aggregate_support,
)
from rfp_orchestrator.requirement_classification import analyze_requirement_input
from rfp_orchestrator.retrieval import (
    EvidenceChunk,
    OfflineSpecialistRetrievers,
    build_offline_retrievers,
)
from rfp_orchestrator.source_validation import validate_source_metadata
from rfp_orchestrator.state import GraphState, new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DRY_RUN_OUTPUT_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "dry_run_step_4_11.json"
)
DEFAULT_DRY_RUN_DIGEST_PATH = DEFAULT_DRY_RUN_OUTPUT_PATH.with_suffix(".sha256")
OFFLINE_DRY_RUN_ID = "step-4-11-offline-dry-eval-001"
OFFLINE_DRY_RUN_STARTED_AT = "2026-09-03T23:45:00-04:00"
OFFLINE_DRY_RUN_COMPLETED_AT = "2026-09-03T23:45:01-04:00"
OFFLINE_AS_OF_DATE = date(2026, 9, 3)


class EvaluationRunnerError(ValueError):
    """Raised when an evaluation run would violate a frozen boundary."""


class EvaluationRunMode(str, Enum):
    OFFLINE_DRY_RUN = "OFFLINE_DRY_RUN"
    FAKE_PROVIDER_REHEARSAL = "FAKE_PROVIDER_REHEARSAL"
    PROVIDER_COMPARISON = "PROVIDER_COMPARISON"


class EvaluationRunStatus(str, Enum):
    COMPLETE = "COMPLETE"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class EvaluationCaseInput(BaseModel):
    """The only case fields visible to an architecture executor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    untrusted_rfp_text: str = Field(min_length=1)


class RetrievalCallRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    domain: Domain
    query: str = Field(min_length=1)
    requested_k: int = Field(ge=1, le=5)
    retrieval_methods: list[str] = Field(min_length=1)
    result_ids: list[str] = Field(max_length=5)

    @model_validator(mode="after")
    def call_is_clean(self) -> RetrievalCallRecord:
        collections = (self.retrieval_methods, self.result_ids)
        if any(len(values) != len(set(values)) for values in collections):
            raise ValueError("retrieval call collections cannot contain duplicates")
        if any(not value.strip() for values in collections for value in values):
            raise ValueError("retrieval call values cannot be blank")
        return self


class EvaluationModelUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(min_length=1)
    model: str = Field(min_length=1)
    provider_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def token_total_is_exact(self) -> EvaluationModelUsage:
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("model usage total must equal input plus output tokens")
        return self


class EvaluationErrorRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    error_type: str = Field(min_length=1)
    message: str = Field(min_length=1)


class EvaluationRunRecord(BaseModel):
    """The exact 22-field normalized output frozen in Step 4.9."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    architecture: ComparisonArchitecture
    atomic_requirements: list[str]
    consulted_domains: list[Domain]
    retrieval_calls: list[RetrievalCallRecord]
    evidence: list[EvidenceChunk]
    claims: list[Claim]
    proposed_answer: str | None
    support_status: SupportStatus
    citation_valid: bool | None
    source_metadata_valid: bool | None
    conflicts: list[dict[str, object]]
    retry_count: int = Field(ge=0, le=2)
    risk_classes: list[RiskClass]
    authority_required: bool
    awaiting_human_review: bool
    final_status: RequirementStatus | None
    final_answer: str | None
    errors: list[EvaluationErrorRecord]
    model_usage: EvaluationModelUsage
    latency_ms: float = Field(ge=0)

    @model_validator(mode="after")
    def record_is_normalized(self) -> EvaluationRunRecord:
        if tuple(type(self).model_fields) != NORMALIZED_OUTPUT_FIELDS:
            raise ValueError("evaluation record fields drifted from the frozen contract")
        collections = {
            "atomic requirements": self.atomic_requirements,
            "consulted domains": self.consulted_domains,
            "evidence IDs": [item.chunk_id for item in self.evidence],
            "claim IDs": [item.claim_id for item in self.claims],
            "risk classes": self.risk_classes,
        }
        if any(len(values) != len(set(values)) for values in collections.values()):
            raise ValueError("normalized record collections cannot contain duplicates")
        if any(not item.strip() for item in self.atomic_requirements):
            raise ValueError("atomic requirements cannot be blank")
        if self.support_status is not aggregate_support(self.claims):
            raise ValueError("record support status must aggregate from claim Booleans")

        evidence_ids = {item.chunk_id for item in self.evidence}
        if any(
            citation_id not in evidence_ids
            for claim in self.claims
            for citation_id in claim.evidence_ids
        ):
            raise ValueError("record claim cites evidence absent from the record")
        call_result_ids = {
            result_id for call in self.retrieval_calls for result_id in call.result_ids
        }
        if not call_result_ids.issubset(evidence_ids):
            raise ValueError("retrieval call result is absent from record evidence")
        called_domains = list(dict.fromkeys(call.domain for call in self.retrieval_calls))
        if self.consulted_domains != called_domains:
            raise ValueError("consulted domains must follow actual retrieval calls")

        if self.final_status is RequirementStatus.FINALIZED:
            if not self.final_answer or not self.final_answer.strip():
                raise ValueError("FINALIZED record requires a final answer")
            if self.awaiting_human_review:
                raise ValueError("FINALIZED record cannot await human review")
        if (
            self.final_status is RequirementStatus.NEEDS_HUMAN
            and (not self.awaiting_human_review or self.final_answer is not None)
        ):
            raise ValueError("NEEDS_HUMAN record must pause without a final answer")
        return self


class EvaluationRunFailure(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str = Field(min_length=1)
    requirement_id: str = Field(min_length=1)
    architecture: ComparisonArchitecture
    error_type: str = Field(min_length=1)
    message: str = Field(min_length=1)


class EvaluationRunArtifact(BaseModel):
    """Run-level provenance plus normalized successes and preserved failures."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    run_id: str = Field(min_length=1)
    mode: EvaluationRunMode
    status: EvaluationRunStatus
    started_at: str = Field(min_length=1)
    completed_at: str = Field(min_length=1)
    dataset_id: Literal["northstar-rfp-evaluation-v1"] = EVALUATION_DATASET_ID
    frozen_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fair_comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    shared_safety_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    random_seed: int = Field(ge=0)
    case_ids: list[str] = Field(min_length=1)
    architectures: list[ComparisonArchitecture] = Field(min_length=2, max_length=2)
    gold_labels_exposed: Literal[False] = False
    scoring_performed: bool
    provider_calls_made: int = Field(ge=0)
    records: list[EvaluationRunRecord]
    failures: list[EvaluationRunFailure]

    @model_validator(mode="after")
    def artifact_is_complete_and_honest(self) -> EvaluationRunArtifact:
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("run case IDs cannot repeat")
        if self.architectures != list(ComparisonArchitecture):
            raise ValueError("runner must preserve the canonical architecture order")
        record_keys = [(item.case_id, item.architecture) for item in self.records]
        failure_keys = [(item.case_id, item.architecture) for item in self.failures]
        if len(record_keys) != len(set(record_keys)):
            raise ValueError("run records cannot repeat case and architecture")
        if set(record_keys) & set(failure_keys):
            raise ValueError("one execution cannot be both a record and a failure")
        expected_keys = {
            (case_id, architecture)
            for case_id in self.case_ids
            for architecture in self.architectures
        }
        if set(record_keys) | set(failure_keys) != expected_keys:
            raise ValueError("every case and architecture requires a record or failure")
        expected_status = (
            EvaluationRunStatus.COMPLETE
            if not self.failures
            else EvaluationRunStatus.FAILED
            if not self.records
            else EvaluationRunStatus.PARTIAL
        )
        if self.status is not expected_status:
            raise ValueError("run status must reflect preserved failures")
        if self.mode is EvaluationRunMode.OFFLINE_DRY_RUN:
            if len(self.case_ids) != 1 or len(self.records) + len(self.failures) != 2:
                raise ValueError("offline dry run requires one paired case")
            if self.provider_calls_made != 0 or self.scoring_performed:
                raise ValueError("offline dry run cannot call providers or score gold")
            if any(item.model_usage.provider_calls for item in self.records):
                raise ValueError("offline dry records cannot claim provider usage")
        return self


class ArchitectureExecutor(Protocol):
    architecture: ComparisonArchitecture

    def execute(self, case: EvaluationCaseInput) -> EvaluationRunRecord: ...


def _offline_usage() -> EvaluationModelUsage:
    return EvaluationModelUsage(
        provider="offline_fixture",
        model="deterministic_no_llm",
        provider_calls=0,
        input_tokens=0,
        output_tokens=0,
        total_tokens=0,
    )


def _elapsed_ms(timer: Callable[[], float], operation: Callable[[], object]) -> tuple[object, float]:
    started = timer()
    value = operation()
    completed = timer()
    return value, round(max(0.0, completed - started) * 1_000, 3)


def _case_input(case: EvaluationCase) -> EvaluationCaseInput:
    return EvaluationCaseInput(
        case_id=case.case_id,
        requirement_id=case.requirement_id,
        untrusted_rfp_text=case.untrusted_rfp_text,
    )


def _stable_offline_evidence(items: Sequence[EvidenceChunk]) -> list[EvidenceChunk]:
    """Remove platform-level float noise from reproducible offline artifacts."""

    def normalize(value: object) -> object:
        if isinstance(value, float):
            return round(value, 12)
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if isinstance(value, dict):
            return {key: normalize(item) for key, item in value.items()}
        return value

    return [
        EvidenceChunk.model_validate(normalize(item.model_dump(mode="json")))
        for item in items
    ]


class OfflineDryRunGeneralistReasoner:
    """One-agent, EVAL-001-only fixture; never used for benchmark scoring."""

    def respond(
        self,
        request: GeneralistReasoningRequest,
        tools: GeneralistToolSession,
    ) -> GeneralistDraft:
        if request.requirement_id != "RFP-001":
            raise EvaluationRunnerError(
                "offline dry generalist is intentionally limited to EVAL-001"
            )
        evidence = tools.call(
            GeneralistToolName.PRODUCT,
            request.untrusted_rfp_text,
            k=5,
        )
        availability = next(
            (item for item in evidence if item.doc_id == "PROD-AVAIL-001"),
            None,
        )
        if availability is None:
            raise EvaluationRunnerError(
                "offline dry generalist could not find the required availability source"
            )
        claims = [
            Claim(
                claim_id="generalist-claim-001",
                text="SAML 2.0 is generally available on Enterprise Cloud and Standard Cloud.",
                evidence_ids=[availability.chunk_id],
                supported=True,
            ),
            Claim(
                claim_id="generalist-claim-002",
                text="SCIM 2.0 is generally available on Enterprise Cloud.",
                evidence_ids=[availability.chunk_id],
                supported=True,
            ),
        ]
        return GeneralistDraft(
            claims=claims,
            proposed_answer=(
                "SAML 2.0 is generally available on Enterprise Cloud and Standard "
                "Cloud. SCIM 2.0 is generally available on Enterprise Cloud."
            ),
            support_status=aggregate_support(claims),
        )


class OfflineGeneralistExecutor:
    architecture = ComparisonArchitecture.SINGLE_GENERALIST

    def __init__(
        self,
        retrievers: OfflineSpecialistRetrievers,
        *,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        self._baseline = SingleGeneralistBaseline.from_offline_retrievers(
            retrievers,
            reasoner=OfflineDryRunGeneralistReasoner(),
        )
        self._timer = timer

    def execute(self, case: EvaluationCaseInput) -> EvaluationRunRecord:
        requirement = analyze_requirement_input(
            Requirement(
                requirement_id=case.requirement_id,
                original_text=case.untrusted_rfp_text,
            )
        )
        preflight = assess_comparison_preflight(self.architecture, requirement)
        if preflight.requires_human:
            return EvaluationRunRecord(
                case_id=case.case_id,
                requirement_id=case.requirement_id,
                architecture=self.architecture,
                atomic_requirements=requirement.atomic_requirements,
                consulted_domains=[],
                retrieval_calls=[],
                evidence=[],
                claims=[],
                proposed_answer=None,
                support_status=SupportStatus.UNSUPPORTED,
                citation_valid=None,
                source_metadata_valid=None,
                conflicts=[],
                retry_count=0,
                risk_classes=preflight.risk_classes,
                authority_required=True,
                awaiting_human_review=True,
                final_status=RequirementStatus.NEEDS_HUMAN,
                final_answer=None,
                errors=[],
                model_usage=_offline_usage(),
                latency_ms=0.0,
            )

        raw_result, latency_ms = _elapsed_ms(
            self._timer,
            lambda: self._baseline.run(requirement),
        )
        result = GeneralistBaselineResult.model_validate(raw_result)
        evidence = _stable_offline_evidence(
            list(
                {
                    item.chunk_id: item
                    for call in result.tool_calls
                    for item in call.evidence
                }.values()
            )
        )
        cited_ids = list(
            dict.fromkeys(
                evidence_id
                for claim in result.claims
                for evidence_id in claim.evidence_ids
            )
        )
        source_validation = validate_source_metadata(
            {
                "citation_valid": True,
                "citation_validation": {"cited_evidence_ids": cited_ids},
                "evidence": [item.model_dump(mode="json") for item in evidence],
            },
            as_of=OFFLINE_AS_OF_DATE,
        )
        safety_facts = PostEvidenceSafetyFacts(
            citation_valid=True,
            source_metadata_valid=source_validation.valid,
            claim_support_valid=True,
            commitment_consistent=True,
        )
        assessment = assess_generalist_risk_authority(
            requirement,
            result,
            safety_facts,
        )
        awaiting = assessment.requires_human
        final_status = (
            RequirementStatus.NEEDS_HUMAN
            if awaiting
            else RequirementStatus.FINALIZED
        )
        return EvaluationRunRecord(
            case_id=case.case_id,
            requirement_id=case.requirement_id,
            architecture=self.architecture,
            atomic_requirements=requirement.atomic_requirements,
            consulted_domains=list(dict.fromkeys(call.domain for call in result.tool_calls)),
            retrieval_calls=[
                RetrievalCallRecord(
                    call_id=f"{case.case_id}:generalist:{index}",
                    tool_name=call.tool_name.value,
                    domain=call.domain,
                    query=call.query,
                    requested_k=call.requested_k,
                    retrieval_methods=list(
                        dict.fromkeys(item.retrieval_method.value for item in call.evidence)
                    ),
                    result_ids=[item.chunk_id for item in call.evidence],
                )
                for index, call in enumerate(result.tool_calls, start=1)
            ],
            evidence=evidence,
            claims=result.claims,
            proposed_answer=result.proposed_answer,
            support_status=result.support_status,
            citation_valid=True,
            source_metadata_valid=source_validation.valid,
            conflicts=[],
            retry_count=0,
            risk_classes=assessment.risk_classes,
            authority_required=assessment.requires_human,
            awaiting_human_review=awaiting,
            final_status=final_status,
            final_answer=None if awaiting else result.proposed_answer,
            errors=[],
            model_usage=_offline_usage(),
            latency_ms=latency_ms,
        )


class InvokableGraph(Protocol):
    def invoke(self, state: GraphState) -> GraphState: ...


class OfflineOrchestratedExecutor:
    architecture = ComparisonArchitecture.ORCHESTRATED_PEERS

    def __init__(
        self,
        retrievers: OfflineSpecialistRetrievers,
        *,
        timer: Callable[[], float] = perf_counter,
    ) -> None:
        self._graph: InvokableGraph = build_selected_fanout_graph(
            retrievers,
            event_clock=lambda: "offline-dry-run",
        )
        self._timer = timer

    def execute(self, case: EvaluationCaseInput) -> EvaluationRunRecord:
        raw_state, latency_ms = _elapsed_ms(
            self._timer,
            lambda: self._graph.invoke(
                new_requirement_state(
                    case.case_id,
                    case.requirement_id,
                    case.untrusted_rfp_text,
                )
            ),
        )
        state = dict(raw_state)
        outputs = [
            SpecialistOutput.model_validate(item)
            for item in state.get("merged_specialist_outputs", [])
        ]
        evidence = _stable_offline_evidence(
            [EvidenceChunk.model_validate(item) for item in state.get("evidence", [])]
        )
        claims = [claim for output in outputs for claim in output.claims]
        branch_evidence = state.get("specialist_evidence", {})
        calls = []
        for index, domain_value in enumerate(state.get("merge_order", []), start=1):
            domain = Domain(domain_value)
            items = [
                EvidenceChunk.model_validate(item)
                for item in branch_evidence.get(domain_value, [])
            ]
            calls.append(
                RetrievalCallRecord(
                    call_id=f"{case.case_id}:orchestrated:{index}",
                    tool_name=f"search_{domain.value}_evidence",
                    domain=domain,
                    query=case.untrusted_rfp_text,
                    requested_k=5,
                    retrieval_methods=list(
                        dict.fromkeys(item.retrieval_method.value for item in items)
                    ),
                    result_ids=[item.chunk_id for item in items],
                )
            )
        final_status = (
            RequirementStatus(state["final_status"])
            if state.get("final_status")
            else None
        )
        conflicts = list(
            (state.get("commitment_consistency") or {}).get("conflicts", [])
        )
        proposed_answer = " ".join(
            output.proposed_answer.strip() for output in outputs if output.proposed_answer.strip()
        ) or None
        return EvaluationRunRecord(
            case_id=case.case_id,
            requirement_id=case.requirement_id,
            architecture=self.architecture,
            atomic_requirements=list(state.get("atomic_requirements", [])),
            consulted_domains=[call.domain for call in calls],
            retrieval_calls=calls,
            evidence=evidence,
            claims=claims,
            proposed_answer=proposed_answer,
            support_status=aggregate_support(claims),
            citation_valid=state.get("citation_valid"),
            source_metadata_valid=state.get("source_metadata_valid"),
            conflicts=conflicts,
            retry_count=int(state.get("retry_count", 0)),
            risk_classes=[RiskClass(value) for value in state.get("risk_classes", [])],
            authority_required=bool(state.get("authority_required", False)),
            awaiting_human_review=bool(state.get("awaiting_human_review", False)),
            final_status=final_status,
            final_answer=state.get("final_answer"),
            errors=[],
            model_usage=_offline_usage(),
            latency_ms=latency_ms,
        )


class EvaluationRunner:
    def __init__(
        self,
        executors: Mapping[ComparisonArchitecture, ArchitectureExecutor],
        *,
        provider_call_counter: Callable[[], int] | None = None,
    ):
        if list(executors) != list(ComparisonArchitecture):
            raise EvaluationRunnerError(
                "runner requires both architectures in canonical order"
            )
        if any(executor.architecture is not architecture for architecture, executor in executors.items()):
            raise EvaluationRunnerError("executor key and architecture do not match")
        self._executors = dict(executors)
        self._provider_call_counter = provider_call_counter

    def run(
        self,
        *,
        case_ids: Sequence[str],
        mode: EvaluationRunMode,
        run_id: str,
        started_at: str,
        completed_at: str,
        random_seed: int = 0,
        provider_execution_authorized: bool = False,
    ) -> EvaluationRunArtifact:
        dataset = load_evaluation_dataset()
        validate_frozen_gold(dataset)
        if len(case_ids) != len(set(case_ids)):
            raise EvaluationRunnerError("requested evaluation case IDs cannot repeat")
        by_id = {case.case_id: case for case in dataset.cases}
        unknown = [case_id for case_id in case_ids if case_id not in by_id]
        if unknown:
            raise EvaluationRunnerError(
                "unknown evaluation case IDs: " + ", ".join(unknown)
            )
        if (
            mode is EvaluationRunMode.PROVIDER_COMPARISON
            and not provider_execution_authorized
        ):
            raise EvaluationRunnerError(
                "provider comparison is disabled until a reviewed execution budget and explicit approval exist"
            )
        if mode is EvaluationRunMode.OFFLINE_DRY_RUN and list(case_ids) != ["EVAL-001"]:
            raise EvaluationRunnerError(
                "Step 4.11 offline dry mode is intentionally limited to EVAL-001"
            )
        if (
            mode is EvaluationRunMode.FAKE_PROVIDER_REHEARSAL
            and list(case_ids) != list(EXPECTED_CASE_IDS)
        ):
            raise EvaluationRunnerError(
                "fake provider rehearsal requires all 24 frozen cases in order"
            )

        records: list[EvaluationRunRecord] = []
        failures: list[EvaluationRunFailure] = []
        provider_calls_before = (
            self._provider_call_counter()
            if self._provider_call_counter is not None
            else 0
        )
        for case_id in case_ids:
            case_input = _case_input(by_id[case_id])
            for architecture, executor in self._executors.items():
                try:
                    records.append(executor.execute(case_input))
                except Exception as error:  # noqa: BLE001 -- failures are preserved as data
                    failures.append(
                        EvaluationRunFailure(
                            case_id=case_input.case_id,
                            requirement_id=case_input.requirement_id,
                            architecture=architecture,
                            error_type=type(error).__name__,
                            message=str(error) or "Execution failed without a message.",
                        )
                    )
        status = (
            EvaluationRunStatus.COMPLETE
            if not failures
            else EvaluationRunStatus.FAILED
            if not records
            else EvaluationRunStatus.PARTIAL
        )
        return EvaluationRunArtifact(
            run_id=run_id,
            mode=mode,
            status=status,
            started_at=started_at,
            completed_at=completed_at,
            frozen_dataset_sha256=file_sha256(DEFAULT_EVALUATION_DATASET_PATH),
            fair_comparison_sha256=file_sha256(DEFAULT_FAIR_COMPARISON_PATH),
            shared_safety_policy_sha256=file_sha256(
                DEFAULT_SHARED_SAFETY_POLICY_PATH
            ),
            random_seed=random_seed,
            case_ids=list(case_ids),
            architectures=list(ComparisonArchitecture),
            scoring_performed=False,
            provider_calls_made=(
                self._provider_call_counter() - provider_calls_before
                if self._provider_call_counter is not None
                else sum(record.model_usage.provider_calls for record in records)
            ),
            records=records,
            failures=failures,
        )


class _DeterministicTimer:
    def __init__(self, elapsed_ms: float = 1.0) -> None:
        self._values = iter((0.0, elapsed_ms / 1_000))

    def __call__(self) -> float:
        return next(self._values)


def build_offline_dry_runner() -> EvaluationRunner:
    retrievers = build_offline_retrievers(PROJECT_ROOT / "data" / "kb")
    return EvaluationRunner(
        {
            ComparisonArchitecture.SINGLE_GENERALIST: OfflineGeneralistExecutor(
                retrievers,
                timer=_DeterministicTimer(),
            ),
            ComparisonArchitecture.ORCHESTRATED_PEERS: OfflineOrchestratedExecutor(
                retrievers,
                timer=_DeterministicTimer(),
            ),
        }
    )


def build_step_4_11_dry_run() -> EvaluationRunArtifact:
    return build_offline_dry_runner().run(
        case_ids=["EVAL-001"],
        mode=EvaluationRunMode.OFFLINE_DRY_RUN,
        run_id=OFFLINE_DRY_RUN_ID,
        started_at=OFFLINE_DRY_RUN_STARTED_AT,
        completed_at=OFFLINE_DRY_RUN_COMPLETED_AT,
        random_seed=0,
    )


def serialize_evaluation_run(
    artifact: EvaluationRunArtifact,
) -> tuple[str, str]:
    content = json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def write_evaluation_run(
    artifact: EvaluationRunArtifact,
    output_path: Path,
) -> tuple[str, str]:
    content, digest = serialize_evaluation_run(artifact)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != content:
        raise EvaluationRunnerError("refusing to overwrite a different evaluation run")
    output_path.write_text(content, encoding="utf-8")
    digest_path = output_path.with_suffix(".sha256")
    digest_content = f"{digest}  {output_path.name}\n"
    if digest_path.exists() and digest_path.read_text(encoding="utf-8") != digest_content:
        raise EvaluationRunnerError("refusing to overwrite a different run checksum")
    digest_path.write_text(digest_content, encoding="utf-8")
    return content, digest
