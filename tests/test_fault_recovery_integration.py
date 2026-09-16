"""Step 5.8: checkpoint and UI safety across all four injected failure modes."""

from copy import deepcopy
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from streamlit.testing.v1 import AppTest

from rfp_orchestrator import ui
from rfp_orchestrator.fault_injection import (
    EmptyRetrievalFault,
    InjectedStructuredOutputError,
    InjectedTimeoutError,
    InjectedToolException,
    InvalidStructuredOutputFault,
    TimeoutFault,
    ToolExceptionFault,
)
from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.models import Domain
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"
APP_PATH = PROJECT_ROOT / "app.py"
SAMPLE_TEXT = "Confirm support for SAML 2.0 and SCIM 2.0."


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


def _graph_with_fault(
    mode: str,
    *,
    domain: Domain = Domain.PRODUCT,
    fail_on_calls: tuple[int, ...] = (1,),
    empty_on_calls: tuple[int, ...] | None = None,
):
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    functions = None
    if mode == "empty":
        fault = EmptyRetrievalFault(
            target_domain=domain, empty_on_calls=empty_on_calls
        )
        retrievers = fault.wrap(retrievers)
    elif mode == "tool":
        fault = ToolExceptionFault(target_domain=domain, fail_on_calls=fail_on_calls)
        retrievers = fault.wrap(retrievers)
    elif mode == "invalid":
        fault = InvalidStructuredOutputFault(
            target_domain=domain, fail_on_calls=fail_on_calls
        )
        functions = fault.wrap_offline_specialists()
    elif mode == "timeout":
        fault = TimeoutFault(target_domain=domain, fail_on_calls=fail_on_calls)
        retrievers = fault.wrap(retrievers)
    else:
        raise AssertionError(f"unknown test fault: {mode}")
    graph = build_selected_fanout_graph(
        retrievers,
        specialist_functions=functions,
        checkpointer=InMemorySaver(),
        event_clock=lambda: "fixed",
    )
    return graph, fault


def _new_state() -> dict:
    return new_requirement_state("fault-case-5-8", "RFP-001", SAMPLE_TEXT)


def test_persistent_empty_retrieval_hits_exact_two_retry_checkpoint() -> None:
    graph, fault = _graph_with_fault("empty")
    thread = _config("empty-hard-stop")

    result = graph.invoke(_new_state(), thread)
    snapshot = graph.get_state(thread)

    assert fault.invocation_count == 3
    assert result["retry_count"] == 2
    assert result["recovery_exhausted"] is True
    assert [item["attempt_number"] for item in result["recovery_attempts"]] == [1, 2]
    assert result["final_status"] == "NEEDS_HUMAN"
    assert result["final_answer"] is None
    assert result["commitments"] == []
    assert result["commitment_promotion"] is None
    assert len(result["__interrupt__"]) == 1
    assert result["__interrupt__"][0].value["reason"] == "RETRY_BUDGET_EXHAUSTED"
    assert snapshot.next == (GraphNode.HUMAN_REVIEW_INTERRUPT.value,)
    assert snapshot.values["retry_count"] == 2
    assert snapshot.values["final_answer"] is None
    assert snapshot.values["human_review_request"] == result["human_review_request"]


def test_transient_empty_retrieval_retries_once_then_finalizes_from_checkpoint() -> None:
    graph, fault = _graph_with_fault("empty", empty_on_calls=(1,))
    thread = _config("empty-recovered")

    result = graph.invoke(_new_state(), thread)
    snapshot = graph.get_state(thread)

    assert fault.invocation_count == 2
    assert [item.invocation_number for item in fault.receipts] == [1]
    assert result["retry_count"] == 1
    assert [item["attempt_number"] for item in result["recovery_attempts"]] == [1]
    assert result["recovery_exhausted"] is False
    assert result["final_status"] == "FINALIZED"
    assert result["finalization_passed"] is True
    assert result["final_answer"]
    assert snapshot.next == ()
    assert snapshot.values["final_answer"] == result["final_answer"]


