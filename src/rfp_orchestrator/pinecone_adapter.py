"""Lazy Pinecone retrieval adapter with no import-time provider initialization."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Protocol

from rfp_orchestrator.corpus import SourceStatus
from rfp_orchestrator.models import Domain
from rfp_orchestrator.provider_config import HYBRID_DENSE_WEIGHT, HYBRID_SPARSE_WEIGHT
from rfp_orchestrator.retrieval import (
    EvidenceChunk,
    HybridScoreComponents,
    RetrievalMethod,
    SearchFilters,
    SourceOrderingSignals,
    apply_relative_score_floor,
    enforce_top_k,
)


class PineconeAdapterError(RuntimeError):
    """Base error for provider-adapter failures."""


class PineconeNotConfiguredError(PineconeAdapterError):
    """Raised before provider initialization when live configuration is incomplete."""


class PineconeResponseError(PineconeAdapterError):
    """Raised when provider output violates the evidence contract."""


class PineconeIndex(Protocol):
    def query(self, **kwargs: Any) -> Any: ...


QueryBuilder = Callable[[str], Mapping[str, Any]]
IndexFactory = Callable[[], PineconeIndex]


def _default_index_factory(api_key: str, index_name: str) -> IndexFactory:
    def create_index() -> PineconeIndex:
        from pinecone import Pinecone

        return Pinecone(api_key=api_key).Index(index_name)

    return create_index


def _provider_filter(domain: Domain, filters: SearchFilters | None) -> dict[str, Any]:
    provider_filter: dict[str, Any] = {"domain": {"$eq": domain.value}}
    if filters is None:
        return provider_filter
    if filters.source_statuses is not None:
        provider_filter["source_status"] = {
            "$in": sorted(status.value for status in filters.source_statuses)
        }
    if filters.min_authority_rank is not None:
        provider_filter["authority_rank"] = {"$gte": filters.min_authority_rank}
    if filters.doc_ids is not None:
        provider_filter["doc_id"] = {"$in": sorted(filters.doc_ids)}
    if filters.effective_on_or_before is not None:
        provider_filter["effective_date"] = {
            "$lte": filters.effective_on_or_before.isoformat()
        }
    return provider_filter


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _ordering_signals(
    score: float,
    source_status: SourceStatus,
    authority_rank: int,
) -> SourceOrderingSignals:
    lifecycle_factor = 1.0 if source_status is SourceStatus.CURRENT else 0.45
    authority_factor = 0.90 + 0.02 * authority_rank
    return SourceOrderingSignals(
        lifecycle_factor=lifecycle_factor,
        authority_factor=authority_factor,
        ranking_score=score * lifecycle_factor * authority_factor,
    )


class PineconeRetrieverAdapter:
    """Domain-locked lazy adapter for a future Pinecone query implementation."""

    def __init__(
        self,
        *,
        domain: Domain,
        namespace: str,
        query_builder: QueryBuilder | None = None,
        api_key: str | None = None,
        index_name: str | None = None,
        index_factory: IndexFactory | None = None,
    ) -> None:
        if not namespace.strip():
            raise ValueError("Pinecone namespace cannot be blank")
        self._domain = domain
        self._namespace = namespace
        self._query_builder = query_builder
        self._api_key = api_key
        self._index_name = index_name
        self._index_factory = index_factory
        self._index: PineconeIndex | None = None
        self._query_count = 0
        self._retrieval_method = (
            RetrievalMethod.DENSE
            if domain is Domain.IMPLEMENTATION
            else RetrievalMethod.HYBRID
        )

    @property
    def domain(self) -> Domain:
        return self._domain

    @property
    def is_initialized(self) -> bool:
        return self._index is not None

    @property
    def query_count(self) -> int:
        return self._query_count

    def _validate_configuration(self) -> None:
        if self._query_builder is None:
            raise PineconeNotConfiguredError(
                "Pinecone query builder is not configured; provider search was not started"
            )
        if self._index_factory is None and (not self._api_key or not self._index_name):
            raise PineconeNotConfiguredError(
                "Pinecone API key and index name are not configured; provider search was not started"
            )

    def _get_index(self) -> PineconeIndex:
        if self._index is None:
            factory = self._index_factory
            if factory is None:
                factory = _default_index_factory(self._api_key or "", self._index_name or "")
            self._index = factory()
        return self._index

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: SearchFilters | None = None,
    ) -> list[EvidenceChunk]:
        limit = enforce_top_k(k)
        if not query.strip():
            raise ValueError("retrieval query must contain at least one searchable token")
        self._validate_configuration()

        query_payload = dict(self._query_builder(query)) if self._query_builder else {}
        reserved = {
            "top_k",
            "filter",
            "namespace",
            "include_metadata",
            "include_values",
        }
        collisions = sorted(reserved & query_payload.keys())
        if collisions:
            raise PineconeAdapterError(
                f"query builder cannot override adapter fields: {', '.join(collisions)}"
            )
        if not query_payload:
            raise PineconeAdapterError("query builder returned an empty provider payload")

        index = self._get_index()
        self._query_count += 1
        response = index.query(
            **query_payload,
            top_k=limit,
            namespace=self._namespace,
            filter=_provider_filter(self._domain, filters),
            include_metadata=True,
            include_values=False,
        )
        evidence = [self._as_evidence(match) for match in (_field(response, "matches") or [])]
        evidence.sort(
            key=lambda item: (
                -item.ordering_signals.ranking_score,
                -item.score,
                -item.authority_rank,
                item.chunk_id,
            )
        )
        return apply_relative_score_floor(evidence[:limit])

    def _as_evidence(self, match: Any) -> EvidenceChunk:
        metadata = _field(match, "metadata")
        if not isinstance(metadata, Mapping):
            raise PineconeResponseError("Pinecone match is missing metadata")

        required = {
            "doc_id",
            "domain",
            "title",
            "text",
            "version",
            "effective_date",
            "authority_rank",
            "source_status",
        }
        missing = sorted(required - metadata.keys())
        if missing:
            raise PineconeResponseError(
                f"Pinecone match is missing evidence metadata: {', '.join(missing)}"
            )

        try:
            result_domain = Domain(str(metadata["domain"]))
            source_status = SourceStatus(str(metadata["source_status"]))
            authority_rank = int(metadata["authority_rank"])
            score = float(_field(match, "score"))
        except (TypeError, ValueError) as error:
            raise PineconeResponseError(
                "Pinecone match contains invalid domain, status, authority, or score"
            ) from error
        if result_domain is not self._domain:
            raise PineconeResponseError(
                f"Pinecone returned cross-domain evidence '{result_domain.value}' "
                f"for '{self._domain.value}'"
            )

        score_components = None
        if self._retrieval_method is RetrievalMethod.HYBRID:
            score_components = HybridScoreComponents(
                lexical_weight=HYBRID_SPARSE_WEIGHT,
                semantic_weight=HYBRID_DENSE_WEIGHT,
                provider_combined_score=score,
                visibility="combined_only",
            )

        chunk_id = _field(match, "id") or metadata.get("chunk_id")
        if not chunk_id:
            raise PineconeResponseError("Pinecone match is missing its stable chunk ID")

        return EvidenceChunk(
            chunk_id=str(chunk_id),
            doc_id=str(metadata["doc_id"]),
            domain=result_domain,
            title=str(metadata["title"]),
            text=str(metadata["text"]),
            version=str(metadata["version"]),
            effective_date=str(metadata["effective_date"]),
            authority_rank=authority_rank,
            source_status=source_status.value,
            score=score,
            retrieval_method=self._retrieval_method,
            score_components=score_components,
            ordering_signals=_ordering_signals(score, source_status, authority_rank),
        )
