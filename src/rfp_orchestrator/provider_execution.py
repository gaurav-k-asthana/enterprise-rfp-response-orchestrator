"""Manifest-gated provider comparison engine used only by the approved CLI."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from rfp_orchestrator.config import Settings
from rfp_orchestrator.evaluation_archive import (
    DEFAULT_RAW_ARCHIVE_ROOT,
    archive_evaluation_run,
)
from rfp_orchestrator.evaluation_runner import (
    ArchitectureExecutor,
    EvaluationCaseInput,
    EvaluationRunArtifact,
    EvaluationRunMode,
    EvaluationRunner,
)
from rfp_orchestrator.evaluation_trials import TrialBudget
from rfp_orchestrator.fair_comparison import ComparisonArchitecture
from rfp_orchestrator.openai_generation import OpenAIStructuredGenerationGateway
from rfp_orchestrator.provider_budget import (
    ProviderBudgetLedger,
    ProviderBudgetSnapshot,
    ProviderBudgetUsageSeed,
)
from rfp_orchestrator.provider_generalist import ProviderSingleGeneralistExecutor
from rfp_orchestrator.provider_orchestrated import ProviderOrchestratedExecutor
from rfp_orchestrator.provider_retrieval import (
    ProviderRetrievalSession,
    build_provider_retrieval_session,
)


class ProviderExecutionError(RuntimeError):
    """Raised when a paid comparison cannot remain inside its reviewed scope."""


PROVIDER_EXECUTION_AS_OF = date(2026, 9, 15)


class RunSpecification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(min_length=1)
    trial_number: int = Field(ge=1, le=3)
    case_ids: list[str] = Field(min_length=1)


class ArchivedProviderRun(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str
    trial_number: int
    case_count: int
    architecture_execution_count: int
    provider_calls_made: int
    status: str
    archive_path: str
    archive_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProviderExecutionReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    runs: list[ArchivedProviderRun] = Field(min_length=3, max_length=3)
    generation_budget: ProviderBudgetSnapshot
    total_architecture_executions: int
    automatic_provider_retries_used: int = 0


class RetrievalSessionFactory(Protocol):
    def __call__(self) -> ProviderRetrievalSession: ...


class ArchitectureExecutorFactory(Protocol):
    def __call__(
        self,
        architecture: ComparisonArchitecture,
        *,
        trial_number: int,
        ledger: ProviderBudgetLedger,
        settings: Settings,
        retrieval_session_factory: RetrievalSessionFactory,
    ) -> ArchitectureExecutor: ...


class ProviderArchitectureExecutor:
    """Create fresh provider sessions for one architecture execution."""

    def __init__(
        self,
        architecture: ComparisonArchitecture,
        *,
        trial_number: int,
        ledger: ProviderBudgetLedger,
        settings: Settings,
        retrieval_session_factory: RetrievalSessionFactory,
    ) -> None:
        self.architecture = architecture
        self._trial_number = trial_number
        self._ledger = ledger
        self._settings = settings
        self._retrieval_session_factory = retrieval_session_factory

    def execute(self, case: EvaluationCaseInput):
        execution_id = f"trial-{self._trial_number}:{case.case_id}:{self.architecture.value}"
        delegate = OpenAIStructuredGenerationGateway(
            api_key=self._settings.openai_api_key,
            enabled=True,
        )
        gateway = self._ledger.gateway(execution_id, delegate)
        if self.architecture is ComparisonArchitecture.SINGLE_GENERALIST:
            executor: ArchitectureExecutor = ProviderSingleGeneralistExecutor(
                generation_gateway=gateway,  # type: ignore[arg-type]
                retrieval_session_factory=self._retrieval_session_factory,
                as_of=PROVIDER_EXECUTION_AS_OF,
            )
        else:
            executor = ProviderOrchestratedExecutor(
                generation_gateway=gateway,  # type: ignore[arg-type]
                retrieval_session_factory=self._retrieval_session_factory,
            )
        return executor.execute(case)


def build_provider_architecture_executor(
    architecture: ComparisonArchitecture,
    *,
    trial_number: int,
    ledger: ProviderBudgetLedger,
    settings: Settings,
    retrieval_session_factory: RetrievalSessionFactory,
) -> ArchitectureExecutor:
    return ProviderArchitectureExecutor(
        architecture,
        trial_number=trial_number,
        ledger=ledger,
        settings=settings,
        retrieval_session_factory=retrieval_session_factory,
    )


def build_live_retrieval_factory(settings: Settings) -> RetrievalSessionFactory:
    openai_key = settings.openai_api_key or ""
    pinecone_key = settings.pinecone_api_key or ""

    def factory() -> ProviderRetrievalSession:
        return build_provider_retrieval_session(
            openai_api_key=openai_key,
            pinecone_api_key=pinecone_key,
            enabled=True,
        )

    return factory


def _timestamp(clock: Callable[[], datetime]) -> str:
    value = clock()
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderExecutionError("provider execution clock must be timezone-aware")
    return value.isoformat(timespec="seconds")


def execute_provider_runs(
    *,
    manifest_sha256: str,
    run_specifications: Sequence[RunSpecification],
    budget: TrialBudget,
    settings: Settings,
    archive_root: Path = DEFAULT_RAW_ARCHIVE_ROOT,
    clock: Callable[[], datetime] = lambda: datetime.now().astimezone(),
    retrieval_session_factory: RetrievalSessionFactory | None = None,
    executor_factory: ArchitectureExecutorFactory = build_provider_architecture_executor,
    initial_budget_usage: ProviderBudgetUsageSeed | None = None,
) -> ProviderExecutionReceipt:
    """Execute only the manifest-supplied run list and archive every raw result."""

    if len(run_specifications) != 3:
        raise ProviderExecutionError("provider comparison requires exactly three runs")
    ledger = ProviderBudgetLedger(budget, initial_usage=initial_budget_usage)
    retrieval_factory = retrieval_session_factory or build_live_retrieval_factory(settings)
    archived: list[ArchivedProviderRun] = []

    for specification in run_specifications:
        executors = {
            architecture: executor_factory(
                architecture,
                trial_number=specification.trial_number,
                ledger=ledger,
                settings=settings,
                retrieval_session_factory=retrieval_factory,
            )
            for architecture in ComparisonArchitecture
        }
        runner = EvaluationRunner(
            executors,
            provider_call_counter=lambda: ledger.snapshot().attempted_calls,
        )
        started_at = _timestamp(clock)
        artifact: EvaluationRunArtifact = runner.run(
            case_ids=specification.case_ids,
            mode=EvaluationRunMode.PROVIDER_COMPARISON,
            run_id=specification.run_id,
            started_at=started_at,
            completed_at=started_at,
            random_seed=0,
            provider_execution_authorized=True,
        )
        artifact = EvaluationRunArtifact.model_validate(
            {
                **artifact.model_dump(mode="python"),
                "completed_at": _timestamp(clock),
            }
        )
        target, _, archive_digest = archive_evaluation_run(
            artifact,
            archive_root=archive_root,
        )
        archived.append(
            ArchivedProviderRun(
                run_id=artifact.run_id,
                trial_number=specification.trial_number,
                case_count=len(artifact.case_ids),
                architecture_execution_count=len(artifact.case_ids) * 2,
                provider_calls_made=artifact.provider_calls_made,
                status=artifact.status.value,
                archive_path=target.relative_to(archive_root.parent.parent).as_posix(),
                archive_manifest_sha256=archive_digest,
            )
        )

    snapshot = ledger.snapshot()
    return ProviderExecutionReceipt(
        manifest_sha256=manifest_sha256,
        runs=archived,
        generation_budget=snapshot,
        total_architecture_executions=sum(item.architecture_execution_count for item in archived),
    )
