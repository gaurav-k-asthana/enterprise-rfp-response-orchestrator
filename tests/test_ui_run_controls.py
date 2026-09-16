import re
from pathlib import Path

from streamlit.testing.v1 import AppTest

from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.ui import (
    SESSION_LATEST_REQUIREMENT,
    SESSION_LATEST_STATE,
    SESSION_LATEST_THREAD,
    SESSION_RUN_COUNT,
    clear_current_run,
    run_sample_requirement,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"


def test_run_control_executes_the_real_offline_graph() -> None:
    requirement = load_sample_requirements()[0]

    state, thread_id = run_sample_requirement(requirement, 1, "test-session")

    assert thread_id == "ui-test-session-0001-rfp-001"
    assert state["requirement_id"] == "RFP-001"
    assert state["original_text"] == requirement.text
    assert state["final_status"] == "FINALIZED"
    assert state["final_answer"]


def test_clear_current_run_preserves_the_monotonic_counter() -> None:
    session_state = {
        SESSION_RUN_COUNT: 3,
        SESSION_LATEST_REQUIREMENT: "RFP-001",
        SESSION_LATEST_THREAD: "ui-0003-rfp-001",
        SESSION_LATEST_STATE: {"final_status": "FINALIZED"},
    }

    clear_current_run(session_state)

    assert session_state == {SESSION_RUN_COUNT: 3}


def test_sidebar_exposes_the_24_sample_options_and_run_controls() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    assert not app.exception
    assert len(app.sidebar.selectbox) == 1
    assert len(app.sidebar.selectbox[0].options) == 24
    assert app.sidebar.selectbox[0].value.startswith("RFP-001")
    assert [button.label for button in app.sidebar.button] == [
        "Run selected requirement",
        "Clear current run",
    ]
    assert app.sidebar.text_area[0].value == "Confirm support for SAML 2.0 and SCIM 2.0."


def test_sidebar_selection_updates_the_read_only_requirement_preview() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    app.sidebar.selectbox[0].select("RFP-014").run(timeout=10)

    assert "retained after contract termination" in app.sidebar.text_area[0].value


def test_run_button_saves_graph_state_for_result_rendering() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    app.sidebar.button[0].click().run(timeout=10)

    assert not app.exception
    assert app.session_state[SESSION_RUN_COUNT] == 1
    assert app.session_state[SESSION_LATEST_REQUIREMENT] == "RFP-001"
    assert re.fullmatch(
        r"ui-[0-9a-f]{12}-0001-rfp-001",
        app.session_state[SESSION_LATEST_THREAD],
    )
    assert app.session_state[SESSION_LATEST_STATE]["final_status"] == "FINALIZED"
    assert [message.value for message in app.sidebar.success] == ["Saved run for RFP-001."]
    assert len(app.dataframe) == 5


def test_clear_button_removes_only_the_current_run() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)
    app.sidebar.button[0].click().run(timeout=10)

    app.sidebar.button[1].click().run(timeout=10)

    assert not app.exception
    assert app.session_state[SESSION_RUN_COUNT] == 1
    assert SESSION_LATEST_REQUIREMENT not in app.session_state
    assert SESSION_LATEST_THREAD not in app.session_state
    assert SESSION_LATEST_STATE not in app.session_state
    assert [message.value for message in app.sidebar.info] == ["Current run cleared."]
