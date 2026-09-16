from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from rfp_orchestrator import ui
from rfp_orchestrator.human_review_ui import SESSION_REVIEW_DECISION_DRAFT
from rfp_orchestrator.ui_feedback import (
    UI_FAILURE_MESSAGES,
    UiFailureKind,
    failure_markdown,
    render_ui_failure,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"


class ErrorTarget:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def error(self, message: str, *, icon: str) -> None:
        self.calls.append((message, icon))


def _all_error_text(app: AppTest) -> str:
    return "\n".join(item.value for item in app.error)


def _prepare_saved_approval(app: AppTest) -> None:
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


def test_failure_catalog_has_unique_references_and_complete_guidance() -> None:
    assert set(UI_FAILURE_MESSAGES) == set(UiFailureKind)
    references = [message.reference for message in UI_FAILURE_MESSAGES.values()]
    assert len(references) == len(set(references))

    for kind, message in UI_FAILURE_MESSAGES.items():
        rendered = failure_markdown(kind)
        assert message.title in rendered
        assert message.impact in rendered
        assert "**What to do next:**" in rendered
        assert message.next_action in rendered
        assert f"`{message.reference}`" in rendered


def test_failure_renderer_uses_only_fixed_sanitized_copy() -> None:
    target = ErrorTarget()

    render_ui_failure(UiFailureKind.RUN, target=target)

    assert target.calls == [(failure_markdown(UiFailureKind.RUN), "🚫")]
    assert "provider-secret-detail" not in target.calls[0][0]


def test_sample_catalog_failure_is_sanitized_without_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_catalog():
        raise RuntimeError("private sample parser detail")

    monkeypatch.setattr(ui, "get_sample_requirements", fail_catalog)

    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    assert not app.exception
    text = _all_error_text(app)
    assert "RFP-UI-001" in text
    assert "private sample parser detail" not in text
    assert "Restart Streamlit" in text


def test_failed_new_run_preserves_the_previous_result_and_hides_internals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)
    app.sidebar.button[0].click().run(timeout=10)
    saved = deepcopy(app.session_state[ui.SESSION_LATEST_STATE])
    saved_thread = app.session_state[ui.SESSION_LATEST_THREAD]

    def fail_run(*_args, **_kwargs):
        raise RuntimeError("api-key=private-run-detail")

    monkeypatch.setattr(ui, "stream_sample_requirement", fail_run)
    app.sidebar.selectbox[0].select("RFP-002").run(timeout=10)
    app.sidebar.button[0].click().run(timeout=10)

    assert not app.exception
    text = _all_error_text(app)
    assert "RFP-UI-002" in text
    assert "private-run-detail" not in text
    assert app.session_state[ui.SESSION_RUN_COUNT] == 2
    assert app.session_state[ui.SESSION_LATEST_STATE] == saved
    assert app.session_state[ui.SESSION_LATEST_THREAD] == saved_thread
    assert app.session_state[ui.SESSION_LATEST_REQUIREMENT] == "RFP-001"


@pytest.mark.parametrize(
    ("failure", "reference", "expected_action"),
    [
        (
            ui.HumanReviewResumeError("private stale checkpoint detail"),
            "RFP-UI-006",
            "Clear current run",
        ),
        (
            RuntimeError("api-key=private resume detail"),
            "RFP-UI-007",
            "Apply decision and resume workflow",
        ),
    ],
)
def test_resume_failure_retains_paused_state_and_draft_with_safe_guidance(
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
    reference: str,
    expected_action: str,
) -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)
    _prepare_saved_approval(app)
    saved = deepcopy(app.session_state[ui.SESSION_LATEST_STATE])
    draft = deepcopy(app.session_state[SESSION_REVIEW_DECISION_DRAFT])

    def fail_resume(*_args, **_kwargs):
        raise failure

    monkeypatch.setattr(ui, "stream_human_review_decision", fail_resume)
    next(
        button
        for button in app.button
        if button.label == "Apply decision and resume workflow"
    ).click().run(timeout=10)

    assert not app.exception
    text = _all_error_text(app)
    assert reference in text
    assert "private" not in text
    assert expected_action in text
    assert app.session_state[ui.SESSION_LATEST_STATE] == saved
    assert app.session_state[SESSION_REVIEW_DECISION_DRAFT] == draft


@pytest.mark.parametrize(
    ("attribute", "reference"),
    [
        ("render_requirement_table", "RFP-UI-008"),
        ("render_requirement_details", "RFP-UI-009"),
    ],
)
def test_saved_result_display_boundaries_hide_internal_errors(
    monkeypatch: pytest.MonkeyPatch,
    attribute: str,
    reference: str,
) -> None:
    def fail_display(*_args, **_kwargs):
        raise RuntimeError("private dataframe detail")

    monkeypatch.setattr(ui, attribute, fail_display)

    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    assert not app.exception
    text = _all_error_text(app)
    assert reference in text
    assert "private dataframe detail" not in text
