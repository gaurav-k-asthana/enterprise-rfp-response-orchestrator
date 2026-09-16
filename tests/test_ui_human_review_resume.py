from dataclasses import replace
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.human_review_ui import build_decision_draft
from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.ui import (
    HumanReviewResumeError,
    stream_human_review_decision,
    stream_sample_requirement,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"
RFP_005 = load_sample_requirements()[4]
SLA_PROPOSAL_ID = "RFP-005:product:product-claim-001:UPTIME_SLA"


def interrupted_run(name: str):
    return stream_sample_requirement(RFP_005, 1, f"step-3-13-{name}")


def decision(run, action: str, **updates) -> dict:
    return build_decision_draft(
        run.state,
        decision=action,
        reviewer="reviewer@example.test",
        timestamp="2026-09-01T16:00:00Z",
        **updates,
    )


def test_initial_interrupt_is_visible_as_a_real_blocked_graph_event() -> None:
    frames: list[tuple[str, str]] = []
    run = stream_sample_requirement(
        RFP_005,
        1,
        "step-3-13-blocked",
        on_event=lambda _nodes, _edges, _counts, event: frames.append(
            (event["node"], event["status"])
        ),
    )

    assert frames[-1] == (GraphNode.HUMAN_REVIEW_INTERRUPT.value, "blocked")
    assert run.node_status[GraphNode.HUMAN_REVIEW_INTERRUPT.value] == "blocked"
    assert run.edge_status[
        (
            GraphNode.HUMAN_REVIEW_CHECKPOINT.value,
            GraphNode.HUMAN_REVIEW_INTERRUPT.value,
        )
    ] == "blocked"
    assert run.event_count == len(run.state["execution_events"]) + 1


def test_approve_resumes_the_same_checkpoint_and_finalizes() -> None:
    initial = interrupted_run("approve")
    resumed = stream_human_review_decision(
        initial,
        decision(
            initial,
            "APPROVE",
            approved_proposal_ids=[SLA_PROPOSAL_ID],
        ),
    )

    assert resumed.thread_id == initial.thread_id
    assert resumed.state["final_status"] == "FINALIZED"
    assert resumed.state["awaiting_human_review"] is False
    assert resumed.state["human_decision_history"][-1]["decision"] == "APPROVE"
    assert resumed.state["commitment_promotion"]["status"] == "PROMOTED"
    assert resumed.node_status[GraphNode.HUMAN_REVIEW_INTERRUPT.value] == "complete"
    assert resumed.edge_status[
        (
            GraphNode.HUMAN_REVIEW_INTERRUPT.value,
            GraphNode.FINALIZATION_GUARD.value,
        )
    ] == "complete"


def test_edit_and_approve_preserves_the_reviewed_answer() -> None:
    initial = interrupted_run("edit")
    edited = "We offer the approved 99.9% standard; no 99.99% commitment is made."
    resumed = stream_human_review_decision(
        initial,
        decision(initial, "EDIT_AND_APPROVE", edited_answer=edited),
    )

    assert resumed.state["final_status"] == "FINALIZED"
    assert resumed.state["final_answer"] == edited
    assert resumed.state["approval"]["edited_answer"] == edited


def test_reject_ends_without_final_answer_or_promotion() -> None:
    initial = interrupted_run("reject")
    resumed = stream_human_review_decision(
        initial,
        decision(initial, "REJECT"),
    )

    assert resumed.state["final_status"] == "REJECTED"
    assert resumed.state["final_answer"] is None
    assert resumed.state["commitment_promotion"] is None
    assert resumed.state["awaiting_human_review"] is False
    assert resumed.node_status[GraphNode.HUMAN_REVIEW_INTERRUPT.value] == "complete"


def test_add_guidance_runs_scoped_rework_and_pauses_again() -> None:
    initial = interrupted_run("guidance")
    resumed = stream_human_review_decision(
        initial,
        decision(
            initial,
            "ADD_GUIDANCE",
            guidance="Use only the approved standard position.",
            target_specialists=["product"],
        ),
    )

    assert resumed.state["human_rework_count"] == 1
    assert resumed.state["retry_count"] == 0
    assert resumed.state["awaiting_human_review"] is True
    assert resumed.state["final_status"] == "NEEDS_HUMAN"
    assert resumed.node_status[GraphNode.HUMAN_REWORK_ATTEMPT.value] == "complete"
    assert resumed.node_status[GraphNode.HUMAN_REVIEW_INTERRUPT.value] == "blocked"
    assert resumed.edge_status[
        (
            GraphNode.HUMAN_REVIEW_INTERRUPT.value,
            GraphNode.HUMAN_REWORK_ATTEMPT.value,
        )
    ] == "complete"


def test_request_retry_uses_bounded_recovery_and_pauses_again() -> None:
    initial = interrupted_run("retry")
    resumed = stream_human_review_decision(
        initial,
        decision(
            initial,
            "REQUEST_RETRY",
            guidance="Search once more for the approved SLA boundary.",
            target_specialists=["product"],
        ),
    )

    assert resumed.state["retry_count"] == 1
    assert resumed.state["awaiting_human_review"] is True
    assert resumed.attempt_counts[GraphNode.RECOVERY_ATTEMPT.value] == 1
    assert resumed.edge_status[
        (
            GraphNode.HUMAN_REVIEW_INTERRUPT.value,
            GraphNode.RECOVERY_ATTEMPT.value,
        )
    ] == "complete"


def test_resume_callback_failure_does_not_stop_the_graph() -> None:
    initial = interrupted_run("callback-failure")
    callback_calls = 0

    def fail_once(*_args) -> None:
        nonlocal callback_calls
        callback_calls += 1
        raise RuntimeError("presentation only")

    resumed = stream_human_review_decision(
        initial,
        decision(initial, "APPROVE"),
        on_event=fail_once,
    )

    assert callback_calls == 1
    assert resumed.visualization_failed is True
    assert resumed.state["final_status"] == "FINALIZED"


def test_resume_rejects_a_missing_or_stale_checkpoint() -> None:
    initial = interrupted_run("stale")
    draft = decision(initial, "REJECT")
    wrong_thread = replace(initial, thread_id="missing-step-3-13-thread")
    stale_state = dict(initial.state)
    stale_request = dict(stale_state["human_review_request"])
    stale_request["rationale"] = "Changed after the reviewer prepared a draft."
    stale_state["human_review_request"] = stale_request
    stale = replace(initial, state=stale_state)

    with pytest.raises(HumanReviewResumeError, match="not at human review"):
        stream_human_review_decision(wrong_thread, draft)
    with pytest.raises(HumanReviewResumeError, match="changed after this draft"):
        stream_human_review_decision(stale, draft)


def test_streamlit_applies_saved_approval_and_refreshes_the_result() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)
    app.sidebar.selectbox[0].select("RFP-005").run(timeout=10)
    app.sidebar.button[0].click().run(timeout=10)

    next(button for button in app.button if button.label == "Approve").click().run(
        timeout=10
    )
    next(
        item for item in app.text_input if item.label == "Reviewer name or email"
    ).input("reviewer@example.test")
    next(
        button for button in app.button if button.label == "Save decision draft"
    ).click().run(timeout=10)

    next(
        button
        for button in app.button
        if button.label == "Apply decision and resume workflow"
    ).click().run(timeout=10)

    state = app.session_state["latest_run_state"]
    assert state["final_status"] == "FINALIZED"
    assert state["awaiting_human_review"] is False
    assert state["human_decision_history"][-1]["decision"] == "APPROVE"
    assert "Human review" not in [item.value for item in app.subheader]
    assert any("finalized successfully" in item.value for item in app.success)
