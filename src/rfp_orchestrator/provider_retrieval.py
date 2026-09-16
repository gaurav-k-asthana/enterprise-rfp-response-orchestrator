"""Shared, audited provider retrieval session for both comparison architectures."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.corpus import load_corpus_chunks
from rfp_orchestrator.ingestion import BM25SparseEncoder
from rfp_orchestrator.models import Domain
from rfp_orchestrator.pinecone_adapter import IndexFactory, PineconeRetrieverAdapter
from rfp_orchestrator.provider_config import (
    EMBEDDING_DIMENSION,
    OPENAI_EMBEDDING_MODEL,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE,
)
from rfp_orchestrator.provider_query import (
    OpenAIClientFactory,
    OpenAIPineconeQueryBuilder,
    QueryEmbeddingUsage,
)
from rfp_orchestrator.retrieval import (
    EvidenceChunk,
    RetrievalMethod,
    SearchFilters,
    enforce_top_k,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS_DIRECTORY = PROJECT_ROOT / "data" / "kb"


class ProviderRetrievalError(RuntimeError):
    """Base error for the shared provider retrieval boundary."""


class ProviderRetrievalDisabledError(ProviderRetrievalError):
    """Raised before provider activity when the session is disabled."""


class ProviderRetrievalCallError(ProviderRetrievalError):
    """Raised with a redacted message after a provider retrieval fails."""


class ProviderRetrievalSessionClosedError(ProviderRetrievalError):
    """Raised before provider activity when a completed run reuses a session."""


class ProviderRetrievalStatus(str, Enum):
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


TOOL_NAME_BY_DOMAIN = {
    Domain.PRODUCT: "search_product_evidence",
    Domain.SECURITY: "search_security_compliance_evidence",
    Domain.IMPLEMENTATION: "search_implementation_evidence",
}

METHOD_BY_DOMAIN = {
    Domain.PRODUCT: RetrievalMethod.HYBRID,
    Domain.SECURITY: RetrievalMethod.HYBRID,
    Domain.IMPLEMENTATION: RetrievalMethod.DENSE,
}


class ProviderRetrievalOperation(BaseModel):
    """Safe operation record; credentials, host values, and vectors are excluded."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    operation_id: str = Field(min_length=1)
    tool_name: str = Field(min_length=1)
    domain: Domain
    query: str = Field(min_length=1)
    requested_k: int = Field(ge=1, le=5)
    retrieval_method: RetrievalMethod
    namespace: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1)
    embedding_dimensions: int = Field(gt=0)
    embedding_calls: int = Field(ge=0, le=1)
    embedding_input_tokens: int | None = Field(default=None, ge=0)
    pinecone_queries: int = Field(ge=0, le=1)
    result_ids: list[str] = Field(max_length=5)
    status: ProviderRetrievalStatus
    error_code: str | None = None

    @model_validator(mode="after")
    def operation_is_consistent(self) -> ProviderRetrievalOperation:
        if self.tool_name != TOOL_NAME_BY_DOMAIN[self.domain]:
            raise ValueError("provider retrieval tool and domain do not match")
        if self.retrieval_method is not METHOD_BY_DOMAIN[self.domain]:
            raise ValueError("provider retrieval method and domain do not match")
        if len(self.result_ids) != len(set(self.result_ids)):
            raise ValueError("provider retrieval result IDs cannot repeat")
        if self.status is ProviderRetrievalStatus.COMPLETE:
            if self.embedding_calls != 1 or self.pinecone_queries != 1:
                raise ValueError("completed retrieval requires one embedding and one query")
            if self.embedding_input_tokens is None or self.error_code is not None:
                raise ValueError("completed retrieval requires usage and no error")
        else:
            if self.result_ids or self.error_code != "PROVIDER_RETRIEVAL_FAILED":
                raise ValueError("failed retrieval requires a safe error and no results")
            if self.embedding_calls == 0 and self.embedding_input_tokens is not None:
                raise ValueError("zero embedding calls cannot report embedding usage")
            if self.pinecone_queries > self.embedding_calls:
                raise ValueError("Pinecone cannot run before the query embedding")
        return self


