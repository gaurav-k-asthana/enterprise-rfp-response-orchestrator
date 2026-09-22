from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_public_release_claims_match_approved_evidence() -> None:
    approval = json.loads(
        (ROOT / "data/evaluation/provider_evaluation_final_approval_step_4_g8.json").read_text()
    )
    readme = (ROOT / "README.md").read_text()
    metrics = (ROOT / "docs/evaluation_metrics_v1.md").read_text()
    audit = (ROOT / "docs/final_claim_audit_v1.md").read_text()
    report_builder = (ROOT / "scripts/build_project_report.py").read_text()

    assert approval["decision"] == "APPROVED"
    assert approval["bounded_preference"] == "single_generalist_for_frozen_v1"
    assert approval["universal_multi_agent_superiority_claim_approved"] is False
    assert approval["production_readiness_claim_approved"] is False

    for expected in (
        "20/24 (83.3%)",
        "10/24 (41.7%)",
        "24/24",
        "20/24",
        "$0.814364",
    ):
        assert expected in readme
        assert expected in audit

    for digest in (
        approval["analysis_json_sha256"],
        approval["analysis_markdown_sha256"],
    ):
        assert digest in metrics
        assert digest in audit

    assert "final reviewed V1 release  |  tag v0.1.0" in report_builder
    assert "submission draft" not in readme.lower()
    assert "submission-draft" not in report_builder.lower()


def test_release_audit_keeps_required_limitations_visible() -> None:
    combined = "\n".join(
        (
            (ROOT / "README.md").read_text(),
            (ROOT / "docs/final_claim_audit_v1.md").read_text(),
            (ROOT / "scripts/build_project_report.py").read_text(),
        )
    )

    for limitation in (
        "RFP-006",
        "RFP-015",
        "zero conflict-detection F1",
        "repeat variability is inconclusive",
        "not a production",
    ):
        assert limitation.lower() in combined.lower()


def test_release_manifest_binds_public_submission_artifacts() -> None:
    manifest = json.loads((ROOT / "docs/release_manifest_v0.1.0.json").read_text())

    assert manifest["release"] == "v0.1.0"
    assert manifest["production_readiness_claimed"] is False
    assert manifest["provider_calls_during_release_checks"] == 0
    assert manifest["verification"]["pytest"] == "1312 passed"
    assert manifest["verification"]["streamlit_clean_start_http_status"] == 200

    for artifact in manifest["artifacts"]:
        path = ROOT / artifact["path"]
        assert path.is_file()
        assert sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
