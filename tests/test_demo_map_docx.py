"""Step 5.11: verify the live map snapshot and DOCX for every frozen path."""

import json
from copy import deepcopy
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree
from zipfile import ZipFile

from docx import Document
from streamlit.testing.v1 import AppTest

from rfp_orchestrator.architecture_map import render_architecture_html
from rfp_orchestrator.safety import SAFETY_NOTICE_BODY, SAFETY_NOTICE_TITLE
from rfp_orchestrator.ui import (
    DOCX_MIME_TYPE,
    SESSION_ATTEMPT_COUNTS,
    SESSION_EDGE_STATUS,
    SESSION_LATEST_STATE,
    SESSION_NODE_STATUS,
    build_docx_download,
)

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app.py"
MANIFEST = ROOT / "data" / "fixtures" / "demo_cases_v1.json"
SPECIALIST_NODE = {
    "product": "product_specialist",
    "security": "security_specialist",
    "implementation": "implementation_specialist",
}


def _rendered_nodes_and_edges(fragment: str) -> tuple[dict[str, str], dict[str, str]]:
    root = ElementTree.fromstring(f"<root>{fragment}</root>")
    svg = root.find("div/svg")
    assert svg is not None
    nodes = {
        item.attrib["data-node"]: item.attrib["data-status"]
        for item in svg.findall("g")
    }
    edges = {
        item.attrib["data-edge"]: item.attrib["data-status"]
        for item in svg.findall("path")
        if "data-edge" in item.attrib
    }
    return nodes, edges


def test_every_frozen_demo_map_and_download_matches_saved_state() -> None:
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]

    with patch("rfp_orchestrator.ui.sleep"):
        app = AppTest.from_file(str(APP)).run(timeout=10)
        assert not app.exception

        for case in cases:
            app.sidebar.selectbox[0].select(case["requirement_id"]).run(timeout=10)
            app.sidebar.button[0].click().run(timeout=10)
            assert not app.exception
            assert len(app.get("iframe")) == 1
            assert len(app.get("download_button")) == 1

            state = app.session_state[SESSION_LATEST_STATE]
            node_status = dict(app.session_state[SESSION_NODE_STATUS])
            edge_status = dict(app.session_state[SESSION_EDGE_STATUS])
            attempt_counts = dict(app.session_state[SESSION_ATTEMPT_COUNTS])
            fragment = render_architecture_html(
                node_status,
                edge_status=edge_status,
                attempt_counts=attempt_counts,
            )
            nodes, edges = _rendered_nodes_and_edges(fragment)

            assert len(nodes) == 21
            assert node_status == {
                node: status for node, status in nodes.items()
            }
            assert all(status != "active" for status in nodes.values())
            assert attempt_counts == {
                "recovery_attempt": case["expected_retries"],
                "conflict_reanalysis_attempt": case[
                    "expected_conflict_reanalyses"
                ],
            }
            assert f"Attempts: {case['expected_retries']}/2" in fragment
            assert (
                f"Attempts: {case['expected_conflict_reanalyses']}/1"
                in fragment
            )

            for domain, node in SPECIALIST_NODE.items():
                expected = (
                    "complete"
                    if domain in case["expected_specialists"]
                    else "inactive"
                )
                assert nodes[node] == expected
                edge = f"{node}--merge"
                assert edges[edge] == expected

            if case["expected_final_answer"]:
                assert nodes["finalization_guard"] == "complete"
                assert nodes["human_review_interrupt"] == "inactive"
            else:
                assert nodes["finalization_guard"] == "inactive"
                assert nodes["human_review_interrupt"] == "blocked"

            saved_state = deepcopy(state)
            artifact = build_docx_download(state)
            assert state == saved_state
            assert artifact.file_name == (
                f"northstar-rfp-response-{case['requirement_id'].lower()}.docx"
            )
            assert artifact.mime_type == DOCX_MIME_TYPE
            with ZipFile(BytesIO(artifact.data)) as package:
                assert package.testzip() is None
                assert "word/document.xml" in package.namelist()

            document = Document(BytesIO(artifact.data))
            body = "\n".join(paragraph.text for paragraph in document.paragraphs)
            assert case["requirement_text"] in body
            assert f"Requirement {case['requirement_id']} | " in body
            assert f"{SAFETY_NOTICE_TITLE}. {SAFETY_NOTICE_BODY}" in body
            assert "Evidence and support" in body
            assert "Approval notes" in body
            if case["expected_final_answer"]:
                assert "Final response" in body
                assert state["final_answer"] in body
            else:
                assert "Current status" in body
                assert "No final response has been authorized." in body
                assert state["final_answer"] is None