class InstrumentedProviderRetriever:
    """Expose adapter telemetry without exposing vector values."""

    def __init__(
        self,
        *,
        query_builder: OpenAIPineconeQueryBuilder,
        adapter: PineconeRetrieverAdapter,
    ) -> None:
        if query_builder is None:
            raise ValueError("instrumented provider retriever requires a query builder")
        self._query_builder = query_builder
        self._adapter = adapter

    @property
    def domain(self) -> Domain:
        return self._adapter.domain

    @property
    def embedding_request_count(self) -> int:
        return self._query_builder.request_count

    @property
    def pinecone_query_count(self) -> int:
        return self._adapter.query_count

    @property
    def last_embedding_usage(self) -> QueryEmbeddingUsage | None:
        return self._query_builder.last_usage

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: SearchFilters | None = None,
    ) -> list[EvidenceChunk]:
        return self._adapter.search(query, k=k, filters=filters)


class ProviderDomainBackend(Protocol):
    @property
    def domain(self) -> Domain: ...

    @property
    def embedding_request_count(self) -> int: ...

    @property
    def pinecone_query_count(self) -> int: ...

    @property
    def last_embedding_usage(self) -> QueryEmbeddingUsage | None: ...

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: SearchFilters | None = None,
    ) -> list[EvidenceChunk]: ...


class SessionDomainRetriever:
    """Domain-specific view used by the baseline and specialist graph."""

    def __init__(self, session: ProviderRetrievalSession, domain: Domain) -> None:
        self._session = session
        self._domain = domain

    @property
    def domain(self) -> Domain:
        return self._domain

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: SearchFilters | None = None,
    ) -> list[EvidenceChunk]:
        return self._session.search(self._domain, query, k=k, filters=filters)


@dataclass(frozen=True)
class ProviderSpecialistRetrievers:
    product: SessionDomainRetriever
    security: SessionDomainRetriever
    implementation: SessionDomainRetriever


