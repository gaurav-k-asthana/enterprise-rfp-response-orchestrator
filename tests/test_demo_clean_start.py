"""Step 5.10: run all frozen cases in one fresh Streamlit session."""

import json
from pathlib import Path
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from rfp_orchestrator.ui import (
    SESSION_LATEST_REQUIREMENT,
    SESSION_LATEST_STATE,
    SESSION_RUN_COUNT,
)

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "fixtures" / "demo_cases_v1.json"
APP = ROOT / "app.py"


def test_five_frozen_cases_run_in_one_fresh_ui_session() -> None:
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]

    with patch("rfp_orchestrator.ui.sleep"):
        app = AppTest.from_file(str(APP)).run(timeout=10)
        assert not app.exception
        assert SESSION_LATEST_STATE not in app.session_state

        for run_number, case in enumerate(cases, start=1):
            app.sidebar.selectbox[0].select(case["requirement_id"]).run(timeout=10)
            assert app.sidebar.text_area[0].value == case["requirement_text"]

            app.sidebar.button[0].click().run(timeout=10)
            assert not app.exception
            assert not app.sidebar.error
            assert app.session_state[SESSION_RUN_COUNT] == run_number
            assert app.session_state[SESSION_LATEST_REQUIREMENT] == case[
                "requirement_id"
            ]
            assert [message.value for message in app.sidebar.success] == [
                f"Saved run for {case['requirement_id']}."
            ]

            state = app.session_state[SESSION_LATEST_STATE]
            assert state["original_text"] == case["requirement_text"]
            assert state["initial_specialists"] == case["expected_specialists"]
            assert state["strategy"] == case["expected_terminal_strategy"]
            assert state["final_status"] == case["expected_status"]
            assert state["retry_count"] == case["expected_retries"]
            assert state["conflict_reanalysis_count"] == case[
                "expected_conflict_reanalyses"
            ]
            assert bool(state["final_answer"]) is case["expected_final_answer"]

            if case["expected_review_reason"] is None:
                assert "Human review" not in [item.value for item in app.subheader]
            else:
                assert "Human review" in [item.value for item in app.subheader]
                assert state["human_review_request"]["reason"] == case[
                    "expected_review_reason"
                ]
