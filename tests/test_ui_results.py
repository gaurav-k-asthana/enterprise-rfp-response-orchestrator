from pathlib import Path

from streamlit.testing.v1 import AppTest

from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.ui import (
    RESULT_COLUMNS,
    build_requirement_result_row,
    evidence_state_label,
    run_sample_requirement,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"


def test_result_row_summarizes_the_real_offline_graph_state() -> None:
    state, _ = run_sample_requirement(load_sample_requirements()[0], 1)

    row = build_requirement_result_row(state)

    assert tuple(row) == RESULT_COLUMNS
    assert row == {
        "Requirement": (
            "RFP-001 — Confirm support for SAML 2.0 and SCIM 2.0."
        ),
        "Strategy": "Single Specialist",
        "Selected specialists": "Product",
        "Evidence state": "Supported / Validated",
        "Risk": "None detected",
        "Final status": "Finalized",
    }


def test_evidence_summary_prioritizes_recovery_and_validation_failures() -> None:
    assert evidence_state_label({"recovery_exhausted": True}) == "Recovery exhausted"
    assert evidence_state_label({"recovery_needed": True}) == "Recovery required"
    assert evidence_state_label({"citation_valid": False}) == "Validation failed"


def test_evidence_summary_aggregates_specialist_support_states() -> None:
    base = {
        "citation_valid": True,
        "source_metadata_valid": True,
        "claim_support_valid": True,
    }

    assert evidence_state_label(base) == "Not evaluated"
    assert evidence_state_label(
        {**base, "merged_specialist_outputs": [{"support_status": "UNSUPPORTED"}]}
    ) == "Unsupported"
    assert evidence_state_label(
        {
            **base,
            "merged_specialist_outputs": [
                {"support_status": "SUPPORTED"},
                {"support_status": "PARTIAL"},
            ],
        }
    ) == "Partial"


def test_page_prompts_for_a_run_before_showing_the_table() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    assert not app.exception
    assert not app.dataframe
    assert "Run a sample requirement to see its result summary." in [
        message.value for message in app.info
    ]


def test_run_renders_the_six_required_summary_columns() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    app.sidebar.button[0].click().run(timeout=10)

    assert not app.exception
    assert len(app.dataframe) == 5
    table = app.dataframe[0].value
    assert tuple(table.columns) == RESULT_COLUMNS
    assert table.to_dict(orient="records") == [
        {
            "Requirement": (
                "RFP-001 — Confirm support for SAML 2.0 and SCIM 2.0."
            ),
            "Strategy": "Single Specialist",
            "Selected specialists": "Product",
            "Evidence state": "Supported / Validated",
            "Risk": "None detected",
            "Final status": "Finalized",
        }
    ]


def test_clear_removes_the_current_result_table() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)
    app.sidebar.button[0].click().run(timeout=10)

    app.sidebar.button[1].click().run(timeout=10)

    assert not app.exception
    assert not app.dataframe
