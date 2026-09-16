from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from rfp_orchestrator.human_review_ui import (
    DECISION_LABELS,
    REVIEW_SESSION_KEYS,
    SESSION_REVIEW_ACTION,
    SESSION_REVIEW_DECISION_DRAFT,
    HumanReviewControlError,
    build_decision_draft,
    clear_review_draft,
    review_action_options,
)
from rfp_orchestrator.models import ApprovalDecision
from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.ui import stream_sample_requirement

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"


def interrupted_state(requirement_index: int = 4) -> dict:
    return stream_sample_requirement(
        load_sample_requirements()[requirement_index],
        1,
        f"review-ui-{requirement_index}",
    ).state


def test_action_options_preserve_all_five_locked_decisions_in_order() -> None:
    options = review_action_options(interrupted_state())

    assert [item.decision for item in options] == list(ApprovalDecision)
    assert [item.label for item in options] == [
        DECISION_LABELS[decision] for decision in ApprovalDecision
    ]
    assert all(item.enabled for item in options)


def test_exhausted_recovery_keeps_retry_visible_but_disabled() -> None:
    options = review_action_options(interrupted_state(20))
    retry = next(
        item for item in options if item.decision is ApprovalDecision.REQUEST_RETRY
    )

    assert retry.enabled is False
    assert retry.disabled_reason == "The locked two-retry retrieval budget is exhausted."


def test_unresolved_conflict_disables_approval_but_keeps_safe_actions() -> None:
    options = review_action_options(interrupted_state(13))
    by_decision = {item.decision: item for item in options}
    reason = (
        "Resolve the evidence conflict before approving this response. "
        "Use Add guidance, Request retry, or Reject."
    )

    assert [item.decision for item in options] == list(ApprovalDecision)
    assert by_decision[ApprovalDecision.APPROVE].enabled is False
    assert by_decision[ApprovalDecision.APPROVE].disabled_reason == reason
    assert by_decision[ApprovalDecision.EDIT_AND_APPROVE].enabled is False
    assert by_decision[ApprovalDecision.EDIT_AND_APPROVE].disabled_reason == reason
    assert by_decision[ApprovalDecision.REJECT].enabled is True
    assert by_decision[ApprovalDecision.ADD_GUIDANCE].enabled is True
    assert by_decision[ApprovalDecision.REQUEST_RETRY].enabled is True


@pytest.mark.parametrize("decision", ["APPROVE", "EDIT_AND_APPROVE"])
def test_unresolved_conflict_cannot_prepare_approval_draft(decision: str) -> None:
    with pytest.raises(HumanReviewControlError, match="Resolve the evidence conflict"):
        build_decision_draft(
            interrupted_state(13),
            decision=decision,
            reviewer="reviewer@example.test",
            edited_answer="Edited response." if decision == "EDIT_AND_APPROVE" else None,
        )


@pytest.mark.parametrize(
    ("decision", "updates"),
    [
        ("APPROVE", {}),
        (
            "EDIT_AND_APPROVE",
            {"edited_answer": "Approved standard terms only."},
        ),
        ("REJECT", {}),
        (
            "ADD_GUIDANCE",
            {
                "guidance": "Use only the approved standard position.",
                "target_specialists": ["product"],
            },
        ),
        (
            "REQUEST_RETRY",
            {
                "guidance": "Search once more for the standard boundary.",
                "target_specialists": ["product"],
            },
        ),
    ],
)
def test_each_control_builds_a_strict_draft_without_mutating_graph_state(
    decision: str,
    updates: dict,
) -> None:
    state = interrupted_state()
    original = deepcopy(state)

    draft = build_decision_draft(
        state,
        decision=decision,
        reviewer="reviewer@example.test",
        timestamp="2026-08-31T20:00:00Z",
        **updates,
    )

    assert draft["requirement_id"] == "RFP-005"
    assert draft["decision"] == decision
    assert draft["reviewer"] == "reviewer@example.test"
    assert state == original
    assert state["awaiting_human_review"] is True
    assert state["approval"] is None


@pytest.mark.parametrize(
    ("decision", "updates", "message"),
    [
        ("APPROVE", {"reviewer": " "}, "required fields"),
        (
            "EDIT_AND_APPROVE",
            {"reviewer": "reviewer", "edited_answer": " "},
            "required fields",
        ),
        (
            "ADD_GUIDANCE",
            {"reviewer": "reviewer", "target_specialists": ["product"]},
            "required fields",
        ),
        (
            "ADD_GUIDANCE",
            {
                "reviewer": "reviewer",
                "guidance": "Review again.",
                "target_specialists": ["security"],
            },
            "outside the saved requirement scope",
        ),
    ],
)
def test_incomplete_or_out_of_scope_drafts_fail_closed(
    decision: str,
    updates: dict,
    message: str,
) -> None:
    with pytest.raises(HumanReviewControlError, match=message):
        build_decision_draft(interrupted_state(), decision=decision, **updates)


def test_clear_review_draft_removes_only_review_session_values() -> None:
    session_state = {
        **{key: "value" for key in REVIEW_SESSION_KEYS},
        "latest_run_state": {"final_status": "NEEDS_HUMAN"},
    }

    clear_review_draft(session_state)

    assert session_state == {
        "latest_run_state": {"final_status": "NEEDS_HUMAN"}
    }


def test_safe_ui_run_does_not_show_human_review_controls() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)
    app.sidebar.button[0].click().run(timeout=10)

    assert "Human review" not in [item.value for item in app.subheader]
    assert not any(button.label == "Approve" for button in app.button)


def test_interrupted_ui_run_shows_five_controls_and_saves_draft_only() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)
    app.sidebar.selectbox[0].select("RFP-005").run(timeout=10)
    app.sidebar.button[0].click().run(timeout=10)

    assert "Human review" in [item.value for item in app.subheader]
    action_labels = {
        "Approve",
        "Edit and approve",
        "Reject",
        "Add guidance",
        "Request retry",
    }
    assert action_labels.issubset({button.label for button in app.button})

    approve = next(button for button in app.button if button.label == "Approve")
    approve.click().run(timeout=10)
    reviewer = next(
        item for item in app.text_input if item.label == "Reviewer name or email"
    )
    reviewer.input("reviewer@example.test")
    submit = next(
        button for button in app.button if button.label == "Save decision draft"
    )
    submit.click().run(timeout=10)

    draft = app.session_state[SESSION_REVIEW_DECISION_DRAFT]
    assert app.session_state[SESSION_REVIEW_ACTION] == "APPROVE"
    assert draft["decision"] == "APPROVE"
    assert draft["reviewer"] == "reviewer@example.test"
    assert app.session_state["latest_run_state"]["awaiting_human_review"] is True
    assert app.session_state["latest_run_state"]["approval"] is None
    assert any("graph remains paused" in item.value.lower() for item in app.success)


def test_unresolved_conflict_ui_disables_only_approval_controls() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)
    app.sidebar.selectbox[0].select("RFP-014").run(timeout=10)
    app.sidebar.button[0].click().run(timeout=10)

    actions = {
        button.label: button
        for button in app.button
        if button.label in set(DECISION_LABELS.values())
    }

    assert set(actions) == set(DECISION_LABELS.values())
    assert actions["Approve"].disabled is True
    assert actions["Edit and approve"].disabled is True
    assert actions["Reject"].disabled is False
    assert actions["Add guidance"].disabled is False
    assert actions["Request retry"].disabled is False
