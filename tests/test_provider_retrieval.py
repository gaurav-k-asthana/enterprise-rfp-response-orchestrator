from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from rfp_orchestrator.corpus import load_corpus_chunks
from rfp_orchestrator.ingestion import BM25SparseEncoder
from rfp_orchestrator.models import Domain
from rfp_orchestrator.pinecone_adapter import PineconeRetrieverAdapter
from rfp_orchestrator.provider_config import EMBEDDING_DIMENSION
from rfp_orchestrator.provider_query import OpenAIPineconeQueryBuilder
from rfp_orchestrator.provider_retrieval import (
    InstrumentedProviderRetriever,
    ProviderRetrievalCallError,
    ProviderRetrievalDisabledError,
    ProviderRetrievalSession,
    ProviderRetrievalSessionClosedError,
    ProviderRetrievalStatus,
    build_provider_retrieval_session,
)
from rfp_orchestrator.retrieval import RetrievalMethod

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


class FakeEmbeddings:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("secret embedding provider payload")
        return {
            "model": "text-embedding-3-small",
            "data": [{"index": 0, "embedding": [0.5] * EMBEDDING_DIMENSION}],
            "usage": {"prompt_tokens": 9, "total_tokens": 9},
        }


class FakeOpenAI:
    def __init__(self, embeddings: FakeEmbeddings) -> None:
        self.embeddings = embeddings


class FakeIndex:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.queries: list[dict[str, Any]] = []

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.queries.append(kwargs)
        if self.fail:
            raise RuntimeError("secret Pinecone provider payload")
        domain = kwargs["filter"]["domain"]["$eq"]
        prefix = {
            "product": "PROD-CAP-001",
            "security": "SEC-CTRL-001",
            "implementation": "IMPL-GUIDE-001",
        }[domain]
        return {
            "matches": [
                {
                    "id": f"{prefix}::chunk-001",
                    "score": 0.9,
                    "metadata": {
                        "doc_id": prefix,
                        "domain": domain,
                        "title": "Provider Fixture",
                        "text": "Synthetic provider evidence passage.",
                        "version": "1.0",
                        "effective_date": "2026-07-01",
                        "authority_rank": 5,
                        "source_status": "current",
                    },
                }
            ]
        }


def backend(
    domain: Domain,
    *,
    embeddings: FakeEmbeddings | None = None,
    index: FakeIndex | None = None,
) -> tuple[InstrumentedProviderRetriever, FakeEmbeddings, FakeIndex]:
    fake_embeddings = embeddings or FakeEmbeddings()
    fake_index = index or FakeIndex()
    kwargs: dict[str, object] = {
        "domain": domain,
        "api_key": "test-openai-key",
        "client_factory": lambda api_key: FakeOpenAI(fake_embeddings),
    }
    if domain in {Domain.PRODUCT, Domain.SECURITY}:
        kwargs["sparse_encoder"] = BM25SparseEncoder(load_corpus_chunks(KB_DIRECTORY))
    builder = OpenAIPineconeQueryBuilder(**kwargs)
    adapter = PineconeRetrieverAdapter(
        domain=domain,
        namespace="northstar-v1",
        query_builder=builder,
        index_factory=lambda: fake_index,
    )
    return (
        InstrumentedProviderRetriever(query_builder=builder, adapter=adapter),
        fake_embeddings,
        fake_index,
    )


def session(
    *,
    enabled: bool = True,
    failing_embeddings_domain: Domain | None = None,
    failing_index_domain: Domain | None = None,
) -> tuple[ProviderRetrievalSession, dict[Domain, FakeEmbeddings], dict[Domain, FakeIndex]]:
    backends = {}
    embeddings_by_domain = {}
    indexes_by_domain = {}
    for domain in Domain:
        instrumented, embeddings, index = backend(
            domain,
            embeddings=FakeEmbeddings(fail=domain is failing_embeddings_domain),
            index=FakeIndex(fail=domain is failing_index_domain),
        )
        backends[domain] = instrumented
        embeddings_by_domain[domain] = embeddings
        indexes_by_domain[domain] = index
    return (
        ProviderRetrievalSession(backends, enabled=enabled),
        embeddings_by_domain,
        indexes_by_domain,
    )


