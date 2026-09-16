from datetime import date
from typing import Any

import pytest

from rfp_orchestrator.corpus import SourceStatus
from rfp_orchestrator.models import Domain
from rfp_orchestrator.pinecone_adapter import (
    PineconeAdapterError,
    PineconeNotConfiguredError,
    PineconeResponseError,
    PineconeRetrieverAdapter,
)
from rfp_orchestrator.retrieval import RetrievalMethod, SearchFilters


class FakeIndex:
    def __init__(self, matches: list[dict[str, Any]]) -> None:
        self.matches = matches
        self.queries: list[dict[str, Any]] = []

    def query(self, **kwargs: Any) -> dict[str, Any]:
        self.queries.append(kwargs)
        return {"matches": self.matches}


def match(
    *,
    domain: Domain = Domain.PRODUCT,
    doc_id: str = "PROD-CAP-001",
    source_status: SourceStatus = SourceStatus.CURRENT,
    authority_rank: int = 5,
    score: float = 0.9,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "doc_id": doc_id,
        "domain": domain.value,
        "title": "Provider Fixture",
        "text": "Provider evidence passage",
        "version": "1.0",
        "effective_date": "2026-07-01",
        "authority_rank": authority_rank,
        "source_status": source_status.value,
    }
    return {
        "id": f"{doc_id}::chunk-001",
        "score": score,
        "metadata": metadata,
    }


def test_construction_is_lazy_and_does_not_call_factory() -> None:
    factory_calls = 0

    def factory() -> FakeIndex:
        nonlocal factory_calls
        factory_calls += 1
        return FakeIndex([])

    adapter = PineconeRetrieverAdapter(
        domain=Domain.PRODUCT,
        namespace="northstar-v1",
        index_factory=factory,
    )

    assert adapter.is_initialized is False
    assert factory_calls == 0


def test_incomplete_configuration_fails_before_provider_initialization() -> None:
    factory_calls = 0

    def factory() -> FakeIndex:
        nonlocal factory_calls
        factory_calls += 1
        return FakeIndex([])

    adapter = PineconeRetrieverAdapter(
        domain=Domain.PRODUCT,
        namespace="northstar-v1",
        index_factory=factory,
    )

    with pytest.raises(PineconeNotConfiguredError, match="query builder"):
        adapter.search("SAML")
    assert factory_calls == 0
    assert adapter.is_initialized is False


def test_first_search_initializes_once_and_returns_hybrid_evidence() -> None:
    fake_index = FakeIndex([match()])
    factory_calls = 0

    def factory() -> FakeIndex:
        nonlocal factory_calls
        factory_calls += 1
        return fake_index

    adapter = PineconeRetrieverAdapter(
        domain=Domain.PRODUCT,
        namespace="northstar-v1",
        query_builder=lambda query: {"vector": [0.1, 0.2, len(query)]},
        index_factory=factory,
    )

    first = adapter.search("SAML", k=1)
    second = adapter.search("SCIM", k=1)

    assert factory_calls == 1
    assert adapter.is_initialized is True
    assert first[0].retrieval_method is RetrievalMethod.HYBRID
    assert first[0].score_components is not None
    assert first[0].score_components.visibility == "combined_only"
    assert first[0].score_components.provider_combined_score == 0.9
    assert first[0].score_components.lexical_raw is None
    assert second[0].domain is Domain.PRODUCT


def test_provider_query_enforces_domain_metadata_filters_namespace_and_top_k() -> None:
    fake_index = FakeIndex([match()])
    adapter = PineconeRetrieverAdapter(
        domain=Domain.PRODUCT,
        namespace="northstar-v1",
        query_builder=lambda query: {"vector": [float(len(query))]},
        index_factory=lambda: fake_index,
    )
    filters = SearchFilters(
        source_statuses={SourceStatus.CURRENT},
        min_authority_rank=4,
        doc_ids={"PROD-CAP-001"},
        effective_on_or_before=date(2026, 7, 1),
    )

    adapter.search("SAML", k=3, filters=filters)

    query = fake_index.queries[0]
    assert query["top_k"] == 3
    assert query["namespace"] == "northstar-v1"
    assert query["include_metadata"] is True
    assert query["include_values"] is False
    assert query["filter"] == {
        "domain": {"$eq": "product"},
        "source_status": {"$in": ["current"]},
        "authority_rank": {"$gte": 4},
        "doc_id": {"$in": ["PROD-CAP-001"]},
        "effective_date": {"$lte": "2026-07-01"},
    }
    assert adapter.query_count == 1


