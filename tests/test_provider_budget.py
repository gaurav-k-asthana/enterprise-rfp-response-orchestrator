from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ConfigDict

from rfp_orchestrator.evaluation_trials import load_repeat_trial_plan
from rfp_orchestrator.openai_generation import (
    ProviderTokenUsage,
    StructuredGenerationRequest,
    StructuredGenerationResult,
)
from rfp_orchestrator.provider_budget import (
    ProviderBudgetExceededError,
    ProviderBudgetLedger,
    ProviderBudgetUsageSeed,
)
from rfp_orchestrator.provider_config import OPENAI_GENERATION_MODEL


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str


class FakeGateway:
    def __init__(
        self,
        *,
        usage: ProviderTokenUsage | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.usage = usage or ProviderTokenUsage(
            input_tokens=100,
            output_tokens=25,
            total_tokens=125,
        )
        self.failure = failure
        self.calls = 0

    def generate(
        self,
        request: StructuredGenerationRequest,
        *,
        output_model: type[BaseModel],
    ) -> StructuredGenerationResult[Any]:
        self.calls += 1
        if self.failure is not None:
            raise self.failure
        return StructuredGenerationResult(
            request_id=request.request_id,
            response_id=f"fake-{self.calls}",
            requested_model=OPENAI_GENERATION_MODEL,
            response_model=OPENAI_GENERATION_MODEL,
            usage=self.usage,
            output=Output(answer="supported"),
        )


def request(number: int) -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        request_id=f"budget-call-{number}",
        schema_name="budget_output",
        instructions="Return the test schema.",
        input_text="Synthetic test input.",
    )


def test_fourth_call_is_blocked_before_the_delegate() -> None:
    ledger = ProviderBudgetLedger(load_repeat_trial_plan().budget)
    delegate = FakeGateway()
    gateway = ledger.gateway("EVAL-001:single_generalist", delegate)  # type: ignore[arg-type]

    for number in range(1, 4):
        gateway.generate(request(number), output_model=Output)
    with pytest.raises(ProviderBudgetExceededError, match="blocked the next call"):
        gateway.generate(request(4), output_model=Output)

    snapshot = ledger.snapshot()
    assert delegate.calls == 3
    assert snapshot.attempted_calls == 3
    assert snapshot.completed_calls == 3
    assert snapshot.failed_calls == 0
    assert snapshot.blocked_calls == 1
    assert snapshot.calls_by_execution == {"EVAL-001:single_generalist": 3}


def test_failed_attempt_remains_counted_without_automatic_retry() -> None:
    ledger = ProviderBudgetLedger(load_repeat_trial_plan().budget)
    delegate = FakeGateway(failure=RuntimeError("secret provider detail"))
    gateway = ledger.gateway("EVAL-007:single_generalist", delegate)  # type: ignore[arg-type]

    with pytest.raises(RuntimeError, match="secret provider detail"):
        gateway.generate(request(1), output_model=Output)

    snapshot = ledger.snapshot()
    assert delegate.calls == 1
    assert snapshot.attempted_calls == 1
    assert snapshot.completed_calls == 0
    assert snapshot.failed_calls == 1
    assert snapshot.blocked_calls == 0


def test_oversized_receipt_halts_future_calls() -> None:
    budget = load_repeat_trial_plan().budget
    ledger = ProviderBudgetLedger(budget)
    delegate = FakeGateway(
        usage=ProviderTokenUsage(
            input_tokens=budget.max_input_tokens_per_provider_call + 1,
            output_tokens=1,
            total_tokens=budget.max_input_tokens_per_provider_call + 2,
        )
    )
    gateway = ledger.gateway("EVAL-001:single_generalist", delegate)  # type: ignore[arg-type]

    with pytest.raises(ProviderBudgetExceededError, match="exceeded"):
        gateway.generate(request(1), output_model=Output)
    with pytest.raises(ProviderBudgetExceededError, match="blocked"):
        gateway.generate(request(2), output_model=Output)

    snapshot = ledger.snapshot()
    assert delegate.calls == 1
    assert snapshot.halted is True
    assert snapshot.attempted_calls == 1
    assert snapshot.failed_calls == 1
    assert snapshot.blocked_calls == 1
    assert snapshot.total_tokens == 0


def test_total_call_ceiling_blocks_call_129_before_the_delegate() -> None:
    budget = load_repeat_trial_plan().budget
    ledger = ProviderBudgetLedger(budget)
    delegate = FakeGateway()

    for number in range(1, budget.max_provider_calls_total + 1):
        ledger.gateway(f"execution-{number}", delegate).generate(  # type: ignore[arg-type]
            request(number),
            output_model=Output,
        )
    with pytest.raises(ProviderBudgetExceededError, match="blocked the next call"):
        ledger.gateway("execution-129", delegate).generate(  # type: ignore[arg-type]
            request(129),
            output_model=Output,
        )

    snapshot = ledger.snapshot()
    assert delegate.calls == budget.max_provider_calls_total
    assert snapshot.attempted_calls == budget.max_provider_calls_total
    assert snapshot.completed_calls == budget.max_provider_calls_total
    assert snapshot.blocked_calls == 1


def test_reviewed_usage_seed_consumes_the_original_shared_budget() -> None:
    budget = load_repeat_trial_plan().budget
    ledger = ProviderBudgetLedger(
        budget,
        initial_usage=ProviderBudgetUsageSeed(
            attempted_calls=36,
            completed_calls=36,
            failed_calls=0,
            input_tokens=57_403,
            output_tokens=11_971,
        ),
    )
    delegate = FakeGateway()

    ledger.gateway("recovery-v2", delegate).generate(  # type: ignore[arg-type]
        request(37), output_model=Output
    )

    snapshot = ledger.snapshot()
    assert snapshot.attempted_calls == 37
    assert snapshot.completed_calls == 37
    assert snapshot.total_input_tokens == 57_503
    assert snapshot.total_output_tokens == 11_996
    assert snapshot.calls_by_execution == {"recovery-v2": 1}


def test_invalid_reviewed_usage_seed_is_rejected() -> None:
    with pytest.raises(ValueError, match="attempts must equal"):
        ProviderBudgetUsageSeed(
            attempted_calls=36,
            completed_calls=35,
            failed_calls=0,
            input_tokens=57_403,
            output_tokens=11_971,
        )