def test_exhausted_empty_retrieval_review_can_reject_without_answer() -> None:
    graph, fault = _graph_with_fault("empty")
    thread = _config("empty-review-reject")
    interrupted = graph.invoke(_new_state(), thread)

    rejected = graph.invoke(
        Command(
            resume={
                "requirement_id": "RFP-001",
                "decision": "REJECT",
                "reviewer": "Synthetic Reviewer",
                "timestamp": "2026-09-16T00:00:00Z",
            }
        ),
        thread,
    )

    assert interrupted["final_status"] == "NEEDS_HUMAN"
    assert rejected["final_status"] == "REJECTED"
    assert rejected["final_answer"] is None
    assert rejected["commitments"] == []
    assert rejected["commitment_promotion"] is None
    assert rejected["retry_count"] == 2
    assert fault.invocation_count == 3
    assert graph.get_state(thread).next == ()


@pytest.mark.parametrize(
    ("mode", "error_type"),
    [
        ("tool", InjectedToolException),
        ("invalid", InjectedStructuredOutputError),
        ("timeout", InjectedTimeoutError),
    ],
)
def test_one_time_failure_preserves_checkpoint_and_resumes_safely(
    mode: str, error_type: type[Exception]
) -> None:
    graph, fault = _graph_with_fault(mode)
    thread = _config(f"{mode}-resume")

    with pytest.raises(error_type):
        graph.invoke(_new_state(), thread)
    failed = graph.get_state(thread)

    assert fault.invocation_count == 1
    assert failed.values["specialist_outputs"] == {}
    assert failed.values["specialist_evidence"] == {}
    assert failed.values["final_answer"] is None
    assert failed.values["commitments"] == []
    assert failed.values["commitment_promotion"] is None
    assert failed.next == (GraphNode.PRODUCT_SPECIALIST.value,)

    recovered = graph.invoke(None, thread)
    complete = graph.get_state(thread)

    assert fault.invocation_count == 2
    assert recovered["final_status"] == "FINALIZED"
    assert recovered["finalization_passed"] is True
    assert recovered["final_answer"]
    assert recovered["retry_count"] == 0
    assert complete.next == ()
    assert complete.values["final_answer"] == recovered["final_answer"]


@pytest.mark.parametrize(
    ("mode", "error_type"),
    [
        ("tool", InjectedToolException),
        ("invalid", InjectedStructuredOutputError),
        ("timeout", InjectedTimeoutError),
    ],
)
def test_persistent_failure_stops_without_automatic_retry_or_unsafe_output(
    mode: str, error_type: type[Exception]
) -> None:
    graph, fault = _graph_with_fault(mode, fail_on_calls=(1, 2))
    thread = _config(f"{mode}-persistent")
    # A persistent fault can be selected explicitly for more than one manual
    # resume; one graph invocation must still fail without an internal loop.

    with pytest.raises(error_type):
        graph.invoke(_new_state(), thread)
    first = graph.get_state(thread)
    with pytest.raises(error_type):
        graph.invoke(None, thread)
    second = graph.get_state(thread)

    assert fault.invocation_count == 2
    assert first.next == second.next == (GraphNode.PRODUCT_SPECIALIST.value,)
    assert first.values["specialist_outputs"] == second.values["specialist_outputs"] == {}
    assert first.values["final_answer"] is second.values["final_answer"] is None
    assert first.values["retry_count"] == second.values["retry_count"] == 0
    assert first.values["commitments"] == second.values["commitments"] == []


