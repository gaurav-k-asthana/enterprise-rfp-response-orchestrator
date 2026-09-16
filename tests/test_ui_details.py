from pathlib import Path

from streamlit.testing.v1 import AppTest

from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.ui import run_sample_requirement
from rfp_orchestrator.ui_details import (
    ANSWER_COLUMNS,
    APPROVAL_COLUMNS,
    CITATION_COLUMNS,
    CLAIM_COLUMNS,
    TRACE_COLUMNS,
    build_approval_rows,
    build_citation_rows,
    build_claim_rows,
    build_proposed_answer_rows,
    build_trace_rows,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"


def _rfp_001_state() -> dict:
    state, _ = run_sample_requirement(load_sample_requirements()[0], 1)
    return state


def test_proposed_answer_rows_preserve_specialist_support_and_text() -> None:
    rows = build_proposed_answer_rows(_rfp_001_state())

    assert tuple(rows[0]) == ANSWER_COLUMNS
    assert rows == [
        {
            "Specialist": "Product",
            "Support status": "Supported",
            "Proposed answer": (
                "SAML 2.0 is generally available on Enterprise Cloud and Standard "
                "Cloud. SCIM 2.0 is generally available on Enterprise Cloud."
            ),
        }
    ]


def test_claim_rows_keep_atomic_support_and_citation_links() -> None:
    rows = build_claim_rows(_rfp_001_state())

    assert tuple(rows[0]) == CLAIM_COLUMNS
    assert len(rows) == 2
    assert [row["Claim ID"] for row in rows] == [
        "product-claim-001",
        "product-claim-002",
    ]
    assert {row["Supported"] for row in rows} == {"Yes"}
    assert {row["Citations"] for row in rows} == {"PROD-AVAIL-001::chunk-001"}


def test_citation_rows_show_only_evidence_used_by_atomic_claims() -> None:
    rows = build_citation_rows(_rfp_001_state())

    assert tuple(rows[0]) == CITATION_COLUMNS
    assert len(rows) == 1
    assert rows[0]["Evidence ID"] == "PROD-AVAIL-001::chunk-001"
    assert rows[0]["Source"] == "Product Availability Matrix"
    assert rows[0]["Domain"] == "Product"
    assert rows[0]["Retrieval"] == "Hybrid"
    assert len(rows[0]["Evidence excerpt"]) <= 240


def test_approval_rows_prefer_complete_decision_history() -> None:
    state = {
        "approval": {
            "decision": "APPROVE",
            "reviewer": "latest@example.test",
            "timestamp": "2026-08-30T15:00:00Z",
        },
        "human_decision_history": [
            {
                "decision": "ADD_GUIDANCE",
                "reviewer": "reviewer@example.test",
                "timestamp": "2026-08-30T14:00:00Z",
                "review_reason": "ORGANIZATIONAL_AUTHORITY",
                "guidance": "Use the approved standard only.",
            },
            {
                "decision": "APPROVE",
                "reviewer": "latest@example.test",
                "timestamp": "2026-08-30T15:00:00Z",
                "review_reason": "ORGANIZATIONAL_AUTHORITY",
            },
        ],
    }

    rows = build_approval_rows(state)

    assert tuple(rows[0]) == APPROVAL_COLUMNS
    assert [row["Decision"] for row in rows] == ["Add Guidance", "Approve"]
    assert rows[0]["Guidance"] == "Use the approved standard only."
    assert rows[1]["Guidance"] == "None"


def test_trace_rows_number_events_in_saved_execution_order() -> None:
    rows = build_trace_rows(_rfp_001_state())

    assert tuple(rows[0]) == TRACE_COLUMNS
    assert len(rows) == 28
    assert rows[0]["Step"] == 1
    assert rows[0]["Node"] == "Requirement Analyzer"
    assert rows[0]["Status"] == "Active"
    assert rows[-1]["Step"] == 28
    assert rows[-1]["Node"] == "Commitment Promotion"
    assert rows[-1]["Status"] == "Complete"


def test_detail_panel_is_absent_before_a_run() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    assert not app.exception
    assert not app.expander
    assert not app.dataframe


def test_run_renders_all_detail_sections_from_saved_state() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    app.sidebar.button[0].click().run(timeout=10)

    assert not app.exception
    assert [item.label for item in app.expander] == [
        "Response, evidence, approval, and trace details"
    ]
    assert len(app.dataframe) == 5
    assert tuple(app.dataframe[1].value.columns) == ANSWER_COLUMNS
    assert tuple(app.dataframe[2].value.columns) == CLAIM_COLUMNS
    assert tuple(app.dataframe[3].value.columns) == CITATION_COLUMNS
    assert tuple(app.dataframe[4].value.columns) == TRACE_COLUMNS
    assert "No human approval was required or recorded for this path." in [
        item.value for item in app.caption
    ]
