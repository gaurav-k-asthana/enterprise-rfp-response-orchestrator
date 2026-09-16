from pathlib import Path

from streamlit.testing.v1 import AppTest

from rfp_orchestrator.ui import SAFETY_NOTICE_BODY, SAFETY_NOTICE_TITLE

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"


def _notice_text(app: AppTest) -> str:
    assert len(app.warning) == 1
    return app.warning[0].value.lower()


def test_notice_contract_names_data_draft_review_and_authority_limits() -> None:
    notice = f"{SAFETY_NOTICE_TITLE} {SAFETY_NOTICE_BODY}".lower()

    for required_phrase in (
        "fictitious company",
        "synthetic rfp requirements",
        "synthetic evidence",
        "draft responses",
        "human review",
        "may be incomplete",
        "legal",
        "commercial",
        "security-exception",
        "roadmap",
        "customer-specific contractual commitments",
    ):
        assert required_phrase in notice


def test_notice_is_prominent_before_any_requirement_run() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    notice = _notice_text(app)

    assert not app.exception
    assert "synthetic demonstration" in notice
    assert "human review required" in notice


def test_notice_remains_visible_after_a_requirement_run() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    app.sidebar.button[0].click().run(timeout=10)

    assert not app.exception
    assert "draft responses" in _notice_text(app)


def test_notice_remains_visible_after_clearing_the_current_run() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)
    app.sidebar.button[0].click().run(timeout=10)

    app.sidebar.button[1].click().run(timeout=10)

    assert not app.exception
    assert "synthetic evidence" in _notice_text(app)
