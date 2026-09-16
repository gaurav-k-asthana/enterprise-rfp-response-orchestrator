from __future__ import annotations

import json
from datetime import date
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from rfp_orchestrator.evaluation_runner import EvaluationCaseInput
from rfp_orchestrator.generalist_baseline import GENERALIST_SYSTEM_PROMPT
from rfp_orchestrator.models import Domain, RequirementStatus, RiskClass, SupportStatus
from rfp_orchestrator.openai_generation import (
    OpenAIGenerationCallError,
    OpenAIStructuredGenerationGateway,
)
from rfp_orchestrator.provider_generalist import (
    ProviderGeneralistAnswer,
    ProviderGeneralistClaim,
    ProviderGeneralistRetrievalPlan,
    ProviderGeneralistToolIntent,
    ProviderSingleGeneralistExecutor,
)
from rfp_orchestrator.retrieval import (
    EvidenceChunk,
    HybridScoreComponents,
    RetrievalMethod,
)


class FakeResponses:
    def __init__(self, results: list[object | Exception]) -> None:
        self.results = list(results)
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakeOpenAI:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


class FakeRetriever:
    def __init__(self, domain: Domain, evidence: list[EvidenceChunk]) -> None:
        self.domain = domain
        self.evidence = evidence
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, *, k: int = 5, filters=None) -> list[EvidenceChunk]:
        self.calls.append((query, k))
        return self.evidence[:k]


class FakeProviderSession:
    def __init__(self) -> None:
        self.retrievers = {
            domain: FakeRetriever(domain, [evidence(domain)]) for domain in Domain
        }
        self.closed = False

    @property
    def domain_retrievers(self):
        return self.retrievers

    def close(self) -> None:
        self.closed = True


class SessionFactory:
    def __init__(self) -> None:
        self.sessions: list[FakeProviderSession] = []

    def __call__(self) -> FakeProviderSession:
        session = FakeProviderSession()
        self.sessions.append(session)
        return session


def evidence(domain: Domain) -> EvidenceChunk:
    method = (
        RetrievalMethod.HYBRID
        if domain in {Domain.PRODUCT, Domain.SECURITY}
        else RetrievalMethod.DENSE
    )
    return EvidenceChunk(
        chunk_id=f"{domain.value}-evidence-001",
        doc_id=f"{domain.value}-doc",
        domain=domain,
        title=f"{domain.value.title()} evidence",
        text=f"Current Northstar {domain.value} evidence.",
        version="1.0",
        effective_date="2026-01-01",
        authority_rank=5,
        source_status="current",
        score=0.9,
        retrieval_method=method,
        score_components=(
            HybridScoreComponents(
                lexical_weight=0.6,
                semantic_weight=0.4,
                provider_combined_score=0.9,
                visibility="combined_only",
            )
            if method is RetrievalMethod.HYBRID
            else None
        ),
    )


def provider_response(output: dict, *, number: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"resp_fake_{number}",
        status="completed",
        model="gpt-5.6-terra-2026-08-01",
        output_text=json.dumps(output),
        usage=SimpleNamespace(
            input_tokens=100 * number,
            output_tokens=20 * number,
            total_tokens=120 * number,
        ),
    )


def successful_responses(*, supported: bool = True) -> FakeResponses:
    citation_ids = ["product-evidence-001"] if supported else []
    return FakeResponses(
        [
            provider_response(
                {
                    "calls": [
                        {
                            "tool_name": "search_product_evidence",
                            "query": "Northstar product capability",
                            "requested_k": 5,
                        }
                    ]
                },
                number=1,
            ),
            provider_response(
                {
                    "claims": [
                        {
                            "claim_id": "claim-001",
                            "text": "Northstar supports the requested capability.",
                            "evidence_ids": citation_ids,
                            "supported": supported,
                        }
                    ],
                    "proposed_answer": (
                        "Northstar supports the requested capability."
                        if supported
                        else "Yes, Northstar supports the requested capability."
                    ),
                    "support_status": "SUPPORTED" if supported else "UNSUPPORTED",
                },
                number=2,
            ),
        ]
    )


def executor(
    responses: FakeResponses,
    sessions: SessionFactory,
    *,
    timer_values: list[float] | None = None,
) -> ProviderSingleGeneralistExecutor:
    values = iter(timer_values or [10.0, 10.125])
    return ProviderSingleGeneralistExecutor(
        generation_gateway=OpenAIStructuredGenerationGateway(
            api_key="test-key",
            enabled=True,
            client_factory=lambda api_key: FakeOpenAI(responses),
        ),
        retrieval_session_factory=sessions,
        as_of=date(2026, 9, 14),
        timer=lambda: next(values),
    )


def case(text: str = "Describe the supported product capability.") -> EvaluationCaseInput:
    return EvaluationCaseInput(
        case_id="EVAL-001",
        requirement_id="RFP-001",
        untrusted_rfp_text=text,
    )


def test_provider_executor_returns_the_frozen_normalized_record() -> None:
    responses = successful_responses()
    sessions = SessionFactory()

    record = executor(responses, sessions).execute(case())

    assert record.architecture.value == "single_generalist"
    assert record.consulted_domains == [Domain.PRODUCT]
    assert record.retrieval_calls[0].requested_k == 5
    assert record.retrieval_calls[0].retrieval_methods == ["hybrid"]
    assert record.retrieval_calls[0].result_ids == ["product-evidence-001"]
    assert record.support_status is SupportStatus.SUPPORTED
    assert record.citation_valid is True
    assert record.source_metadata_valid is True
    assert record.authority_required is False
    assert record.final_status is RequirementStatus.FINALIZED
    assert record.final_answer == record.proposed_answer
    assert record.model_usage.provider_calls == 2
    assert record.model_usage.input_tokens == 300
    assert record.model_usage.output_tokens == 60
    assert record.model_usage.total_tokens == 360
    assert record.latency_ms == pytest.approx(125.0)
    assert sessions.sessions[0].closed is True


