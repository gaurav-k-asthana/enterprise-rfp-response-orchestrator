import json
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from rfp_orchestrator.config import Settings
from rfp_orchestrator.corpus import load_corpus_chunks
from rfp_orchestrator.ingestion import (
    DEFAULT_CORPUS_DIRECTORY,
    EMBEDDING_DIMENSION,
    UPLOAD_APPROVAL_TOKEN,
    BM25SparseEncoder,
    IngestionApprovalError,
    IngestionConfigurationError,
    IngestionManifestMismatchError,
    IngestionProviderResponseError,
    build_ingestion_plan,
    execute_reviewed_ingestion,
    load_reviewed_manifest,
    validate_runtime_settings,
    write_manifest,
)
from rfp_orchestrator.ingestion_cli import prepare_main, upload_main
from rfp_orchestrator.models import Domain


def configured_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "openai_api_key": "sk-test-secret-never-display",
        "openai_embedding_model": "text-embedding-3-small",
        "pinecone_api_key": "pcsk-test-secret-never-display",
        "pinecone_index": "rfp-agentic-ai-v1",
        "pinecone_namespace": "northstar-v1",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


class FakeEmbeddings:
    def __init__(self, *, record_count: int, dimensions: int = EMBEDDING_DIMENSION) -> None:
        self.record_count = record_count
        self.dimensions = dimensions
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        return SimpleNamespace(
            data=[
                SimpleNamespace(index=index, embedding=[float(index + 1)] * self.dimensions)
                for index in range(self.record_count)
            ],
            model="text-embedding-3-small",
            usage=SimpleNamespace(prompt_tokens=321, total_tokens=321),
        )


class FakeOpenAIClient:
    def __init__(self, embeddings: FakeEmbeddings) -> None:
        self.embeddings = embeddings


class FakeIndex:
    def __init__(self, *, confirmed_count: int | None = None) -> None:
        self.confirmed_count = confirmed_count
        self.upserts: list[dict[str, Any]] = []

    def upsert(self, **kwargs: Any) -> SimpleNamespace:
        self.upserts.append(kwargs)
        count = self.confirmed_count
        if count is None:
            count = len(kwargs["vectors"])
        return SimpleNamespace(upserted_count=count)


def test_plan_and_manifest_are_deterministic_and_match_frozen_configuration() -> None:
    first = build_ingestion_plan()
    second = build_ingestion_plan()
    first_manifest = first.public_manifest()
    second_manifest = second.public_manifest()

    assert first_manifest == second_manifest
    assert first_manifest["document_count"] == 12
    assert first_manifest["record_count"] == len(first.records)
    assert first_manifest["record_count"] <= 100
    assert first_manifest["openai"] == {
        "model": "text-embedding-3-small",
        "dimensions": 1_536,
        "encoding_format": "float",
        "planned_requests_if_approved": 1,
    }
    assert first_manifest["pinecone"] == {
        "index": "rfp-agentic-ai-v1",
        "namespace": "northstar-v1",
        "vector_type": "dense",
        "metric": "dotproduct",
        "cloud": "aws",
        "region": "us-east-1",
        "planned_upsert_requests_if_approved": 1,
    }
    assert first_manifest["network_calls_made"] == 0
    assert first_manifest["upload_authorized"] is False


def test_product_and_security_records_have_sparse_vectors_but_implementation_does_not() -> None:
    plan = build_ingestion_plan()

    hybrid_records = [
        record
        for record in plan.records
        if record.metadata["domain"] in {Domain.PRODUCT.value, Domain.SECURITY.value}
    ]
    dense_only_records = [
        record
        for record in plan.records
        if record.metadata["domain"] == Domain.IMPLEMENTATION.value
    ]

    assert hybrid_records
    assert dense_only_records
    assert all(record.sparse_vector is not None for record in hybrid_records)
    assert all(record.sparse_vector is None for record in dense_only_records)
    assert all(
        len(record.sparse_vector.indices) == len(record.sparse_vector.values)
        for record in hybrid_records
        if record.sparse_vector is not None
    )


def test_sparse_encoder_is_repeatable_and_uses_known_query_terms() -> None:
    plan = build_ingestion_plan()
    chunks = load_corpus_chunks(DEFAULT_CORPUS_DIRECTORY)
    first = BM25SparseEncoder(chunks)
    second = BM25SparseEncoder(chunks)

    assert first.digest == second.digest == plan.sparse_encoder_sha256
    assert first.vocabulary_size == second.vocabulary_size
    query = first.encode_query(Domain.PRODUCT, "SAML SCIM unknown-never-indexed")
    assert query.indices
    assert query.values == tuple(1.0 for _ in query.indices)


