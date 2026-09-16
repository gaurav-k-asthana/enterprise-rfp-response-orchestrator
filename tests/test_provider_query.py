from pathlib import Path
from typing import Any

import pytest

from rfp_orchestrator.corpus import load_corpus_chunks
from rfp_orchestrator.ingestion import BM25SparseEncoder
from rfp_orchestrator.models import Domain
from rfp_orchestrator.provider_config import EMBEDDING_DIMENSION
from rfp_orchestrator.provider_query import (
    OpenAIPineconeQueryBuilder,
    ProviderQueryError,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


class FakeEmbeddings:
    def __init__(self, response: dict[str, Any]) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return self.response


class FakeOpenAI:
    def __init__(self, response: dict[str, Any]) -> None:
        self.embeddings = FakeEmbeddings(response)


def embedding_response(*, dimensions: int = EMBEDDING_DIMENSION) -> dict[str, Any]:
    return {
        "model": "text-embedding-3-small",
        "data": [{"index": 0, "embedding": [0.5] * dimensions}],
        "usage": {"prompt_tokens": 7, "total_tokens": 7},
    }


def sparse_encoder() -> BM25SparseEncoder:
    return BM25SparseEncoder(load_corpus_chunks(KB_DIRECTORY))


@pytest.mark.parametrize("domain", [Domain.PRODUCT, Domain.SECURITY])
def test_hybrid_query_scales_dense_and_sparse_vectors(domain: Domain) -> None:
    fake = FakeOpenAI(embedding_response())
    builder = OpenAIPineconeQueryBuilder(
        domain=domain,
        api_key="test-key-not-live",
        sparse_encoder=sparse_encoder(),
        client_factory=lambda api_key: fake,
    )

    payload = builder("SAML TLS retention")

    assert payload["vector"] == [0.2] * EMBEDDING_DIMENSION
    assert payload["sparse_vector"]["indices"]
    assert set(payload["sparse_vector"]["values"]) == {0.6}
    assert fake.embeddings.calls == [
        {
            "model": "text-embedding-3-small",
            "input": "SAML TLS retention",
            "encoding_format": "float",
            "dimensions": EMBEDDING_DIMENSION,
        }
    ]
    assert builder.request_count == 1
    assert builder.last_usage is not None
    assert builder.last_usage.input_tokens == 7
    assert builder.last_usage.dimensions == EMBEDDING_DIMENSION


def test_implementation_query_is_dense_only_and_unscaled() -> None:
    fake = FakeOpenAI(embedding_response())
    builder = OpenAIPineconeQueryBuilder(
        domain=Domain.IMPLEMENTATION,
        api_key="test-key-not-live",
        client_factory=lambda api_key: fake,
    )

    payload = builder("How long does onboarding take?")

    assert payload == {"vector": [0.5] * EMBEDDING_DIMENSION}
    assert "sparse_vector" not in payload


def test_query_builder_is_lazy_until_the_first_query() -> None:
    factory_calls = 0

    def factory(api_key: str) -> FakeOpenAI:
        nonlocal factory_calls
        factory_calls += 1
        return FakeOpenAI(embedding_response())

    builder = OpenAIPineconeQueryBuilder(
        domain=Domain.IMPLEMENTATION,
        api_key="test-key-not-live",
        client_factory=factory,
    )

    assert builder.is_initialized is False
    assert factory_calls == 0

    builder("implementation timeline")

    assert builder.is_initialized is True
    assert factory_calls == 1
    assert builder.request_count == 1


def test_unknown_sparse_terms_fall_back_to_dense_signal() -> None:
    builder = OpenAIPineconeQueryBuilder(
        domain=Domain.PRODUCT,
        api_key="test-key-not-live",
        sparse_encoder=sparse_encoder(),
        client_factory=lambda api_key: FakeOpenAI(embedding_response()),
    )

    payload = builder("zyxwvutsrqponmlkjihgfedcba")

    assert "vector" in payload
    assert "sparse_vector" not in payload


@pytest.mark.parametrize(
    "response",
    [
        {"model": "wrong-model", "data": [{"embedding": [0.5] * EMBEDDING_DIMENSION}]},
        {
            "model": "text-embedding-3-small",
            "data": [],
            "usage": {"prompt_tokens": 7, "total_tokens": 7},
        },
        embedding_response(dimensions=3),
    ],
)
def test_query_builder_rejects_invalid_openai_responses(response: dict[str, Any]) -> None:
    builder = OpenAIPineconeQueryBuilder(
        domain=Domain.IMPLEMENTATION,
        api_key="test-key-not-live",
        client_factory=lambda api_key: FakeOpenAI(response),
    )

    with pytest.raises(ProviderQueryError):
        builder("implementation timeline")


def test_hybrid_query_requires_sparse_encoder_before_any_client_exists() -> None:
    factory_calls = 0

    def factory(api_key: str) -> FakeOpenAI:
        nonlocal factory_calls
        factory_calls += 1
        return FakeOpenAI(embedding_response())

    with pytest.raises(ValueError, match="sparse encoder"):
        OpenAIPineconeQueryBuilder(
            domain=Domain.SECURITY,
            api_key="test-key-not-live",
            client_factory=factory,
        )
    assert factory_calls == 0


@pytest.mark.parametrize(
    "usage",
    [
        None,
        {"prompt_tokens": -1, "total_tokens": -1},
        {"prompt_tokens": 7, "total_tokens": 8},
        {"prompt_tokens": "7", "total_tokens": 7},
    ],
)
def test_query_builder_rejects_missing_invalid_or_inexact_usage(
    usage: object,
) -> None:
    provider_response = embedding_response()
    provider_response["usage"] = usage
    builder = OpenAIPineconeQueryBuilder(
        domain=Domain.IMPLEMENTATION,
        api_key="test-key-not-live",
        client_factory=lambda api_key: FakeOpenAI(provider_response),
    )

    with pytest.raises(ProviderQueryError, match="token usage"):
        builder("implementation timeline")

    assert builder.request_count == 1
    assert builder.usage_receipts == ()