class ProviderRetrievalSession:
    """One-run retrieval recorder shared by either comparison architecture."""

    def __init__(
        self,
        backends: Mapping[Domain, ProviderDomainBackend],
        *,
        enabled: bool = False,
        namespace: str = PINECONE_NAMESPACE,
    ) -> None:
        if list(backends) != list(Domain):
            raise ValueError("provider retrieval session requires all domains in canonical order")
        if any(backend.domain is not domain for domain, backend in backends.items()):
            raise ValueError("provider retrieval backend key and domain do not match")
        if not namespace.strip():
            raise ValueError("provider retrieval namespace cannot be blank")
        self._backends = dict(backends)
        self._enabled = enabled
        self._namespace = namespace
        self._operations: list[ProviderRetrievalOperation] = []
        self._closed = False
        self._retrievers = {
            domain: SessionDomainRetriever(self, domain) for domain in Domain
        }

    @property
    def operations(self) -> tuple[ProviderRetrievalOperation, ...]:
        return tuple(self._operations)

    @property
    def domain_retrievers(self) -> Mapping[Domain, SessionDomainRetriever]:
        return dict(self._retrievers)

    @property
    def specialist_retrievers(self) -> ProviderSpecialistRetrievers:
        return ProviderSpecialistRetrievers(
            product=self._retrievers[Domain.PRODUCT],
            security=self._retrievers[Domain.SECURITY],
            implementation=self._retrievers[Domain.IMPLEMENTATION],
        )

    def close(self) -> None:
        self._closed = True

    def search(
        self,
        domain: Domain,
        query: str,
        *,
        k: int = 5,
        filters: SearchFilters | None = None,
    ) -> list[EvidenceChunk]:
        if self._closed:
            raise ProviderRetrievalSessionClosedError(
                "provider retrieval session is closed"
            )
        if not self._enabled:
            raise ProviderRetrievalDisabledError(
                "provider retrieval is disabled until the exact paid command is approved"
            )
        limit = enforce_top_k(k)
        if not query.strip():
            raise ValueError("retrieval query must contain at least one searchable token")

        backend = self._backends[domain]
        embeddings_before = backend.embedding_request_count
        pinecone_before = backend.pinecone_query_count
        try:
            evidence = backend.search(query, k=limit, filters=filters)
        except Exception:  # noqa: BLE001 - provider boundary records and redacts failures.
            self._record_operation(
                domain=domain,
                query=query,
                requested_k=limit,
                backend=backend,
                embeddings_before=embeddings_before,
                pinecone_before=pinecone_before,
                evidence=[],
                status=ProviderRetrievalStatus.FAILED,
            )
            raise ProviderRetrievalCallError(
                f"provider retrieval failed for the {domain.value} evidence tool"
            ) from None

        self._record_operation(
            domain=domain,
            query=query,
            requested_k=limit,
            backend=backend,
            embeddings_before=embeddings_before,
            pinecone_before=pinecone_before,
            evidence=evidence,
            status=ProviderRetrievalStatus.COMPLETE,
        )
        return list(evidence)

    def _record_operation(
        self,
        *,
        domain: Domain,
        query: str,
        requested_k: int,
        backend: ProviderDomainBackend,
        embeddings_before: int,
        pinecone_before: int,
        evidence: list[EvidenceChunk],
        status: ProviderRetrievalStatus,
    ) -> None:
        embedding_calls = backend.embedding_request_count - embeddings_before
        pinecone_queries = backend.pinecone_query_count - pinecone_before
        if embedding_calls not in {0, 1} or pinecone_queries not in {0, 1}:
            raise ProviderRetrievalError(
                "one retrieval operation exceeded its provider-call boundary"
            )
        usage = backend.last_embedding_usage if embedding_calls else None
        expected_request_number = embeddings_before + embedding_calls
        if usage is not None and usage.request_number != expected_request_number:
            usage = None
        self._operations.append(
            ProviderRetrievalOperation(
                operation_id=f"retrieval-{len(self._operations) + 1:03d}",
                tool_name=TOOL_NAME_BY_DOMAIN[domain],
                domain=domain,
                query=query,
                requested_k=requested_k,
                retrieval_method=METHOD_BY_DOMAIN[domain],
                namespace=self._namespace,
                embedding_model=OPENAI_EMBEDDING_MODEL,
                embedding_dimensions=EMBEDDING_DIMENSION,
                embedding_calls=embedding_calls,
                embedding_input_tokens=(usage.input_tokens if usage else None),
                pinecone_queries=pinecone_queries,
                result_ids=[item.chunk_id for item in evidence],
                status=status,
                error_code=(
                    None
                    if status is ProviderRetrievalStatus.COMPLETE
                    else "PROVIDER_RETRIEVAL_FAILED"
                ),
            )
        )


def build_provider_retrieval_session(
    *,
    openai_api_key: str,
    pinecone_api_key: str,
    enabled: bool = False,
    corpus_directory: str | Path = DEFAULT_CORPUS_DIRECTORY,
    openai_client_factory: OpenAIClientFactory | None = None,
    index_factory: IndexFactory | None = None,
) -> ProviderRetrievalSession:
    """Build all three lazy provider tools without initializing either provider."""

    if not pinecone_api_key.strip():
        raise ValueError("Pinecone API key cannot be blank")
    sparse_encoder = BM25SparseEncoder(load_corpus_chunks(corpus_directory))
    backends: dict[Domain, InstrumentedProviderRetriever] = {}
    for domain in Domain:
        builder_kwargs: dict[str, object] = {
            "domain": domain,
            "api_key": openai_api_key,
        }
        if domain in {Domain.PRODUCT, Domain.SECURITY}:
            builder_kwargs["sparse_encoder"] = sparse_encoder
        if openai_client_factory is not None:
            builder_kwargs["client_factory"] = openai_client_factory
        query_builder = OpenAIPineconeQueryBuilder(**builder_kwargs)

        adapter_kwargs: dict[str, object] = {
            "domain": domain,
            "namespace": PINECONE_NAMESPACE,
            "query_builder": query_builder,
            "api_key": pinecone_api_key,
            "index_name": PINECONE_INDEX_NAME,
        }
        if index_factory is not None:
            adapter_kwargs["index_factory"] = index_factory
        adapter = PineconeRetrieverAdapter(**adapter_kwargs)
        backends[domain] = InstrumentedProviderRetriever(
            query_builder=query_builder,
            adapter=adapter,
        )
    return ProviderRetrievalSession(backends, enabled=enabled)