def test_same_generalist_prompt_drives_plan_and_answer_without_gold() -> None:
    responses = successful_responses()
    sessions = SessionFactory()

    executor(responses, sessions).execute(case())

    assert len(responses.calls) == 2
    assert all(call["instructions"] == GENERALIST_SYSTEM_PROMPT for call in responses.calls)
    assert [call["metadata"]["request_id"] for call in responses.calls] == [
        "EVAL-001-generalist-plan",
        "EVAL-001-generalist-answer",
    ]
    plan_input = json.loads(responses.calls[0]["input"])
    answer_input = json.loads(responses.calls[1]["input"])
    assert set(plan_input) == {
        "atomic_requirements",
        "available_tools",
        "requirement_id",
        "task",
        "untrusted_rfp_text",
    }
    assert "retrieval_calls" in answer_input
    assert "gold" not in json.dumps([plan_input, answer_input]).lower()
    assert "expected_answer" not in json.dumps([plan_input, answer_input]).lower()


def test_generalist_plan_can_select_multiple_peer_neutral_tools() -> None:
    responses = successful_responses()
    plan = json.loads(responses.results[0].output_text)
    plan["calls"].append(
        {
            "tool_name": "search_security_compliance_evidence",
            "query": "Northstar security controls",
            "requested_k": 5,
        }
    )
    responses.results[0].output_text = json.dumps(plan)
    answer = json.loads(responses.results[1].output_text)
    answer["claims"][0]["evidence_ids"].append("security-evidence-001")
    responses.results[1].output_text = json.dumps(answer)
    sessions = SessionFactory()

    record = executor(responses, sessions).execute(case("Describe product and security."))

    assert record.consulted_domains == [Domain.PRODUCT, Domain.SECURITY]
    assert [call.tool_name for call in record.retrieval_calls] == [
        "search_product_evidence",
        "search_security_compliance_evidence",
    ]
    assert all(retriever.calls for retriever in list(sessions.sessions[0].retrievers.values())[:2])


def test_immediate_preflight_human_review_makes_no_provider_or_session_call() -> None:
    responses = successful_responses()
    sessions = SessionFactory()

    record = executor(responses, sessions).execute(
        case("Accept a 25% discount and unlimited indemnity.")
    )

    assert record.final_status is RequirementStatus.NEEDS_HUMAN
    assert record.awaiting_human_review is True
    assert record.authority_required is True
    assert record.model_usage.provider_calls == 0
    assert RiskClass.PRICING_OR_DISCOUNT in record.risk_classes
    assert sessions.sessions == []
    assert responses.calls == []


def test_shared_post_evidence_gate_escalates_unsupported_affirmative_answer() -> None:
    responses = successful_responses(supported=False)
    sessions = SessionFactory()

    record = executor(responses, sessions).execute(case())

    assert record.support_status is SupportStatus.UNSUPPORTED
    assert record.final_status is RequirementStatus.NEEDS_HUMAN
    assert record.final_answer is None
    assert record.risk_classes == [RiskClass.UNSUPPORTED_CATEGORICAL_YES]
    assert sessions.sessions[0].closed is True


def test_provider_failure_is_redacted_and_always_closes_retrieval_session() -> None:
    responses = successful_responses()
    responses.results[1] = RuntimeError("secret provider payload")
    sessions = SessionFactory()

    with pytest.raises(OpenAIGenerationCallError) as captured:
        executor(responses, sessions).execute(case())

    assert "secret provider payload" not in str(captured.value)
    assert "redacted" in str(captured.value)
    assert sessions.sessions[0].closed is True


def test_provider_output_contracts_reject_duplicate_tools_and_bad_support() -> None:
    with pytest.raises(ValidationError, match="cannot repeat"):
        ProviderGeneralistRetrievalPlan(
            calls=[
                ProviderGeneralistToolIntent(
                    tool_name="search_product_evidence",
                    query="one",
                    requested_k=5,
                ),
                ProviderGeneralistToolIntent(
                    tool_name="search_product_evidence",
                    query="two",
                    requested_k=5,
                ),
            ]
        )
    with pytest.raises(ValidationError, match="require citations"):
        ProviderGeneralistClaim(
            claim_id="claim-001",
            text="Claim",
            evidence_ids=[],
            supported=True,
        )
    with pytest.raises(ValidationError, match="aggregate"):
        ProviderGeneralistAnswer(
            claims=[
                ProviderGeneralistClaim(
                    claim_id="claim-001",
                    text="Claim",
                    evidence_ids=["evidence-001"],
                    supported=True,
                )
            ],
            proposed_answer="Answer",
            support_status=SupportStatus.UNSUPPORTED,
        )


def test_strict_provider_schemas_forbid_extra_fields_recursively() -> None:
    for schema in (
        ProviderGeneralistRetrievalPlan.model_json_schema(),
        ProviderGeneralistAnswer.model_json_schema(),
    ):
        assert schema["additionalProperties"] is False
        object_definitions = [
            definition
            for definition in schema.get("$defs", {}).values()
            if definition.get("type") == "object"
        ]
        assert object_definitions
        assert all(
            definition.get("additionalProperties") is False
            for definition in object_definitions
        )
        for definition in [schema, *object_definitions]:
            assert set(definition.get("required", [])) == set(
                definition.get("properties", {})
            )
