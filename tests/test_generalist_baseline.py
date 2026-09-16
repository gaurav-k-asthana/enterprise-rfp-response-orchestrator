from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.generalist_baseline import (
    GENERALIST_SYSTEM_PROMPT,
    GENERALIST_TOOL_SPECS,
    GeneralistBaselineResult,
    GeneralistDraft,
    GeneralistReasoningRequest,
    GeneralistToolName,
    GeneralistToolSession,
    SingleGeneralistBaseline,
    render_generalist_baseline_contract,
)
from rfp_orchestrator.models import Claim, Domain, Requirement, SupportStatus
from rfp_orchestrator.requirement_classification import analyze_requirement_input
from rfp_orchestrator.retrieval import RetrievalMethod, build_offline_retrievers

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"
CONTRACT_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "generalist_baseline_contract_v1.md"
)


def analyzed(requirement_id: str, text: str) -> Requirement:
    return analyze_requirement_input(
        Requirement(requirement_id=requirement_id, original_text=text)
    )


def tool_session() -> GeneralistToolSession:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    return GeneralistToolSession(
        {
            Domain.PRODUCT: retrievers.product,
            Domain.SECURITY: retrievers.security,
            Domain.IMPLEMENTATION: retrievers.implementation,
        }
    )


class CrossDomainReasoner:
    def __init__(self) -> None:
        self.invocations = 0
        self.request: GeneralistReasoningRequest | None = None

    def respond(
        self,
        request: GeneralistReasoningRequest,
        tools: GeneralistToolSession,
    ) -> GeneralistDraft:
        self.invocations += 1
        self.request = request
        product = tools.call(
            GeneralistToolName.PRODUCT,
            "customer-managed encryption keys deployment environments",
        )
        security = tools.call(
            GeneralistToolName.SECURITY,
            "customer-managed encryption keys deployment environments",
        )
        claims = [
            Claim(
                claim_id="generalist-claim-001",
                text="Product evidence limits customer-managed keys to AWS Enterprise Cloud.",
                evidence_ids=[product[0].chunk_id],
                supported=True,
            ),
            Claim(
                claim_id="generalist-claim-002",
                text="Security evidence applies the same AWS Enterprise Cloud boundary.",
                evidence_ids=[security[0].chunk_id],
                supported=True,
            ),
        ]
        return GeneralistDraft(
            claims=claims,
            proposed_answer=(
                "Customer-managed keys are documented for AWS-hosted Enterprise Cloud; "
                "the deployment boundary should be preserved."
            ),
            support_status=SupportStatus.SUPPORTED,
        )


def test_tool_contract_exposes_exactly_three_domain_retrieval_tools() -> None:
    assert [spec.name for spec in GENERALIST_TOOL_SPECS] == list(GeneralistToolName)
    assert [spec.domain for spec in GENERALIST_TOOL_SPECS] == list(Domain)
    assert all(spec.maximum_results == 5 for spec in GENERALIST_TOOL_SPECS)
    assert "hybrid" in GENERALIST_TOOL_SPECS[0].retrieval_policy
    assert "hybrid" in GENERALIST_TOOL_SPECS[1].retrieval_policy
    assert GENERALIST_TOOL_SPECS[2].retrieval_policy == "dense semantic, Top 5"


@pytest.mark.parametrize(
    ("tool_name", "query", "expected_method"),
    [
        (GeneralistToolName.PRODUCT, "SAML SCIM", RetrievalMethod.HYBRID),
        (GeneralistToolName.SECURITY, "TLS AES-256", RetrievalMethod.HYBRID),
        (
            GeneralistToolName.IMPLEMENTATION,
            "implementation timeline prerequisites",
            RetrievalMethod.SEMANTIC_SUBSTITUTE,
        ),
    ],
)
def test_each_generalist_tool_uses_the_same_domain_locked_offline_retriever(
    tool_name: GeneralistToolName,
    query: str,
    expected_method: RetrievalMethod,
) -> None:
    session = tool_session()

    evidence = session.call(tool_name, query)

    assert 0 < len(evidence) <= 5
    assert all(item.domain is dict(zip(GeneralistToolName, Domain))[tool_name] for item in evidence)
    assert all(item.retrieval_method is expected_method for item in evidence)
    assert session.calls[0].evidence == evidence