def test_record_metadata_contains_complete_provenance_without_absolute_paths() -> None:
    plan = build_ingestion_plan()
    required = {
        "chunk_id",
        "chunk_index",
        "doc_id",
        "domain",
        "title",
        "text",
        "version",
        "effective_date",
        "authority_rank",
        "source_status",
        "source_file",
    }

    assert all(set(record.metadata) == required for record in plan.records)
    assert all("/Users/" not in str(record.metadata) for record in plan.records)


def test_manifest_file_is_safe_and_round_trips(tmp_path: Path) -> None:
    plan = build_ingestion_plan()
    path = tmp_path / "manifest.json"
    manifest = write_manifest(plan, path)
    saved = load_reviewed_manifest(path)

    assert saved == manifest
    serialized = path.read_text(encoding="utf-8")
    assert "sk-test" not in serialized
    assert "pcsk-test" not in serialized
    assert '"values"' not in serialized
    assert '"embedding_input"' not in serialized


def test_prepare_cli_makes_only_a_local_dry_run(tmp_path: Path) -> None:
    output = StringIO()
    error = StringIO()
    manifest_path = tmp_path / "manifest.json"

    exit_code = prepare_main(
        ["--output", str(manifest_path)],
        settings=Settings(_env_file=None),
        output_stream=output,
        error_stream=error,
    )

    assert exit_code == 0
    assert error.getvalue() == ""
    summary = json.loads(output.getvalue())
    assert summary["status"] == "dry_run_ready"
    assert summary["network_calls_made"] == 0
    assert summary["upload_authorized"] is False
    assert manifest_path.is_file()


@pytest.mark.parametrize(
    ("overrides", "expected_variable"),
    [
        ({"openai_embedding_model": "wrong-model"}, "OPENAI_EMBEDDING_MODEL"),
        ({"pinecone_index": "wrong-index"}, "PINECONE_INDEX"),
        ({"pinecone_namespace": "wrong-namespace"}, "PINECONE_NAMESPACE"),
    ],
)
def test_runtime_configuration_drift_fails_closed(
    overrides: dict[str, object], expected_variable: str
) -> None:
    with pytest.raises(IngestionConfigurationError, match=expected_variable):
        validate_runtime_settings(configured_settings(**overrides), require_secrets=True)


def test_upload_refuses_missing_approval_before_provider_initialization() -> None:
    plan = build_ingestion_plan()
    manifest = plan.public_manifest()
    openai_calls = 0
    pinecone_calls = 0

    def openai_factory(api_key: str) -> FakeOpenAIClient:
        nonlocal openai_calls
        openai_calls += 1
        return FakeOpenAIClient(FakeEmbeddings(record_count=len(plan.records)))

    def pinecone_factory(api_key: str, index_name: str) -> FakeIndex:
        nonlocal pinecone_calls
        pinecone_calls += 1
        return FakeIndex()

    with pytest.raises(IngestionApprovalError, match="approval token"):
        execute_reviewed_ingestion(
            plan=plan,
            reviewed_manifest=manifest,
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
            approval_token="",
            settings=configured_settings(),
            openai_client_factory=openai_factory,
            pinecone_index_factory=pinecone_factory,
        )

    assert openai_calls == 0
    assert pinecone_calls == 0


def test_upload_refuses_stale_manifest_before_provider_initialization() -> None:
    plan = build_ingestion_plan()
    manifest = plan.public_manifest()
    stale_manifest = dict(manifest)
    stale_manifest["record_count"] = int(manifest["record_count"]) + 1
    client_calls = 0

    def openai_factory(api_key: str) -> FakeOpenAIClient:
        nonlocal client_calls
        client_calls += 1
        return FakeOpenAIClient(FakeEmbeddings(record_count=len(plan.records)))

    with pytest.raises(IngestionManifestMismatchError, match="changed after"):
        execute_reviewed_ingestion(
            plan=plan,
            reviewed_manifest=stale_manifest,
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
            approval_token=UPLOAD_APPROVAL_TOKEN,
            settings=configured_settings(),
            openai_client_factory=openai_factory,
            pinecone_index_factory=lambda api_key, index_name: FakeIndex(),
        )

    assert client_calls == 0


