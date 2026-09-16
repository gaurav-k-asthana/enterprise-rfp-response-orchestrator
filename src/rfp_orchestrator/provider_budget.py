"""Thread-safe text-generation budget guard for provider evaluation runs."""

from __future__ import annotations

from collections import defaultdict
from threading import Lock
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

from rfp_orchestrator.evaluation_trials import TrialBudget
from rfp_orchestrator.openai_generation import (
    OpenAIStructuredGenerationGateway,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)

OutputT = TypeVar("OutputT", bound=BaseModel)


class ProviderBudgetExceededError(RuntimeError):
    """Raised before another call, or after an impossible usage receipt."""


class ProviderBudgetSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    attempted_calls: int = Field(ge=0)
    completed_calls: int = Field(ge=0)
    failed_calls: int = Field(ge=0)
    blocked_calls: int = Field(ge=0)
    total_input_tokens: int = Field(ge=0)
    total_output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    calls_by_execution: dict[str, int]
    halted: bool


class ProviderBudgetUsageSeed(BaseModel):
    """Reviewed usage from an earlier attempt that still consumes the same cap."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempted_calls: int = Field(ge=0)
    completed_calls: int = Field(ge=0)
    failed_calls: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    def model_post_init(self, __context: object, /) -> None:
        if self.attempted_calls != self.completed_calls + self.failed_calls:
            raise ValueError("carried-forward attempts must equal completed plus failed calls")


class ProviderBudgetLedger:
    """Count attempted calls, including failed attempts, under the approved envelope."""

    def __init__(
        self,
        budget: TrialBudget,
        *,
        initial_usage: ProviderBudgetUsageSeed | None = None,
    ) -> None:
        seed = initial_usage or ProviderBudgetUsageSeed(
            attempted_calls=0,
            completed_calls=0,
            failed_calls=0,
            input_tokens=0,
            output_tokens=0,
        )
        if (
            seed.attempted_calls > budget.max_provider_calls_total
            or seed.input_tokens > budget.max_total_input_tokens
            or seed.output_tokens > budget.max_total_output_tokens
        ):
            raise ValueError("carried-forward provider usage exceeds the approved budget")
        self._budget = budget
        self._attempted_calls = seed.attempted_calls
        self._completed_calls = seed.completed_calls
        self._failed_calls = seed.failed_calls
        self._blocked_calls = 0
        self._input_tokens = seed.input_tokens
        self._output_tokens = seed.output_tokens
        self._calls_by_execution: dict[str, int] = defaultdict(int)
        self._halted = False
        self._lock = Lock()

    @property
    def budget(self) -> TrialBudget:
        return self._budget

    def gateway(
        self,
        execution_id: str,
        delegate: OpenAIStructuredGenerationGateway,
    ) -> BudgetedGenerationGateway:
        if not execution_id.strip():
            raise ValueError("budget execution ID cannot be blank")
        return BudgetedGenerationGateway(self, execution_id, delegate)

    def reserve_call(self, execution_id: str) -> None:
        with self._lock:
            would_exceed = (
                self._halted
                or self._attempted_calls >= self._budget.max_provider_calls_total
                or self._calls_by_execution[execution_id]
                >= self._budget.max_provider_calls_per_architecture_execution
                or self._input_tokens + self._budget.max_input_tokens_per_provider_call
                > self._budget.max_total_input_tokens
                or self._output_tokens + self._budget.max_output_tokens_per_provider_call
                > self._budget.max_total_output_tokens
            )
            if would_exceed:
                self._blocked_calls += 1
                raise ProviderBudgetExceededError(
                    "provider generation budget blocked the next call"
                )
            self._attempted_calls += 1
            self._calls_by_execution[execution_id] += 1

    def record_failure(self) -> None:
        with self._lock:
            self._failed_calls += 1

    def record_success(self, result: StructuredGenerationResult) -> None:
        usage = result.usage
        with self._lock:
            if (
                usage.input_tokens > self._budget.max_input_tokens_per_provider_call
                or usage.output_tokens > self._budget.max_output_tokens_per_provider_call
                or self._input_tokens + usage.input_tokens > self._budget.max_total_input_tokens
                or self._output_tokens + usage.output_tokens > self._budget.max_total_output_tokens
            ):
                self._halted = True
                self._failed_calls += 1
                raise ProviderBudgetExceededError(
                    "provider usage exceeded the approved token envelope"
                )
            self._completed_calls += 1
            self._input_tokens += usage.input_tokens
            self._output_tokens += usage.output_tokens

    def snapshot(self) -> ProviderBudgetSnapshot:
        with self._lock:
            return ProviderBudgetSnapshot(
                attempted_calls=self._attempted_calls,
                completed_calls=self._completed_calls,
                failed_calls=self._failed_calls,
                blocked_calls=self._blocked_calls,
                total_input_tokens=self._input_tokens,
                total_output_tokens=self._output_tokens,
                total_tokens=self._input_tokens + self._output_tokens,
                calls_by_execution=dict(sorted(self._calls_by_execution.items())),
                halted=self._halted,
            )


class BudgetedGenerationGateway(Generic[OutputT]):
    """Delegate strict generation only after a ledger reservation succeeds."""

    def __init__(
        self,
        ledger: ProviderBudgetLedger,
        execution_id: str,
        delegate: OpenAIStructuredGenerationGateway,
    ) -> None:
        self._ledger = ledger
        self._execution_id = execution_id
        self._delegate = delegate

    def generate(
        self,
        request: StructuredGenerationRequest,
        *,
        output_model: type[OutputT],
    ) -> StructuredGenerationResult[OutputT]:
        self._ledger.reserve_call(self._execution_id)
        try:
            result = self._delegate.generate(request, output_model=output_model)
        except Exception:
            self._ledger.record_failure()
            raise
        self._ledger.record_success(result)
        return result
