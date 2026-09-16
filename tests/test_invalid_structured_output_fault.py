from pathlib import Path

import pytest

from rfp_orchestrator.fault_injection import (
    InjectedStructuredOutputError,
    InvalidStructuredOutputFault,
)
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.models import Domain
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.specialists import (
    implementation_specialist_node,
    product_specialist_node,
    security_specialist_node,
)
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"
SAMPLE_TEXT = "Confirm support for SAML 2.0 and SCIM 2.0."


def test_fault_is_inert_until_its_offline_function_map_is_passed_to_graph() -> None:
    fault = InvalidStructuredOutputFault(target_domain=Domain.PRODUCT)
    graph = build_selected_fanout_graph(
        build_offline_retrievers(KB_DIRECTORY), event_clock=lambda: "fixed"
    )

    state = graph.invoke(new_requirement_state("fault-case-3", "RFP-001", SAMPLE_TEXT))

    assert state["final_status"] == "FINALIZED"
    assert fault.invocation_count == 0
    assert fault.receipts == ()


def test_map_wraps_only_selected_peer_function() -> None:
    fault = InvalidStructuredOutputFault(target_domain=Domain.SECURITY)
    functions = fault.wrap_offline_specialists()

    assert set(functions) == set(Domain)
    assert functions[Domain.PRODUCT] is product_specialist_node
    assert functions[Domain.SECURITY] is not security_specialist_node
    assert functions[Domain.IMPLEMENTATION] is implementation_specialist_node
    assert fault.invocation_count == 0


def test_unselected_fault_domain_is_never_invoked() -> None:
    fault = InvalidStructuredOutputFault(target_domain=Domain.SECURITY)
    graph = build_selected_fanout_graph(
        build_offline_retrievers(KB_DIRECTORY),
        specialist_functions=fault.wrap_offline_specialists(),
        event_clock=lambda: "fixed",
    )

    state = graph.invoke(new_requirement_state("fault-case-3", "RFP-001", SAMPLE_TEXT))

    assert state["final_status"] == "FINALIZED"
    assert fault.invocation_count == 0
    assert fault.receipts == ()


def test_graph_rejects_malformed_output_with_fixed_safe_error_and_no_answer() -> None:
    fault = InvalidStructuredOutputFault(target_domain=Domain.PRODUCT)
    graph = build_selected_fanout_graph(
        build_offline_retrievers(KB_DIRECTORY),
        specialist_functions=fault.wrap_offline_specialists(),
        event_clock=lambda: "fixed",
    )
    events: list[dict] = []

    with pytest.raises(
        InjectedStructuredOutputError,
        match=r"Controlled specialist output validation failure \(test only\)",
    ) as raised:
        events.extend(
            graph.stream(
                new_requirement_state("fault-case-3", "RFP-001", SAMPLE_TEXT),
                stream_mode="custom",
            )
        )

    assert SAMPLE_TEXT not in str(raised.value)
    assert fault.invocation_count == 1
    assert len(fault.receipts) == 1
    assert fault.receipts[0].fault_type == "invalid_structured_output"
    assert fault.receipts[0].domain is Domain.PRODUCT
    assert fault.receipts[0].invocation_number == 1
    assert fault.receipts[0].error_code == "INVALID_SPECIALIST_OUTPUT_REJECTED"
    assert SAMPLE_TEXT not in repr(fault.receipts)
    assert [
        event["status"]
        for event in events
        if event["node"] == GraphNode.PRODUCT_SPECIALIST.value
    ] == ["active", "blocked"]
    assert events[-1]["detail"] == (
        "product_specialist failed: InjectedStructuredOutputError"
    )
    assert not any(event["node"] == GraphNode.MERGE.value for event in events)
    assert not any(event["node"] == GraphNode.FINALIZATION_GUARD.value for event in events)


@pytest.mark.parametrize(
    ("domain", "requirement_id", "text"),
    [
        (Domain.SECURITY, "RFP-003", "Confirm SOC 2 Type II certification."),
        (
            Domain.IMPLEMENTATION,
            "RFP-004",
            "Describe implementation prerequisites and customer responsibilities.",
        ),
    ],
)
def test_other_peer_domains_can_be_targeted_independently(
    domain: Domain, requirement_id: str, text: str
) -> None:
    fault = InvalidStructuredOutputFault(target_domain=domain)
    graph = build_selected_fanout_graph(
        build_offline_retrievers(KB_DIRECTORY),
        specialist_functions=fault.wrap_offline_specialists(),
        event_clock=lambda: "fixed",
    )

    with pytest.raises(InjectedStructuredOutputError):
        graph.invoke(new_requirement_state("fault-case-domain", requirement_id, text))

    assert fault.invocation_count == 1
    assert fault.receipts[0].domain is domain


def test_selected_call_schedule_can_fail_then_return_normal_valid_output() -> None:
    fault = InvalidStructuredOutputFault(target_domain=Domain.PRODUCT)
    graph = build_selected_fanout_graph(
        build_offline_retrievers(KB_DIRECTORY),
        specialist_functions=fault.wrap_offline_specialists(),
        event_clock=lambda: "fixed",
    )

    with pytest.raises(InjectedStructuredOutputError):
        graph.invoke(new_requirement_state("fault-case-3", "RFP-001", SAMPLE_TEXT))
    state = graph.invoke(new_requirement_state("fault-case-4", "RFP-001", SAMPLE_TEXT))

    assert state["final_status"] == "FINALIZED"
    assert fault.invocation_count == 2
    assert [receipt.invocation_number for receipt in fault.receipts] == [1]


@pytest.mark.parametrize("calls", [(), (0,), (-1,), (True,), (1, 1), [1]])
def test_invalid_failure_schedule_is_rejected(calls) -> None:
    with pytest.raises(ValueError, match="distinct positive call numbers"):
        InvalidStructuredOutputFault(target_domain=Domain.PRODUCT, fail_on_calls=calls)


def test_invalid_domain_is_rejected() -> None:
    with pytest.raises(TypeError, match="must be a Domain"):
        InvalidStructuredOutputFault(target_domain="product")  # type: ignore[arg-type]
