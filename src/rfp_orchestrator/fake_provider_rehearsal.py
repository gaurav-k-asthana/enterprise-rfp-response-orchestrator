"""Offline 24-case rehearsal of both provider architecture boundaries."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from threading import Lock
from types import SimpleNamespace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_freeze import text_sha256
from rfp_orchestrator.evaluation_runner import (
    ArchitectureExecutor,
    EvaluationCaseInput,
    EvaluationRunArtifact,
    EvaluationRunMode,
    EvaluationRunner,
)
from rfp_orchestrator.evaluation_schema import EXPECTED_CASE_IDS
from rfp_orchestrator.evaluation_trials import load_repeat_trial_plan
from rfp_orchestrator.fair_comparison import ComparisonArchitecture
from rfp_orchestrator.generalist_baseline import GeneralistToolName
from rfp_orchestrator.models import Domain, Requirement
from rfp_orchestrator.openai_generation import OpenAIStructuredGenerationGateway
from rfp_orchestrator.provider_budget import (
    ProviderBudgetLedger,
    ProviderBudgetSnapshot,
)
from rfp_orchestrator.provider_config import EMBEDDING_DIMENSION
from rfp_orchestrator.provider_generalist import ProviderSingleGeneralistExecutor
from rfp_orchestrator.provider_orchestrated import ProviderOrchestratedExecutor
from rfp_orchestrator.provider_retrieval import (
    ProviderRetrievalSession,
    build_provider_retrieval_session,
)
from rfp_orchestrator.requirement_classification import analyze_requirement_input

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REHEARSAL_OUTPUT_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "fake_provider_rehearsal_step_4_g5.json"
)
DEFAULT_REHEARSAL_DIGEST_PATH = DEFAULT_REHEARSAL_OUTPUT_PATH.with_suffix(".sha256")
REHEARSAL_RUN_ID = "step-4-g5-fake-provider-rehearsal"
REHEARSAL_STARTED_AT = "2026-09-14T18:45:00-04:00"
REHEARSAL_COMPLETED_AT = "2026-09-14T18:45:01-04:00"


class FakeProviderCounters(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generation: ProviderBudgetSnapshot
    embedding_calls: int = Field(ge=0)
    pinecone_queries: int = Field(ge=0)


class FakeProviderRehearsalReport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    rehearsal_id: Literal["step-4-g5-fake-provider-rehearsal"] = REHEARSAL_RUN_ID
    fake_clients_only: Literal[True] = True
    external_network_calls: Literal[0] = 0
    scoring_performed: Literal[False] = False
    expected_architecture_executions: Literal[48] = 48
    accounted_architecture_executions: int = Field(ge=0)
    failures_preserved_in_denominator: bool
    deliberately_injected_failure_keys: list[str]
    counters: FakeProviderCounters
    artifact: EvaluationRunArtifact

    @model_validator(mode="after")
    def rehearsal_is_complete_and_bounded(self) -> FakeProviderRehearsalReport:
        accounted = len(self.artifact.records) + len(self.artifact.failures)
        if self.accounted_architecture_executions != accounted:
            raise ValueError("rehearsal accounted execution count drifted")
        if accounted != self.expected_architecture_executions:
            raise ValueError("rehearsal must account for all 48 paired executions")
        if self.artifact.case_ids != list(EXPECTED_CASE_IDS):
            raise ValueError("rehearsal must retain all 24 frozen cases in order")
        failure_keys = {
            f"{item.case_id}:{item.architecture.value}"
            for item in self.artifact.failures
        }
        if not set(self.deliberately_injected_failure_keys).issubset(failure_keys):
            raise ValueError("a deliberate fake failure was not preserved")
        if self.failures_preserved_in_denominator != bool(self.artifact.failures):
            raise ValueError("failure-preservation marker is inaccurate")
        generation = self.counters.generation
        budget = load_repeat_trial_plan().budget
        if generation.attempted_calls != self.artifact.provider_calls_made:
            raise ValueError("artifact provider count must include failed attempts")
        if generation.attempted_calls > budget.max_provider_calls_total:
            raise ValueError("rehearsal exceeded the total generation-call ceiling")
        if any(
            count > budget.max_provider_calls_per_architecture_execution
            for count in generation.calls_by_execution.values()
        ):
            raise ValueError("rehearsal exceeded a per-execution generation ceiling")
        if generation.total_input_tokens > budget.max_total_input_tokens:
            raise ValueError("rehearsal exceeded the input-token ceiling")
        if generation.total_output_tokens > budget.max_total_output_tokens:
            raise ValueError("rehearsal exceeded the output-token ceiling")
        return self


class FakeEmbeddingResource:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._lock = Lock()

    def create(self, **kwargs: Any) -> dict[str, Any]:
        with self._lock:
            self.calls.append(kwargs)
        return {
            "model": "text-embedding-3-small",
            "data": [{"index": 0, "embedding": [0.5] * EMBEDDING_DIMENSION}],
            "usage": {"prompt_tokens": 12, "total_tokens": 12},
        }


class FakeEmbeddingClient:
    def __init__(self, embeddings: FakeEmbeddingResource) -> None:
        self.embeddings = embeddings


class FakePineconeIndex:
    def __init__(self) -> None:
        self.queries: list[dict[str, Any]] = []
        self._lock = Lock()

    def query(self, **kwargs: Any) -> dict[str, Any]:
        domain = Domain(kwargs["filter"]["domain"]["$eq"])
        with self._lock:
            self.queries.append(kwargs)
        prefix = {
            Domain.PRODUCT: "PROD-FAKE-001",
            Domain.SECURITY: "SEC-FAKE-001",
            Domain.IMPLEMENTATION: "IMPL-FAKE-001",
        }[domain]
        return {
            "matches": [
                {
                    "id": f"{prefix}::chunk-001",
                    "score": 0.9,
                    "metadata": {
                        "doc_id": prefix,
                        "domain": domain.value,
                        "title": f"Fake {domain.value} evidence",
                        "text": (
                            f"Current Northstar {domain.value} evidence supports this "
                            "domain response with documented qualifications."
                        ),
                        "version": "1.0",
                        "effective_date": "2026-01-01",
                        "authority_rank": 5,
                        "source_status": "current",
                    },
                }
            ]
        }


class FakeStructuredResponses:
    """Return schema-correct outputs and two deliberate redacted failures."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self._lock = Lock()

    def create(self, **kwargs: Any) -> SimpleNamespace:
        schema_name = kwargs["text"]["format"]["name"]
        payload = json.loads(kwargs["input"])
        requirement_id = str(payload["requirement_id"])
        with self._lock:
            self.calls.append(kwargs)
            number = len(self.calls)

        if schema_name == "rfp_generalist_answer" and requirement_id == "RFP-007":
            raise RuntimeError("deliberate secret generalist provider failure")
        if schema_name == "rfp_specialist_answer" and requirement_id == "RFP-008":
            raise RuntimeError("deliberate secret specialist provider failure")

        if schema_name == "rfp_generalist_retrieval_plan":
            output = self._generalist_plan(payload)
        elif schema_name == "rfp_generalist_answer":
            output = self._generalist_answer(payload)
        elif schema_name == "rfp_specialist_answer":
            output = self._specialist_answer(payload)
        else:
            raise AssertionError(f"unexpected fake schema: {schema_name}")
        return SimpleNamespace(
            id=f"resp_fake_rehearsal_{number:03d}",
            status="completed",
            model="gpt-5.6-terra-2026-08-01",
            output_text=json.dumps(output),
            usage=SimpleNamespace(
                input_tokens=100,
                output_tokens=25,
                total_tokens=125,
            ),
        )

    @staticmethod
    def _generalist_plan(payload: dict[str, Any]) -> dict[str, Any]:
        requirement = analyze_requirement_input(
            Requirement(
                requirement_id=payload["requirement_id"],
                original_text=payload["untrusted_rfp_text"],
            )
        )
        domains = requirement.assigned_domains or [Domain.PRODUCT]
        tool_by_domain = {
            Domain.PRODUCT: GeneralistToolName.PRODUCT,
            Domain.SECURITY: GeneralistToolName.SECURITY,
            Domain.IMPLEMENTATION: GeneralistToolName.IMPLEMENTATION,
        }
        query = " ".join(payload["atomic_requirements"])
        return {
            "calls": [
                {
                    "tool_name": tool_by_domain[domain].value,
                    "query": query,
                    "requested_k": 5,
                }
                for domain in domains
            ]
        }

    @staticmethod
    def _generalist_answer(payload: dict[str, Any]) -> dict[str, Any]:
        claims = []
        for number, call in enumerate(payload["retrieval_calls"], start=1):
            evidence = call["evidence"]
            supported = bool(evidence)
            claims.append(
                {
                    "claim_id": f"generalist-claim-{number:03d}",
                    "text": (
                        evidence[0]["text"]
                        if supported
                        else "Available evidence does not establish this requirement."
                    ),
                    "evidence_ids": [evidence[0]["chunk_id"]] if supported else [],
                    "supported": supported,
                }
            )
        supported_count = sum(claim["supported"] for claim in claims)
        status = (
            "SUPPORTED"
            if supported_count == len(claims)
            else "PARTIAL"
            if supported_count
            else "UNSUPPORTED"
        )
        return {
            "claims": claims,
            "proposed_answer": " ".join(claim["text"] for claim in claims),
            "support_status": status,
        }

    @staticmethod
    def _specialist_answer(payload: dict[str, Any]) -> dict[str, Any]:
        domain = Domain(payload["specialist"])
        evidence = payload["evidence"]
        deliberately_unsupported = payload["requirement_id"] == "RFP-021"
        supported = bool(evidence) and not deliberately_unsupported
        claim_text = (
            evidence[0]["text"]
            if supported
            else f"Available {domain.value} evidence does not establish this requirement."
        )
        return {
            "claims": [
                {
                    "claim_id": f"{domain.value}-claim-001",
                    "text": claim_text,
                    "evidence_ids": [evidence[0]["chunk_id"]] if supported else [],
                    "supported": supported,
                }
            ],
            "proposed_answer": claim_text,
            "support_status": "SUPPORTED" if supported else "UNSUPPORTED",
        }


