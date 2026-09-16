from pathlib import Path

import pytest

from rfp_orchestrator.fault_injection import (
    EmptyRetrievalFault,
    EmptyRetrievalFaultRetriever,
)
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.models import Domain
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


def test_fault_is_inert_until_a_bundle_is_explicitly_wrapped() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = EmptyRetrievalFault(target_domain=Domain.PRODUCT)

    results = retrievers.product.search("SAML 2.0 and SCIM 2.0", k=5)

    assert results
    assert fault.invocation_count == 0
    assert fault.receipts == ()


def test_wrapped_target_returns_empty_and_writes_secret_free_receipt() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = EmptyRetrievalFault(target_domain=Domain.SECURITY)
    faulted = fault.wrap(retrievers)

    results = faulted.security.search("SOC 2 Type II", k=5)

    assert results == []
    assert fault.invocation_count == 1
    assert fault.receipts[0].fault_type == "empty_retrieval"
    assert fault.receipts[0].domain is Domain.SECURITY
    assert fault.receipts[0].invocation_number == 1
    assert fault.receipts[0].requested_top_k == 5
    assert fault.receipts[0].returned_count == 0
    assert "SOC" not in repr(fault.receipts[0])


def test_fault_wraps_only_the_selected_domain() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = EmptyRetrievalFault(target_domain=Domain.SECURITY)
    faulted = fault.wrap(retrievers)

    assert faulted.product is retrievers.product
    assert faulted.implementation is retrievers.implementation
    assert isinstance(faulted.security, EmptyRetrievalFaultRetriever)
    assert faulted.product.search("SAML 2.0", k=5)
    assert faulted.implementation.search("implementation prerequisites", k=5)
    assert fault.invocation_count == 0


def test_fault_can_return_empty_once_then_delegate_to_normal_retrieval() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = EmptyRetrievalFault(
        target_domain=Domain.PRODUCT, empty_on_calls=(1,)
    )
    faulted = fault.wrap(retrievers)

    assert faulted.product.search("SAML 2.0", k=5) == []
    assert faulted.product.search("SAML 2.0", k=5)
    assert fault.invocation_count == 2
    assert [item.invocation_number for item in fault.receipts] == [1]


def test_fault_preserves_query_and_top_k_validation() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = EmptyRetrievalFault(target_domain=Domain.PRODUCT)
    faulted = fault.wrap(retrievers)

    with pytest.raises(ValueError, match="searchable token"):
        faulted.product.search("---", k=5)
    with pytest.raises(ValueError, match="between 1 and 5"):
        faulted.product.search("SAML", k=6)

    assert fault.invocation_count == 0


def test_empty_retrieval_fault_reaches_bounded_recovery_and_safe_hitl() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = EmptyRetrievalFault(target_domain=Domain.PRODUCT)
    graph = build_selected_fanout_graph(
        fault.wrap(retrievers),
        event_clock=lambda: "fixed",
    )

    state = graph.invoke(
        new_requirement_state(
            "fault-case-1",
            "RFP-001",
            "Confirm support for SAML 2.0 and SCIM 2.0.",
        )
    )

    assert fault.invocation_count == 3
    assert [receipt.invocation_number for receipt in fault.receipts] == [1, 2, 3]
    assert {receipt.domain for receipt in fault.receipts} == {Domain.PRODUCT}
    assert state["retry_count"] == 2
    assert state["recovery_exhausted"] is True
    assert state["strategy"] == "IMMEDIATE_HITL"
    assert state["final_status"] == "NEEDS_HUMAN"
    assert state["final_answer"] is None
    assert state["evidence_failure_contexts"][0]["failure_type"] == "EMPTY_RETRIEVAL"


def test_invalid_fault_target_is_rejected_before_any_retrieval() -> None:
    with pytest.raises(TypeError, match="must be a Domain"):
        EmptyRetrievalFault(target_domain="security")  # type: ignore[arg-type]


@pytest.mark.parametrize("calls", [(), (0,), (-1,), (True,), (1, 1), [1]])
def test_invalid_empty_call_schedule_is_rejected(calls) -> None:
    with pytest.raises(ValueError, match="distinct positive call numbers"):
        EmptyRetrievalFault(target_domain=Domain.PRODUCT, empty_on_calls=calls)