def test_disabled_session_stops_before_any_provider_initialization() -> None:
    provider_session, embeddings, indexes = session(enabled=False)

    with pytest.raises(ProviderRetrievalDisabledError, match="exact paid command"):
        provider_session.search(Domain.PRODUCT, "SAML", k=5)

    assert provider_session.operations == ()
    assert all(fake.calls == [] for fake in embeddings.values())
    assert all(fake.queries == [] for fake in indexes.values())


@pytest.mark.parametrize(
    ("domain", "expected_method", "expects_sparse"),
    [
        (Domain.PRODUCT, RetrievalMethod.HYBRID, True),
        (Domain.SECURITY, RetrievalMethod.HYBRID, True),
        (Domain.IMPLEMENTATION, RetrievalMethod.DENSE, False),
    ],
)
def test_session_enforces_domain_method_top_five_and_records_usage(
    domain: Domain,
    expected_method: RetrievalMethod,
    expects_sparse: bool,
) -> None:
    provider_session, embeddings, indexes = session()

    evidence = provider_session.search(domain, "SAML TLS implementation", k=5)
    operation = provider_session.operations[0]
    query = indexes[domain].queries[0]

    assert len(evidence) == 1
    assert evidence[0].domain is domain
    assert evidence[0].retrieval_method is expected_method
    assert operation.domain is domain
    assert operation.retrieval_method is expected_method
    assert operation.requested_k == 5
    assert operation.embedding_calls == 1
    assert operation.embedding_input_tokens == 9
    assert operation.pinecone_queries == 1
    assert operation.result_ids == [evidence[0].chunk_id]
    assert operation.status is ProviderRetrievalStatus.COMPLETE
    assert len(embeddings[domain].calls) == 1
    assert query["top_k"] == 5
    assert query["namespace"] == "northstar-v1"
    assert query["filter"] == {"domain": {"$eq": domain.value}}
    assert query["include_metadata"] is True
    assert query["include_values"] is False
    assert ("sparse_vector" in query) is expects_sparse


def test_both_architecture_views_use_the_same_three_session_tools() -> None:
    provider_session, _, _ = session()
    generalist = provider_session.domain_retrievers
    specialists = provider_session.specialist_retrievers

    assert list(generalist) == list(Domain)
    assert generalist[Domain.PRODUCT] is specialists.product
    assert generalist[Domain.SECURITY] is specialists.security
    assert generalist[Domain.IMPLEMENTATION] is specialists.implementation

    specialists.product.search("SAML")
    generalist[Domain.SECURITY].search("TLS")
    assert [item.domain for item in provider_session.operations] == [
        Domain.PRODUCT,
        Domain.SECURITY,
    ]


def test_operation_record_contains_no_key_host_vector_or_gold_fields() -> None:
    provider_session, _, _ = session()
    provider_session.search(Domain.PRODUCT, "SAML")

    payload = provider_session.operations[0].model_dump(mode="json")
    rendered = str(payload).lower()
    assert set(payload) == {
        "operation_id",
        "tool_name",
        "domain",
        "query",
        "requested_k",
        "retrieval_method",
        "namespace",
        "embedding_model",
        "embedding_dimensions",
        "embedding_calls",
        "embedding_input_tokens",
        "pinecone_queries",
        "result_ids",
        "status",
        "error_code",
    }
    assert "api_key" not in rendered
    assert "host" not in rendered
    assert "vector" not in rendered
    assert "gold" not in rendered
    assert "expected" not in rendered


def test_operation_ids_and_counts_are_append_only_per_session() -> None:
    provider_session, _, _ = session()
    provider_session.search(Domain.PRODUCT, "SAML")
    provider_session.search(Domain.PRODUCT, "SCIM")

    assert [item.operation_id for item in provider_session.operations] == [
        "retrieval-001",
        "retrieval-002",
    ]
    assert [item.embedding_calls for item in provider_session.operations] == [1, 1]
    assert [item.pinecone_queries for item in provider_session.operations] == [1, 1]