@pytest.mark.parametrize(
    ("mode", "error_type"),
    [
        ("tool", InjectedToolException),
        ("invalid", InjectedStructuredOutputError),
        ("timeout", InjectedTimeoutError),
    ],
)
def test_parallel_failure_restarts_from_consistent_peer_barrier(
    mode: str, error_type: type[Exception]
) -> None:
    graph, fault = _graph_with_fault(mode, domain=Domain.SECURITY)
    thread = _config(f"{mode}-parallel")
    parallel_text = (
        "Describe customer-managed encryption keys and identify supported "
        "deployment environments."
    )

    with pytest.raises(error_type):
        graph.invoke(
            new_requirement_state("fault-parallel", "RFP-002", parallel_text),
            thread,
        )
    failed = graph.get_state(thread)

    assert failed.values["final_answer"] is None
    assert failed.values["commitment_promotion"] is None
    assert set(failed.values["specialist_outputs"]) == set(
        failed.values["specialist_evidence"]
    )
    assert not failed.values["merged_specialist_outputs"]
    assert GraphNode.SECURITY_SPECIALIST.value in failed.next

    recovered = graph.invoke(None, thread)

    assert fault.invocation_count == 2
    assert recovered["final_status"] == "FINALIZED"
    assert recovered["merge_order"] == ["product", "security"]
    assert set(recovered["specialist_outputs"]) == {"product", "security"}


def test_failed_thread_cannot_corrupt_a_separate_completed_thread() -> None:
    graph, fault = _graph_with_fault("tool", fail_on_calls=(2,))
    good_thread = _config("fault-isolation-good")
    bad_thread = _config("fault-isolation-bad")

    completed = graph.invoke(_new_state(), good_thread)
    before = deepcopy(graph.get_state(good_thread).values)
    with pytest.raises(InjectedToolException):
        graph.invoke(_new_state(), bad_thread)

    assert fault.invocation_count == 2
    assert completed["final_status"] == "FINALIZED"
    assert graph.get_state(good_thread).values == before
    assert graph.get_state(good_thread).next == ()
    assert graph.get_state(bad_thread).values["final_answer"] is None
    assert graph.get_state(bad_thread).next == (GraphNode.PRODUCT_SPECIALIST.value,)


@pytest.mark.parametrize("mode", ["tool", "invalid", "timeout"])
def test_streamlit_shows_fixed_failure_and_keeps_previous_saved_run(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(ui, "LIVE_EVENT_DWELL_SECONDS", 0)
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)
    app.sidebar.button[0].click().run(timeout=10)
    saved = deepcopy(app.session_state[ui.SESSION_LATEST_STATE])
    saved_thread = app.session_state[ui.SESSION_LATEST_THREAD]
    graph, fault = _graph_with_fault(mode)
    monkeypatch.setattr(ui, "get_ui_graph", lambda: graph)

    app.sidebar.button[0].click().run(timeout=10)

    assert not app.exception
    assert any("RFP-UI-002" in message.value for message in app.error)
    assert all(SAMPLE_TEXT not in message.value for message in app.error)
    assert fault.invocation_count == 1
    assert app.session_state[ui.SESSION_LATEST_STATE] == saved
    assert app.session_state[ui.SESSION_LATEST_THREAD] == saved_thread


def test_empty_retrieval_exposes_review_checkpoint_in_streamlit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ui, "LIVE_EVENT_DWELL_SECONDS", 0)
    graph, fault = _graph_with_fault("empty")
    monkeypatch.setattr(ui, "get_ui_graph", lambda: graph)
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    app.sidebar.button[0].click().run(timeout=10)

    assert not app.exception
    assert fault.invocation_count == 3
    saved = app.session_state[ui.SESSION_LATEST_STATE]
    assert saved["final_status"] == "NEEDS_HUMAN"
    assert saved["final_answer"] is None
    assert saved["retry_count"] == 2
    assert saved["human_review_request"]["reason"] == "RETRY_BUDGET_EXHAUSTED"
    assert not app.error


@pytest.mark.parametrize("mode", ["tool", "invalid", "timeout"])
def test_first_failed_run_saves_no_partial_state(
    monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    monkeypatch.setattr(ui, "LIVE_EVENT_DWELL_SECONDS", 0)
    graph, fault = _graph_with_fault(mode)
    monkeypatch.setattr(ui, "get_ui_graph", lambda: graph)
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    app.sidebar.button[0].click().run(timeout=10)

    assert not app.exception
    assert fault.invocation_count == 1
    assert any("RFP-UI-002" in message.value for message in app.error)
    assert ui.SESSION_LATEST_STATE not in app.session_state
    assert ui.SESSION_LATEST_THREAD not in app.session_state
