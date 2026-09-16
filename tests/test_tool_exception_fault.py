from pathlib import Path

import pytest

from rfp_orchestrator.fault_injection import (
    InjectedToolException,
    ToolExceptionFault,
    ToolExceptionFaultRetriever,
)
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.models import Domain
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


def test_fault_is_inert_until_explicitly_wrapped() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = ToolExceptionFault(target_domain=Domain.PRODUCT)

    assert retrievers.product.search("SAML 2.0", k=5)
    assert fault.invocation_count == 0
    assert fault.receipts == ()


def test_selected_call_raises_fixed_exception_and_writes_safe_receipt() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = ToolExceptionFault(target_domain=Domain.SECURITY)
    faulted = fault.wrap(retrievers)

    with pytest.raises(
        InjectedToolException, match=r"Controlled retrieval tool failure \(test only\)"
    ) as raised:
        faulted.security.search("sensitive customer query about SOC 2", k=5)

    assert "sensitive customer query" not in str(raised.value)
    assert fault.invocation_count == 1
    assert len(fault.receipts) == 1
    assert fault.receipts[0].fault_type == "tool_exception"
    assert fault.receipts[0].domain is Domain.SECURITY
    assert fault.receipts[0].invocation_number == 1
    assert fault.receipts[0].requested_top_k == 5
    assert fault.receipts[0].error_code == "INJECTED_RETRIEVAL_TOOL_EXCEPTION"
    assert "sensitive customer query" not in repr(fault.receipts)


def test_only_selected_domain_is_wrapped_and_original_bundle_is_unmodified() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = ToolExceptionFault(target_domain=Domain.SECURITY)
    faulted = fault.wrap(retrievers)

    assert isinstance(faulted.security, ToolExceptionFaultRetriever)
    assert faulted.product is retrievers.product
    assert faulted.implementation is retrievers.implementation
    assert retrievers.security.search("SOC 2", k=5)
    assert faulted.product.search("SAML 2.0", k=5)
    assert faulted.implementation.search("implementation prerequisites", k=5)
    assert fault.invocation_count == 0


def test_fault_is_repeatable_and_can_fail_only_selected_invocations() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = ToolExceptionFault(target_domain=Domain.PRODUCT, fail_on_calls=(1, 3))
    faulted = fault.wrap(retrievers)

    with pytest.raises(InjectedToolException):
        faulted.product.search("SAML 2.0")
    assert faulted.product.search("SAML 2.0")
    with pytest.raises(InjectedToolException):
        faulted.product.search("SAML 2.0")

    assert fault.invocation_count == 3
    assert [receipt.invocation_number for receipt in fault.receipts] == [1, 3]


def test_invalid_query_or_top_k_cannot_trigger_fault() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = ToolExceptionFault(target_domain=Domain.PRODUCT)
    faulted = fault.wrap(retrievers)

    with pytest.raises(ValueError, match="searchable token"):
        faulted.product.search("---", k=5)
    with pytest.raises(ValueError, match="between 1 and 5"):
        faulted.product.search("SAML", k=6)

    assert fault.invocation_count == 0
    assert fault.receipts == ()


@pytest.mark.parametrize("calls", [(), (0,), (-1,), (True,), (1, 1), [1]])
def test_invalid_failure_schedule_is_rejected(calls) -> None:
    with pytest.raises(ValueError, match="distinct positive call numbers"):
        ToolExceptionFault(target_domain=Domain.PRODUCT, fail_on_calls=calls)


def test_invalid_domain_is_rejected() -> None:
    with pytest.raises(TypeError, match="must be a Domain"):
        ToolExceptionFault(target_domain="product")  # type: ignore[arg-type]


def test_graph_emits_blocked_event_and_propagates_tool_error_without_finalizing() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = ToolExceptionFault(target_domain=Domain.PRODUCT)
    graph = build_selected_fanout_graph(
        fault.wrap(retrievers), event_clock=lambda: "fixed"
    )
    events: list[dict] = []

    with pytest.raises(InjectedToolException):
        events.extend(
            graph.stream(
                new_requirement_state(
                    "fault-case-2",
                    "RFP-001",
                    "Confirm support for SAML 2.0 and SCIM 2.0.",
                ),
                stream_mode="custom",
            )
        )

    assert fault.invocation_count == 1
    assert [item["status"] for item in events if item["node"] == GraphNode.PRODUCT_SPECIALIST.value] == [
        "active",
        "blocked",
    ]
    assert events[-1]["detail"] == "product_specialist failed: InjectedToolException"
    assert not any(item["node"] == GraphNode.FINALIZATION_GUARD.value for item in events)
    assert not any(item["node"] == GraphNode.RECOVERY_ATTEMPT.value for item in events)
