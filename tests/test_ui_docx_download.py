from copy import deepcopy
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
from streamlit.testing.v1 import AppTest

from rfp_orchestrator import ui
from rfp_orchestrator.docx_export import DocxExportError
from rfp_orchestrator.sample_requirements import load_sample_requirements

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"


def _download_buttons(app: AppTest):
    return app.get("download_button")


def test_download_artifact_uses_current_state_bytes_name_and_mime() -> None:
    state, _ = ui.run_sample_requirement(load_sample_requirements()[0], 1)
    saved = deepcopy(state)

    artifact = ui.build_docx_download(state)

    assert artifact.file_name == "northstar-rfp-response-rfp-001.docx"
    assert artifact.mime_type == ui.DOCX_MIME_TYPE
    assert artifact.data.startswith(b"PK")
    with ZipFile(BytesIO(artifact.data)) as package:
        assert "word/document.xml" in package.namelist()
    document = Document(BytesIO(artifact.data))
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "Requirement RFP-001 | Finalized" in text
    assert state["final_answer"] in text
    assert state == saved


@pytest.mark.parametrize(
    ("requirement_id", "expected_slug"),
    [
        ("RFP 001 / Example", "rfp-001-example"),
        (" RFP---001 ", "rfp-001"),
        ("RFP_001", "rfp-001"),
    ],
)
def test_download_filename_is_sanitized(
    requirement_id: str,
    expected_slug: str,
) -> None:
    state = {
        "requirement_id": requirement_id,
        "original_text": "Confirm the documented capability.",
        "final_status": "FINALIZED",
        "final_answer": "The documented capability is supported.",
    }

    artifact = ui.build_docx_download(state)

    assert artifact.file_name == f"northstar-rfp-response-{expected_slug}.docx"


@pytest.mark.parametrize("state", [None, {}, {"requirement_id": "///"}])
def test_missing_or_unsafe_state_cannot_produce_a_download(state: object) -> None:
    with pytest.raises(DocxExportError):
        ui.build_docx_download(state)


def test_page_explains_that_a_run_is_required_before_download() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    assert not app.exception
    assert not _download_buttons(app)
    assert "Run a sample requirement to prepare its DOCX response." in [
        item.value for item in app.info
    ]


def test_completed_run_exposes_one_requirement_specific_download() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    app.sidebar.button[0].click().run(timeout=10)

    assert not app.exception
    buttons = _download_buttons(app)
    assert len(buttons) == 1
    assert buttons[0].label == "Download DOCX response"
    assert buttons[0].proto.type == "primary"
    assert buttons[0].url.endswith(".docx")
    assert any(
        "Built locally from the current saved result." in item.value
        for item in app.caption
    )


def test_export_failure_is_sanitized_and_preserves_saved_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)
    app.sidebar.button[0].click().run(timeout=10)
    saved = deepcopy(app.session_state[ui.SESSION_LATEST_STATE])

    def fail_export(_state: object) -> bytes:
        raise RuntimeError("api-key=private-export-detail")

    monkeypatch.setattr(ui, "generate_basic_response_docx", fail_export)
    app.run(timeout=10)

    assert not app.exception
    text = "\n".join(item.value for item in app.error)
    assert "RFP-UI-010" in text
    assert "private-export-detail" not in text
    assert not _download_buttons(app)
    assert app.session_state[ui.SESSION_LATEST_STATE] == saved