def test_embedding_failure_is_recorded_and_redacted_before_pinecone() -> None:
    provider_session, _, indexes = session(
        failing_embeddings_domain=Domain.SECURITY
    )

    with pytest.raises(ProviderRetrievalCallError) as captured:
        provider_session.search(Domain.SECURITY, "TLS")

    operation = provider_session.operations[0]
    assert str(captured.value) == (
        "provider retrieval failed for the security evidence tool"
    )
    assert operation.status is ProviderRetrievalStatus.FAILED
    assert operation.error_code == "PROVIDER_RETRIEVAL_FAILED"
    assert operation.embedding_calls == 1
    assert operation.embedding_input_tokens is None
    assert operation.pinecone_queries == 0
    assert operation.result_ids == []
    assert indexes[Domain.SECURITY].queries == []
    assert "secret" not in str(captured.value).lower()


def test_failed_embedding_does_not_reuse_a_prior_successful_usage_receipt() -> None:
    provider_session, embeddings, _ = session()
    provider_session.search(Domain.SECURITY, "TLS")
    embeddings[Domain.SECURITY].fail = True

    with pytest.raises(ProviderRetrievalCallError):
        provider_session.search(Domain.SECURITY, "SOC 2")

    successful, failed = provider_session.operations
    assert successful.embedding_input_tokens == 9
    assert failed.embedding_calls == 1
    assert failed.embedding_input_tokens is None
    assert failed.pinecone_queries == 0


def test_pinecone_failure_preserves_embedding_usage_and_is_redacted() -> None:
    provider_session, _, _ = session(failing_index_domain=Domain.PRODUCT)

    with pytest.raises(ProviderRetrievalCallError) as captured:
        provider_session.search(Domain.PRODUCT, "SAML")

    operation = provider_session.operations[0]
    assert operation.status is ProviderRetrievalStatus.FAILED
    assert operation.embedding_calls == 1
    assert operation.embedding_input_tokens == 9
    assert operation.pinecone_queries == 1
    assert "secret" not in str(captured.value).lower()


@pytest.mark.parametrize("invalid_k", [0, 6])
def test_invalid_top_k_stops_before_providers_and_is_not_an_operation(
    invalid_k: int,
) -> None:
    provider_session, embeddings, indexes = session()

    with pytest.raises(ValueError, match="between 1 and 5"):
        provider_session.search(Domain.PRODUCT, "SAML", k=invalid_k)

    assert provider_session.operations == ()
    assert all(fake.calls == [] for fake in embeddings.values())
    assert all(fake.queries == [] for fake in indexes.values())


def test_closed_session_stops_before_providers() -> None:
    provider_session, embeddings, indexes = session()
    provider_session.close()

    with pytest.raises(ProviderRetrievalSessionClosedError, match="closed"):
        provider_session.search(Domain.PRODUCT, "SAML")

    assert provider_session.operations == ()
    assert all(fake.calls == [] for fake in embeddings.values())
    assert all(fake.queries == [] for fake in indexes.values())


def test_production_session_factory_is_lazy() -> None:
    openai_factory_calls = 0
    index_factory_calls = 0

    def openai_factory(api_key: str) -> FakeOpenAI:
        nonlocal openai_factory_calls
        openai_factory_calls += 1
        return FakeOpenAI(FakeEmbeddings())

    def index_factory() -> FakeIndex:
        nonlocal index_factory_calls
        index_factory_calls += 1
        return FakeIndex()

    provider_session = build_provider_retrieval_session(
        openai_api_key="test-openai-key",
        pinecone_api_key="test-pinecone-key",
        enabled=False,
        openai_client_factory=openai_factory,
        index_factory=index_factory,
    )

    assert provider_session.operations == ()
    assert openai_factory_calls == 0
    assert index_factory_calls == 0
