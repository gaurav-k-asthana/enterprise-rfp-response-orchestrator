from pathlib import Path

from rfp_orchestrator.inspect_retrieval import render_report, run_inspection
from rfp_orchestrator.models import Domain

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


def test_inspection_results_cover_domains_conflict_and_implementation() -> None:
    results = run_inspection(KB_DIRECTORY)

    assert all(item.domain is Domain.PRODUCT for item in results["Product"])
    assert results["Product"][0].doc_id in {"PROD-CAP-001", "PROD-AVAIL-001"}

    security_ids = {item.doc_id for item in results["Security/Compliance"]}
    assert {"SEC-RET-001", "SEC-RET-OPS-001"} <= security_ids
    assert all(item.domain is Domain.SECURITY for item in results["Security/Compliance"])

    implementation = results["Implementation"]
    assert implementation
    assert all(item.domain is Domain.IMPLEMENTATION for item in implementation)
    implementation_text = " ".join(item.text.lower() for item in implementation)
    assert "six to eight weeks" in implementation_text
    assert "executive sponsor" in implementation_text


def test_inspection_report_exposes_review_fields_without_provider_claims() -> None:
    report = render_report(run_inspection(KB_DIRECTORY))

    assert "Citation ID" in report
    assert "Authority" in report
    assert "Status" in report
    assert "Effective date" in report
    assert "semantic_substitute" in report
    assert "zero OpenAI or Pinecone calls" in report
    assert "30 calendar days" in report
    assert "90-calendar-day" in report
    assert "six to eight weeks" in report
    assert "executive sponsor" in report
