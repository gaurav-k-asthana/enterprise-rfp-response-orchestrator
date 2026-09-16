"""Lazy, validated OpenAI query embeddings and Pinecone query payloads."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.ingestion import BM25SparseEncoder
from rfp_orchestrator.models import Domain
from rfp_orchestrator.provider_config import (
    EMBEDDING_DIMENSION,
    EMBEDDING_ENCODING,
    HYBRID_DENSE_WEIGHT,
    HYBRID_SPARSE_WEIGHT,
    OPENAI_EMBEDDING_MODEL,
)


class ProviderQueryError(RuntimeError):
    """Raised when query-vector configuration or provider output is unsafe."""


class QueryEmbeddingUsage(BaseModel):
    """Safe receipt for one query-embedding request; vector values are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_number: int = Field(ge=1)
    model: str = Field(min_length=1)
    input_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)
    dimensions: int = Field(gt=0)

    @model_validator(mode="after")
    def embedding_usage_is_exact(self) -> QueryEmbeddingUsage:
        if self.total_tokens != self.input_tokens:
            raise ValueError("embedding total tokens must equal input tokens")
        return self


class EmbeddingsResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class OpenAIClient(Protocol):
    embeddings: EmbeddingsResource


OpenAIClientFactory = Callable[[str], OpenAIClient]


def _default_openai_client_factory(api_key: str) -> OpenAIClient:
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


class OpenAIPineconeQueryBuilder:
    """Build one dense or weighted dense+sparse payload per specialist query.

    Client creation and the embedding request happen only when the builder is called.
    Tests inject a fake client, so they never cross the network boundary.
    """

    def __init__(
        self,
        *,
        domain: Domain,
        api_key: str,
        sparse_encoder: BM25SparseEncoder | None = None,
        client_factory: OpenAIClientFactory = _default_openai_client_factory,
    ) -> None:
        if not api_key.strip():
            raise ValueError("OpenAI API key cannot be blank")
        if domain in {Domain.PRODUCT, Domain.SECURITY} and sparse_encoder is None:
            raise ValueError("Product and Security query builders require a sparse encoder")
        self._domain = domain
        self._api_key = api_key
        self._sparse_encoder = sparse_encoder
        self._client_factory = client_factory
        self._client: OpenAIClient | None = None
        self._request_count = 0
        self._usage_receipts: list[QueryEmbeddingUsage] = []

    @property
    def is_initialized(self) -> bool:
        return self._client is not None

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def usage_receipts(self) -> tuple[QueryEmbeddingUsage, ...]:
        return tuple(self._usage_receipts)

    @property
    def last_usage(self) -> QueryEmbeddingUsage | None:
        return self._usage_receipts[-1] if self._usage_receipts else None

    def _get_client(self) -> OpenAIClient:
        if self._client is None:
            self._client = self._client_factory(self._api_key)
        return self._client

    def __call__(self, query: str) -> dict[str, Any]:
        if not query.strip():
            raise ValueError("retrieval query must contain at least one searchable token")

        client = self._get_client()
        self._request_count += 1
        response = client.embeddings.create(
            model=OPENAI_EMBEDDING_MODEL,
            input=query,
            encoding_format=EMBEDDING_ENCODING,
            dimensions=EMBEDDING_DIMENSION,
        )
        returned_model = _field(response, "model")
        if returned_model != OPENAI_EMBEDDING_MODEL:
            raise ProviderQueryError("OpenAI returned an unexpected embedding model")

        data = _field(response, "data")
        if not isinstance(data, Sequence) or isinstance(data, (str, bytes)) or len(data) != 1:
            raise ProviderQueryError("OpenAI must return exactly one query embedding")
        vector = _field(data[0], "embedding")
        if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)):
            raise ProviderQueryError("OpenAI returned an invalid query embedding")
        dense = [float(value) for value in vector]
        if len(dense) != EMBEDDING_DIMENSION:
            raise ProviderQueryError("OpenAI query embedding has the wrong dimension")

        usage = _field(response, "usage")
        input_tokens = _field(usage, "prompt_tokens")
        total_tokens = _field(usage, "total_tokens")
        if (
            isinstance(input_tokens, bool)
            or not isinstance(input_tokens, int)
            or input_tokens < 0
            or isinstance(total_tokens, bool)
            or not isinstance(total_tokens, int)
            or total_tokens < 0
        ):
            raise ProviderQueryError("OpenAI query embedding has invalid token usage")
        try:
            receipt = QueryEmbeddingUsage(
                request_number=self._request_count,
                model=returned_model,
                input_tokens=input_tokens,
                total_tokens=total_tokens,
                dimensions=len(dense),
            )
        except ValueError:
            raise ProviderQueryError(
                "OpenAI query embedding token usage is inconsistent"
            ) from None
        self._usage_receipts.append(receipt)

        if self._domain is Domain.IMPLEMENTATION:
            return {"vector": dense}

        weighted_dense = [value * HYBRID_DENSE_WEIGHT for value in dense]
        sparse_encoder = self._sparse_encoder
        if sparse_encoder is None:  # defensive: constructor already enforces this
            raise ProviderQueryError("hybrid query is missing its sparse encoder")
        sparse = sparse_encoder.encode_query(self._domain, query)
        payload: dict[str, Any] = {"vector": weighted_dense}
        if sparse.indices:
            payload["sparse_vector"] = {
                "indices": list(sparse.indices),
                "values": [value * HYBRID_SPARSE_WEIGHT for value in sparse.values],
            }
        return payload