class RehearsalRetrievalFactory:
    def __init__(
        self,
        embeddings: FakeEmbeddingResource,
        index: FakePineconeIndex,
    ) -> None:
        self._embeddings = embeddings
        self._index = index
        self.sessions: list[ProviderRetrievalSession] = []

    def __call__(self) -> ProviderRetrievalSession:
        session = build_provider_retrieval_session(
            openai_api_key="fake-openai-key",
            pinecone_api_key="fake-pinecone-key",
            enabled=True,
            openai_client_factory=lambda api_key: FakeEmbeddingClient(self._embeddings),
            index_factory=lambda: self._index,
        )
        self.sessions.append(session)
        return session


class RehearsalArchitectureExecutor:
    def __init__(
        self,
        architecture: ComparisonArchitecture,
        *,
        ledger: ProviderBudgetLedger,
        responses: FakeStructuredResponses,
        retrieval_factory: RehearsalRetrievalFactory,
    ) -> None:
        self.architecture = architecture
        self._ledger = ledger
        self._responses = responses
        self._retrieval_factory = retrieval_factory

    def execute(self, case: EvaluationCaseInput):
        execution_id = f"{case.case_id}:{self.architecture.value}"
        delegate = OpenAIStructuredGenerationGateway(
            api_key="fake-openai-key",
            enabled=True,
            client_factory=lambda api_key: SimpleNamespace(responses=self._responses),
        )
        gateway = self._ledger.gateway(execution_id, delegate)
        timer = _timer()
        if self.architecture is ComparisonArchitecture.SINGLE_GENERALIST:
            executor: ArchitectureExecutor = ProviderSingleGeneralistExecutor(
                generation_gateway=gateway,
                retrieval_session_factory=self._retrieval_factory,
                as_of=date(2026, 9, 14),
                timer=timer,
            )
        else:
            executor = ProviderOrchestratedExecutor(
                generation_gateway=gateway,
                retrieval_session_factory=self._retrieval_factory,
                timer=timer,
                event_clock=lambda: "fake-provider-rehearsal",
            )
        return executor.execute(case)