@pytest.mark.parametrize("invalid_k", [0, 6])
def test_top_five_guard_runs_before_query_builder_or_factory(invalid_k: int) -> None:
    builder_calls = 0
    factory_calls = 0

    def query_builder(query: str) -> dict[str, list[float]]:
        nonlocal builder_calls
        builder_calls += 1
        return {"vector": [float(len(query))]}

    def factory() -> FakeIndex:
        nonlocal factory_calls
        factory_calls += 1
        return FakeIndex([])

    adapter = PineconeRetrieverAdapter(
        domain=Domain.SECURITY,
        namespace="northstar-v1",
        query_builder=query_builder,
        index_factory=factory,
    )

    with pytest.raises(ValueError, match="between 1 and 5"):
        adapter.search("TLS", k=invalid_k)
    assert builder_calls == 0
    assert factory_calls == 0


def test_implementation_adapter_returns_dense_evidence_without_hybrid_components() -> None:
    fake_index = FakeIndex(
        [
            match(
                domain=Domain.IMPLEMENTATION,
                doc_id="IMPL-GUIDE-001",
            )
        ]
    )
    adapter = PineconeRetrieverAdapter(
        domain=Domain.IMPLEMENTATION,
        namespace="northstar-v1",
        query_builder=lambda query: {"vector": [float(len(query))]},
        index_factory=lambda: fake_index,
    )

    result = adapter.search("onboarding timeline", k=1)[0]

    assert result.retrieval_method is RetrievalMethod.DENSE
    assert result.score_components is None
    assert result.domain is Domain.IMPLEMENTATION


def test_cross_domain_provider_response_fails_closed() -> None:
    fake_index = FakeIndex([match(domain=Domain.SECURITY, doc_id="SEC-CTRL-001")])
    adapter = PineconeRetrieverAdapter(
        domain=Domain.PRODUCT,
        namespace="northstar-v1",
        query_builder=lambda query: {"vector": [float(len(query))]},
        index_factory=lambda: fake_index,
    )

    with pytest.raises(PineconeResponseError, match="cross-domain"):
        adapter.search("SAML")


def test_hybrid_response_does_not_invent_unavailable_component_scores() -> None:
    fake_index = FakeIndex([match()])
    adapter = PineconeRetrieverAdapter(
        domain=Domain.PRODUCT,
        namespace="northstar-v1",
        query_builder=lambda query: {"vector": [float(len(query))]},
        index_factory=lambda: fake_index,
    )

    result = adapter.search("SAML")[0]

    assert result.score_components is not None
    assert result.score_components.visibility == "combined_only"
    assert result.score_components.lexical_raw is None
    assert result.score_components.semantic_raw is None


def test_query_builder_cannot_override_boundary_fields() -> None:
    adapter = PineconeRetrieverAdapter(
        domain=Domain.PRODUCT,
        namespace="northstar-v1",
        query_builder=lambda query: {"vector": [float(len(query))], "top_k": 99},
        index_factory=lambda: FakeIndex([]),
    )

    with pytest.raises(PineconeAdapterError, match="top_k"):
        adapter.search("SAML")


def test_query_builder_cannot_request_stored_vector_values() -> None:
    adapter = PineconeRetrieverAdapter(
        domain=Domain.PRODUCT,
        namespace="northstar-v1",
        query_builder=lambda query: {
            "vector": [float(len(query))],
            "include_values": True,
        },
        index_factory=lambda: FakeIndex([]),
    )

    with pytest.raises(PineconeAdapterError, match="include_values"):
        adapter.search("SAML")

    assert adapter.query_count == 0


def test_provider_results_drop_weak_tail_relative_to_best_score() -> None:
    fake_index = FakeIndex(
        [
            match(doc_id="PROD-CAP-001", score=0.9),
            match(doc_id="PROD-AVAIL-001", score=0.5),
            match(doc_id="PROD-DEPLOY-001", score=0.2),
        ]
    )
    adapter = PineconeRetrieverAdapter(
        domain=Domain.PRODUCT,
        namespace="northstar-v1",
        query_builder=lambda query: {"vector": [float(len(query))]},
        index_factory=lambda: fake_index,
    )

    results = adapter.search("SAML", k=5)

    assert [result.doc_id for result in results] == [
        "PROD-CAP-001",
        "PROD-AVAIL-001",
    ]
