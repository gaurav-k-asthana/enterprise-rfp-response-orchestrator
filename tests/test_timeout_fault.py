from pathlib import Path
from unittest.mock import patch

import pytest

from rfp_orchestrator.fault_injection import (
    InjectedTimeoutError,
    TimeoutFault,
    TimeoutFaultRetriever,
)
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.models import Domain
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"
SAMPLE_TEXT = "Confirm support for SAML 2.0 and SCIM 2.0."


def test_timeout_fault_is_inert_until_explicitly_wrapped() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = TimeoutFault(target_domain=Domain.PRODUCT)

    assert retrievers.product.search("SAML 2.0", k=5)
    assert fault.invocation_count == 0
    assert fault.receipts == ()


def test_virtual_deadline_raises_immediately_with_safe_receipt() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = TimeoutFault(
        target_domain=Domain.SECURITY,
        timeout_ms=100,
        simulated_elapsed_ms=101,
    )
    faulted = fault.wrap(retrievers)

    with (
        patch("time.sleep", side_effect=AssertionError("real sleep is forbidden")),
        pytest.raises(
            InjectedTimeoutError, match=r"Controlled retrieval timeout \(test only\)"
        ) as raised,
    ):
        faulted.security.search("sensitive customer SOC 2 question", k=5)

    assert isinstance(raised.value, TimeoutError)
    assert "sensitive customer" not in str(raised.value)
    assert fault.invocation_count == 1
    assert len(fault.receipts) == 1
    assert fault.receipts[0].fault_type == "timeout"
    assert fault.receipts[0].domain is Domain.SECURITY
    assert fault.receipts[0].invocation_number == 1
    assert fault.receipts[0].requested_top_k == 5
    assert fault.receipts[0].timeout_ms == 100
    assert fault.receipts[0].simulated_elapsed_ms == 101
    assert fault.receipts[0].error_code == "INJECTED_RETRIEVAL_TIMEOUT"
    assert "sensitive customer" not in repr(fault.receipts)


def test_timeout_wraps_only_selected_domain_and_keeps_original_bundle() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = TimeoutFault(target_domain=Domain.SECURITY)
    faulted = fault.wrap(retrievers)

    assert isinstance(faulted.security, TimeoutFaultRetriever)
    assert faulted.product is retrievers.product
    assert faulted.implementation is retrievers.implementation
    assert retrievers.security.search("SOC 2", k=5)
    assert faulted.product.search("SAML 2.0", k=5)
    assert faulted.implementation.search("implementation prerequisites", k=5)
    assert fault.invocation_count == 0


def test_selected_call_schedule_times_out_second_call_only() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = TimeoutFault(target_domain=Domain.PRODUCT, fail_on_calls=(2,))
    faulted = fault.wrap(retrievers)

    assert faulted.product.search("SAML 2.0")
    with pytest.raises(InjectedTimeoutError):
        faulted.product.search("SAML 2.0")
    assert faulted.product.search("SAML 2.0")

    assert fault.invocation_count == 3
    assert [item.invocation_number for item in fault.receipts] == [2]


@pytest.mark.parametrize(
    ("elapsed_ms", "expected_timeout"),
    [(99, False), (100, True), (101, True)],
)
def test_virtual_elapsed_time_uses_deadline_boundary(
    elapsed_ms: int, expected_timeout: bool
) -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = TimeoutFault(
        target_domain=Domain.PRODUCT,
        timeout_ms=100,
        simulated_elapsed_ms=elapsed_ms,
    )
    faulted = fault.wrap(retrievers)

    if expected_timeout:
        with pytest.raises(InjectedTimeoutError):
            faulted.product.search("SAML 2.0")
        assert len(fault.receipts) == 1
    else:
        assert faulted.product.search("SAML 2.0")
        assert fault.receipts == ()


def test_invalid_query_or_top_k_cannot_trigger_timeout() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    fault = TimeoutFault(target_domain=Domain.PRODUCT)
    faulted = fault.wrap(retrievers)

    with pytest.raises(ValueError, match="searchable token"):
        faulted.product.search("---", k=5)
    with pytest.raises(ValueError, match="between 1 and 5"):
        faulted.product.search("SAML", k=6)

    assert fault.invocation_count == 0
    assert fault.receipts == ()


@pytest.mark.parametrize("timeout_ms", [0, -1, True, 1.5, "100"])
def test_invalid_deadline_is_rejected(timeout_ms) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        TimeoutFault(target_domain=Domain.PRODUCT, timeout_ms=timeout_ms)


@pytest.mark.parametrize("elapsed_ms", [-1, True, 1.5, "101"])
def test_invalid_simulated_elapsed_time_is_rejected(elapsed_ms) -> None:
    with pytest.raises(ValueError, match="nonnegative integer"):
        TimeoutFault(target_domain=Domain.PRODUCT, simulated_elapsed_ms=elapsed_ms)


@pytest.mark.parametrize("calls", [(), (0,), (-1,), (True,), (1, 1), [1]])
def test_invalid_call_schedule_is_rejected(calls) -> None:
    with pytest.raises(ValueError, match="distinct positive call numbers"):
        TimeoutFault(target_domain=Domain.PRODUCT, fail_on_calls=calls)


def test_invalid_domain_is_rejected() -> None:
    with pytest.raises(TypeError, match="must be a Domain"):
        TimeoutFault(target_domain="product")  # type: ignore[arg-type]


def test_graph_streams_blocked_timeout_without_merging_or_finalizing() -> None:
    fault = TimeoutFault(target_domain=Domain.PRODUCT)
    graph = build_selected_fanout_graph(
        fault.wrap(build_offline_retrievers(KB_DIRECTORY)),
        event_clock=lambda: "fixed",
    )
    events: list[dict] = []

    with pytest.raises(InjectedTimeoutError):
        events.extend(
            graph.stream(
                new_requirement_state("fault-case-5", "RFP-001", SAMPLE_TEXT),
                stream_mode="custom",
            )
        )

    assert fault.invocation_count == 1
    assert [
        event["status"]
        for event in events
        if event["node"] == GraphNode.PRODUCT_SPECIALIST.value
    ] == ["active", "blocked"]
    assert events[-1]["detail"] == "product_specialist failed: InjectedTimeoutError"
    assert not any(event["node"] == GraphNode.MERGE.value for event in events)
    assert not any(event["node"] == GraphNode.RECOVERY_ATTEMPT.value for event in events)
    assert not any(event["node"] == GraphNode.FINALIZATION_GUARD.value for event in events)
