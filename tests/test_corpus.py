from pathlib import Path

import pytest

from rfp_orchestrator.corpus import (
    CorpusValidationError,
    SourceStatus,
    chunk_document,
    load_corpus_chunks,
    load_source_document,
    load_source_documents,
)
from rfp_orchestrator.models import Domain

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


def source_text(**overrides: str) -> str:
    metadata = {
        "doc_id": "TEST-DOC-001",
        "domain": "product",
        "title": "Test Source",
        "version": "1.0",
        "effective_date": "2026-08-29",
        "authority_rank": "3",
        "status": "current",
    }
    metadata.update(overrides)
    front_matter = "\n".join(f"{key}: {value}" for key, value in metadata.items())
    return f"---\n{front_matter}\n---\n\nFirst paragraph.\n\nSecond paragraph.\n"


def test_loads_all_kb_sources_with_typed_metadata() -> None:
    documents = load_source_documents(KB_DIRECTORY)

    assert len(documents) == 12
    assert {document.doc_id for document in documents} == {
        "IMPL-GUIDE-001",
        "POLICY-AUTH-001",
        "POLICY-EVID-001",
        "PROD-AVAIL-001",
        "PROD-CAP-001",
        "PROD-DEPLOY-001",
        "PROD-SLA-001",
        "SEC-CTRL-001",
        "SEC-CTRL-OLD-001",
        "SEC-DATA-001",
        "SEC-RET-001",
        "SEC-RET-OPS-001",
    }
    product = next(document for document in documents if document.doc_id == "PROD-AVAIL-001")
    assert product.domain is Domain.PRODUCT
    assert product.status is SourceStatus.CURRENT
    assert product.authority_rank == 5


def test_chunk_ids_are_identical_across_repeated_loads() -> None:
    first_ids = [chunk.chunk_id for chunk in load_corpus_chunks(KB_DIRECTORY, max_chars=120)]
    second_ids = [chunk.chunk_id for chunk in load_corpus_chunks(KB_DIRECTORY, max_chars=120)]

    assert first_ids == second_ids
    assert first_ids
    assert all("::chunk-" in chunk_id for chunk_id in first_ids)


def test_chunking_preserves_provenance(tmp_path: Path) -> None:
    path = tmp_path / "valid.md"
    path.write_text(source_text(), encoding="utf-8")

    document = load_source_document(path)
    chunks = chunk_document(document, max_chars=20)

    assert [chunk.chunk_id for chunk in chunks] == [
        "TEST-DOC-001::chunk-001",
        "TEST-DOC-001::chunk-002",
    ]
    assert all(chunk.doc_id == document.doc_id for chunk in chunks)
    assert all(chunk.source_path == path for chunk in chunks)


@pytest.mark.parametrize(
    "missing_field",
    [
        "doc_id",
        "domain",
        "title",
        "version",
        "effective_date",
        "authority_rank",
        "status",
    ],
)
def test_rejects_each_missing_required_metadata_field(
    tmp_path: Path, missing_field: str
) -> None:
    path = tmp_path / f"missing-{missing_field}.md"
    text = source_text()
    text = "\n".join(
        line for line in text.splitlines() if not line.startswith(f"{missing_field}:")
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(CorpusValidationError, match=missing_field):
        load_source_document(path)


@pytest.mark.parametrize(
    ("override", "message"),
    [
        ({"domain": "finance"}, "domain"),
        ({"effective_date": "not-a-date"}, "effective_date"),
        ({"authority_rank": "6"}, "authority_rank"),
        ({"status": "draft"}, "status"),
    ],
)
def test_rejects_invalid_metadata_values(
    tmp_path: Path, override: dict[str, str], message: str
) -> None:
    path = tmp_path / "invalid.md"
    path.write_text(source_text(**override), encoding="utf-8")

    with pytest.raises(CorpusValidationError, match=message):
        load_source_document(path)


def test_rejects_duplicate_document_ids(tmp_path: Path) -> None:
    (tmp_path / "first.md").write_text(source_text(), encoding="utf-8")
    (tmp_path / "second.md").write_text(
        source_text(title="Second Source"), encoding="utf-8"
    )

    with pytest.raises(CorpusValidationError, match="duplicate doc_id 'TEST-DOC-001'"):
        load_source_documents(tmp_path)


def test_rejects_missing_front_matter(tmp_path: Path) -> None:
    path = tmp_path / "no-front-matter.md"
    path.write_text("This file has no metadata block.", encoding="utf-8")

    with pytest.raises(CorpusValidationError, match="opening '---'"):
        load_source_document(path)


def test_step_1_12_sources_are_substantive_and_multi_section() -> None:
    documents = load_source_documents(KB_DIRECTORY)

    assert all(len(document.text) >= 200 for document in documents)
    assert all(document.text.count("## ") >= 2 for document in documents)


def test_direct_conflict_preserves_both_equal_authority_current_values() -> None:
    documents = {document.doc_id: document for document in load_source_documents(KB_DIRECTORY)}
    standard = documents["SEC-RET-001"]
    operations = documents["SEC-RET-OPS-001"]

    assert standard.status is SourceStatus.CURRENT
    assert operations.status is SourceStatus.CURRENT
    assert standard.authority_rank == operations.authority_rank == 5
    assert "30 calendar days" in standard.text
    assert "90-calendar-day" in operations.text


def test_fedramp_high_has_no_supporting_trusted_source() -> None:
    trusted_text = "\n".join(
        document.text.lower() for document in load_source_documents(KB_DIRECTORY)
    )

    assert "fedramp" not in trusted_text


def test_expected_behavior_fixture_is_not_inside_trusted_kb() -> None:
    fixture_path = PROJECT_ROOT / "data" / "fixtures" / "expected_evidence_behaviors.md"

    assert fixture_path.is_file()
    fixture_text = fixture_path.read_text(encoding="utf-8")
    assert "FIX-MISSING-001" in fixture_text
    assert "FIX-CONFLICT-001" in fixture_text
    assert fixture_path.parent != KB_DIRECTORY