def test_one_reasoner_can_combine_multiple_tools_without_specialist_branches() -> None:
    reasoner = CrossDomainReasoner()
    baseline = SingleGeneralistBaseline.from_offline_retrievers(
        build_offline_retrievers(KB_DIRECTORY),
        reasoner=reasoner,
    )
    requirement = analyzed(
        "RFP-002",
        "Describe customer-managed encryption keys and supported deployment environments.",
    )

    result = baseline.run(requirement)

    assert reasoner.invocations == 1
    assert result.architecture == "single_generalist"
    assert [call.domain for call in result.tool_calls] == [
        Domain.PRODUCT,
        Domain.SECURITY,
    ]
    assert result.support_status is SupportStatus.SUPPORTED
    assert result.proposed_answer
    assert not hasattr(result, "specialist_outputs")


def test_reasoning_request_contains_no_gold_or_expected_labels() -> None:
    reasoner = CrossDomainReasoner()
    baseline = SingleGeneralistBaseline.from_offline_retrievers(
        build_offline_retrievers(KB_DIRECTORY),
        reasoner=reasoner,
    )
    baseline.run(
        analyzed(
            "RFP-002",
            "Describe customer-managed encryption keys and supported deployment environments.",
        )
    )

    payload = reasoner.request.model_dump(mode="json")
    assert set(payload) == {
        "architecture",
        "agent_role",
        "requirement_id",
        "untrusted_rfp_text",
        "atomic_requirements",
        "available_tools",
        "system_prompt",
    }
    exposed_data = {
        key: value for key, value in payload.items() if key != "system_prompt"
    }
    serialized_data = str(exposed_data).lower()
    assert "gold_labels" not in serialized_data
    assert "expected_domains" not in serialized_data
    assert "expected_answer" not in serialized_data


def test_result_rejects_a_citation_not_returned_by_an_actual_tool() -> None:
    with pytest.raises(ValidationError, match="not returned by its tools"):
        GeneralistBaselineResult(
            requirement_id="RFP-X",
            tool_calls=[],
            claims=[
                Claim(
                    claim_id="generalist-claim-001",
                    text="An invented claim.",
                    evidence_ids=["INVENTED::chunk-001"],
                    supported=True,
                )
            ],
            proposed_answer="An invented answer.",
            support_status=SupportStatus.SUPPORTED,
        )


def test_baseline_requires_analyzed_atomic_requirements() -> None:
    baseline = SingleGeneralistBaseline.from_offline_retrievers(
        build_offline_retrievers(KB_DIRECTORY),
        reasoner=CrossDomainReasoner(),
    )

    with pytest.raises(ValueError, match="analyzed atomic requirements"):
        baseline.run(
            Requirement(
                requirement_id="RFP-X",
                original_text="Describe SAML support.",
            )
        )


def test_tool_session_closes_after_the_single_reasoner_returns() -> None:
    retained_session: GeneralistToolSession | None = None

    class RetainingReasoner(CrossDomainReasoner):
        def respond(
            self,
            request: GeneralistReasoningRequest,
            tools: GeneralistToolSession,
        ) -> GeneralistDraft:
            nonlocal retained_session
            retained_session = tools
            return super().respond(request, tools)

    baseline = SingleGeneralistBaseline.from_offline_retrievers(
        build_offline_retrievers(KB_DIRECTORY),
        reasoner=RetainingReasoner(),
    )
    baseline.run(
        analyzed(
            "RFP-002",
            "Describe customer-managed encryption keys and supported deployment environments.",
        )
    )

    assert retained_session is not None
    with pytest.raises(RuntimeError, match="session is closed"):
        retained_session.call(GeneralistToolName.PRODUCT, "SAML")


def test_prompt_and_checked_in_contract_freeze_the_step_4_8_boundary() -> None:
    prompt = GENERALIST_SYSTEM_PROMPT.lower()
    assert "untrusted data" in prompt
    assert "do not delegate" in prompt
    assert "three evidence-search tools" in prompt
    assert "never use evaluation gold labels" in prompt
    assert CONTRACT_PATH.read_text(encoding="utf-8") == render_generalist_baseline_contract()