def _timer() -> Callable[[], float]:
    values = iter((0.0, 0.001))
    return lambda: next(values)


def build_step_4_g5_rehearsal() -> FakeProviderRehearsalReport:
    plan = load_repeat_trial_plan()
    ledger = ProviderBudgetLedger(plan.budget)
    embeddings = FakeEmbeddingResource()
    index = FakePineconeIndex()
    retrieval_factory = RehearsalRetrievalFactory(embeddings, index)
    responses = FakeStructuredResponses()
    executors = {
        architecture: RehearsalArchitectureExecutor(
            architecture,
            ledger=ledger,
            responses=responses,
            retrieval_factory=retrieval_factory,
        )
        for architecture in ComparisonArchitecture
    }
    runner = EvaluationRunner(
        executors,
        provider_call_counter=lambda: ledger.snapshot().attempted_calls,
    )
    artifact = runner.run(
        case_ids=list(EXPECTED_CASE_IDS),
        mode=EvaluationRunMode.FAKE_PROVIDER_REHEARSAL,
        run_id=REHEARSAL_RUN_ID,
        started_at=REHEARSAL_STARTED_AT,
        completed_at=REHEARSAL_COMPLETED_AT,
        random_seed=0,
    )
    return FakeProviderRehearsalReport(
        accounted_architecture_executions=len(artifact.records) + len(artifact.failures),
        failures_preserved_in_denominator=bool(artifact.failures),
        deliberately_injected_failure_keys=[
            "EVAL-007:single_generalist",
            "EVAL-008:orchestrated_peer_specialists",
        ],
        counters=FakeProviderCounters(
            generation=ledger.snapshot(),
            embedding_calls=len(embeddings.calls),
            pinecone_queries=len(index.queries),
        ),
        artifact=artifact,
    )


def serialize_fake_provider_rehearsal(
    report: FakeProviderRehearsalReport,
) -> tuple[str, str]:
    content = json.dumps(report.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def write_step_4_g5_rehearsal(
    output_path: Path = DEFAULT_REHEARSAL_OUTPUT_PATH,
    digest_path: Path = DEFAULT_REHEARSAL_DIGEST_PATH,
) -> tuple[str, str]:
    report = build_step_4_g5_rehearsal()
    content, digest = serialize_fake_provider_rehearsal(report)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    digest_path.write_text(digest + "\n", encoding="utf-8")
    return content, digest