def test_approved_fake_execution_makes_one_embedding_request_and_one_upsert() -> None:
    plan = build_ingestion_plan()
    manifest = plan.public_manifest()
    embeddings = FakeEmbeddings(record_count=len(plan.records))
    openai_client = FakeOpenAIClient(embeddings)
    index = FakeIndex()
    observed_openai_key = ""
    observed_pinecone: tuple[str, str] | None = None

    def openai_factory(api_key: str) -> FakeOpenAIClient:
        nonlocal observed_openai_key
        observed_openai_key = api_key
        return openai_client

    def pinecone_factory(api_key: str, index_name: str) -> FakeIndex:
        nonlocal observed_pinecone
        observed_pinecone = (api_key, index_name)
        return index

    result = execute_reviewed_ingestion(
        plan=plan,
        reviewed_manifest=manifest,
        expected_manifest_sha256=str(manifest["manifest_sha256"]),
        approval_token=UPLOAD_APPROVAL_TOKEN,
        settings=configured_settings(),
        openai_client_factory=openai_factory,
        pinecone_index_factory=pinecone_factory,
    )

    assert observed_openai_key == "sk-test-secret-never-display"
    assert observed_pinecone == (
        "pcsk-test-secret-never-display",
        "rfp-agentic-ai-v1",
    )
    assert len(embeddings.requests) == 1
    assert embeddings.requests[0]["model"] == "text-embedding-3-small"
    assert embeddings.requests[0]["encoding_format"] == "float"
    assert len(index.upserts) == 1
    assert index.upserts[0]["namespace"] == "northstar-v1"
    assert len(index.upserts[0]["vectors"]) == len(plan.records)
    assert result.status == "uploaded"
    assert result.openai_request_count == 1
    assert result.pinecone_upsert_request_count == 1
    assert "secret" not in str(result.public_fields()).lower()

    records_by_domain = {
        record["metadata"]["domain"]: record for record in index.upserts[0]["vectors"]
    }
    assert "sparse_values" in records_by_domain[Domain.PRODUCT.value]
    assert "sparse_values" in records_by_domain[Domain.SECURITY.value]
    assert "sparse_values" not in records_by_domain[Domain.IMPLEMENTATION.value]


def test_embedding_dimension_mismatch_stops_before_upsert() -> None:
    plan = build_ingestion_plan()
    manifest = plan.public_manifest()
    index = FakeIndex()

    with pytest.raises(IngestionProviderResponseError, match="dimension"):
        execute_reviewed_ingestion(
            plan=plan,
            reviewed_manifest=manifest,
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
            approval_token=UPLOAD_APPROVAL_TOKEN,
            settings=configured_settings(),
            openai_client_factory=lambda api_key: FakeOpenAIClient(
                FakeEmbeddings(record_count=len(plan.records), dimensions=12)
            ),
            pinecone_index_factory=lambda api_key, index_name: index,
        )

    assert index.upserts == []


def test_upsert_count_mismatch_fails_without_retry() -> None:
    plan = build_ingestion_plan()
    manifest = plan.public_manifest()
    index = FakeIndex(confirmed_count=len(plan.records) - 1)

    with pytest.raises(IngestionProviderResponseError, match="do not retry"):
        execute_reviewed_ingestion(
            plan=plan,
            reviewed_manifest=manifest,
            expected_manifest_sha256=str(manifest["manifest_sha256"]),
            approval_token=UPLOAD_APPROVAL_TOKEN,
            settings=configured_settings(),
            openai_client_factory=lambda api_key: FakeOpenAIClient(
                FakeEmbeddings(record_count=len(plan.records))
            ),
            pinecone_index_factory=lambda api_key, index_name: index,
        )

    assert len(index.upserts) == 1


def test_upload_cli_without_execute_never_initializes_providers() -> None:
    output = StringIO()
    error = StringIO()
    provider_calls = 0

    def openai_factory(api_key: str) -> FakeOpenAIClient:
        nonlocal provider_calls
        provider_calls += 1
        return FakeOpenAIClient(FakeEmbeddings(record_count=1))

    exit_code = upload_main(
        [],
        settings=Settings(_env_file=None),
        openai_client_factory=openai_factory,
        pinecone_index_factory=lambda api_key, index_name: FakeIndex(),
        output_stream=output,
        error_stream=error,
    )

    assert exit_code == 2
    assert output.getvalue() == ""
    assert "--execute" in error.getvalue()
    assert provider_calls == 0
