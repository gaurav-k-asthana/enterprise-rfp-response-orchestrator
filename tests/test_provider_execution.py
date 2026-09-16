from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime

from rfp_orchestrator.config import Settings
from rfp_orchestrator.evaluation_runner import (
    EvaluationCaseInput,
    EvaluationRunRecord,
    build_step_4_11_dry_run,
)
from rfp_orchestrator.evaluation_trials import load_repeat_trial_plan
from rfp_orchestrator.fair_comparison import ComparisonArchitecture
from rfp_orchestrator.provider_budget import ProviderBudgetLedger
from rfp_orchestrator.provider_execution import (
    ProviderArchitectureExecutor,
    RunSpecification,
    execute_provider_runs,
)


class FakeArchitectureExecutor:
    def __init__(
        self,
        architecture: ComparisonArchitecture,
        template: EvaluationRunRecord,
    ) -> None:
        self.architecture = architecture
        self._template = template

    def execute(self, case: EvaluationCaseInput) -> EvaluationRunRecord:
        payload = deepcopy(self._template.model_dump(mode="python"))
        payload["case_id"] = case.case_id
        payload["requirement_id"] = case.requirement_id
        for call in payload["retrieval_calls"]:
            call["call_id"] = f"{case.case_id}:{self.architecture.value}:offline-test"
        return EvaluationRunRecord.model_validate(payload)


def test_three_run_provider_workflow_archives_all_64_executions_with_fakes(
    tmp_path,
) -> None:
    templates = {record.architecture: record for record in build_step_4_11_dry_run().records}
    factory_calls: list[tuple[ComparisonArchitecture, int]] = []

    def executor_factory(
        architecture,
        *,
        trial_number,
        ledger,
        settings,
        retrieval_session_factory,
    ):
        factory_calls.append((architecture, trial_number))
        return FakeArchitectureExecutor(architecture, templates[architecture])

    def never_retrieve():
        raise AssertionError("offline execution test cannot initialize provider retrieval")

    plan = load_repeat_trial_plan()
    receipt = execute_provider_runs(
        manifest_sha256="a" * 64,
        run_specifications=[
            RunSpecification(
                run_id="provider-primary-test",
                trial_number=1,
                case_ids=plan.primary_case_ids,
            ),
            RunSpecification(
                run_id="provider-repeat-2-test",
                trial_number=2,
                case_ids=[item.case_id for item in plan.repeat_cases],
            ),
            RunSpecification(
                run_id="provider-repeat-3-test",
                trial_number=3,
                case_ids=[item.case_id for item in plan.repeat_cases],
            ),
        ],
        budget=plan.budget,
        settings=Settings(_env_file=None),
        archive_root=tmp_path,
        clock=lambda: datetime.fromisoformat("2026-09-15T10:00:00-04:00"),
        retrieval_session_factory=never_retrieve,
        executor_factory=executor_factory,
    )

    assert receipt.total_architecture_executions == 64
    assert len(receipt.runs) == 3
    assert [item.architecture_execution_count for item in receipt.runs] == [48, 8, 8]
    assert [item.provider_calls_made for item in receipt.runs] == [0, 0, 0]
    assert receipt.generation_budget.attempted_calls == 0
    assert factory_calls == [
        (architecture, trial_number)
        for trial_number in (1, 2, 3)
        for architecture in ComparisonArchitecture
    ]
    assert all((tmp_path / item.run_id / "manifest.json").is_file() for item in receipt.runs)


def test_live_generalist_factory_supplies_the_frozen_as_of_date() -> None:
    plan = load_repeat_trial_plan()
    executor = ProviderArchitectureExecutor(
        ComparisonArchitecture.SINGLE_GENERALIST,
        trial_number=1,
        ledger=ProviderBudgetLedger(plan.budget),
        settings=Settings(_env_file=None, openai_api_key="test-key"),
        retrieval_session_factory=lambda: (_ for _ in ()).throw(
            AssertionError("immediate HITL cannot retrieve")
        ),
    )
    case = EvaluationCaseInput(
        case_id="EVAL-023",
        requirement_id="RFP-023",
        untrusted_rfp_text="Accept a 20% subscription discount and unlimited indemnity.",
    )

    record = executor.execute(case)

    assert record.case_id == "EVAL-023"
    assert record.final_status == "NEEDS_HUMAN"


def test_run_timestamps_bracket_execution_instead_of_preceding_it(tmp_path) -> None:
    templates = {record.architecture: record for record in build_step_4_11_dry_run().records}
    times = iter(
        datetime.fromisoformat(value)
        for value in (
            "2026-09-15T10:00:00-04:00",
            "2026-09-15T10:00:05-04:00",
            "2026-09-15T10:01:00-04:00",
            "2026-09-15T10:01:05-04:00",
            "2026-09-15T10:02:00-04:00",
            "2026-09-15T10:02:05-04:00",
        )
    )

    def executor_factory(architecture, **kwargs):
        return FakeArchitectureExecutor(architecture, templates[architecture])

    execute_provider_runs(
        manifest_sha256="b" * 64,
        run_specifications=[
            RunSpecification(run_id=f"timing-{number}", trial_number=number, case_ids=["EVAL-001"])
            for number in (1, 2, 3)
        ],
        budget=load_repeat_trial_plan().budget,
        settings=Settings(_env_file=None),
        archive_root=tmp_path,
        clock=lambda: next(times),
        retrieval_session_factory=lambda: (_ for _ in ()).throw(
            AssertionError("offline timing test cannot retrieve")
        ),
        executor_factory=executor_factory,
    )

    manifests = [
        json.loads((tmp_path / f"timing-{number}" / "manifest.json").read_text())
        for number in (1, 2, 3)
    ]
    assert [item["source_started_at"] for item in manifests] == [
        "2026-09-15T10:00:00-04:00",
        "2026-09-15T10:01:00-04:00",
        "2026-09-15T10:02:00-04:00",
    ]
    assert [item["source_completed_at"] for item in manifests] == [
        "2026-09-15T10:00:05-04:00",
        "2026-09-15T10:01:05-04:00",
        "2026-09-15T10:02:05-04:00",
    ]
