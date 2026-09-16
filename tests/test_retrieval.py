from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.corpus import CorpusChunk, SourceStatus, load_corpus_chunks
from rfp_orchestrator.models import Domain
from rfp_orchestrator.retrieval import (
    BM25Retriever,
    EvidenceChunk,
    HybridRetriever,
    InMemoryRetriever,
    RetrievalMethod,
    SearchFilters,
    SemanticSubstituteRetriever,
    build_offline_retrievers,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


def test_builds_from_validated_corpus_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)

    retriever = InMemoryRetriever.from_corpus_directory(KB_DIRECTORY)

    assert retriever.chunk_count >= 12


def test_search_is_repeatable_for_unchanged_input() -> None:
    retriever = InMemoryRetriever.from_corpus_directory(KB_DIRECTORY)

    first = retriever.search("SAML SCIM", k=5)
    second = retriever.search("SAML SCIM", k=5)

    assert first
    assert first == second
    assert first[0].doc_id in {"PROD-AVAIL-001", "PROD-CAP-001"}


def test_search_returns_complete_evidence_provenance() -> None:
    retriever = InMemoryRetriever.from_corpus_directory(KB_DIRECTORY)

    result = retriever.search("implementation prerequisites", k=1)[0]

    assert result.chunk_id.startswith(f"{result.doc_id}::chunk-")
    assert result.title
    assert result.text
    assert result.version
    assert result.effective_date
    assert 1 <= result.authority_rank <= 5
    assert result.source_status in {"current", "archived"}
    assert result.score > 0
    assert result.retrieval_method is RetrievalMethod.BOOTSTRAP


def test_search_respects_requested_limit_and_top_five_guard() -> None:
    retriever = InMemoryRetriever.from_corpus_directory(KB_DIRECTORY)

    assert len(retriever.search("customer", k=3)) <= 3
    with pytest.raises(ValueError, match="between 1 and 5"):
        retriever.search("customer", k=6)


def test_search_rejects_blank_query_and_returns_empty_for_no_match() -> None:
    retriever = InMemoryRetriever.from_corpus_directory(KB_DIRECTORY)

    with pytest.raises(ValueError, match="searchable token"):
        retriever.search("   ")
    assert retriever.search("zyxwvutsrqponmlkjihgfedcba") == []


def test_equal_scores_use_stable_chunk_id_tiebreaker() -> None:
    shared = {
        "domain": Domain.PRODUCT,
        "title": "Tie Fixture",
        "version": "1.0",
        "effective_date": date(2026, 8, 29),
        "authority_rank": 3,
        "source_status": SourceStatus.CURRENT,
        "text": "alpha beta",
        "source_path": Path("tie.md"),
    }
    chunks = [
        CorpusChunk(chunk_id="DOC-B::chunk-001", chunk_index=1, doc_id="DOC-B", **shared),
        CorpusChunk(chunk_id="DOC-A::chunk-001", chunk_index=1, doc_id="DOC-A", **shared),
    ]

    results = InMemoryRetriever(chunks).search("alpha")

    assert [result.chunk_id for result in results] == [
        "DOC-A::chunk-001",
        "DOC-B::chunk-001",
    ]


def domain_bm25_retriever(domain: Domain) -> BM25Retriever:
    chunks = [
        chunk for chunk in load_corpus_chunks(KB_DIRECTORY) if chunk.domain is domain
    ]
    return BM25Retriever(chunks)


@pytest.mark.parametrize(
    ("domain", "query", "expected_doc_ids"),
    [
        (
            Domain.PRODUCT,
            "SAML 2.0 SCIM 2.0",
            {"PROD-AVAIL-001", "PROD-CAP-001"},
        ),
        (
            Domain.PRODUCT,
            "SAP S/4HANA ROADMAP",
            {"PROD-AVAIL-001", "PROD-CAP-001"},
        ),
        (Domain.SECURITY, "FIPS 140-3", {"SEC-CTRL-001"}),
        (Domain.SECURITY, "SOC 2 Type II ISO 27001", {"SEC-CTRL-001"}),
    ],
)
def test_bm25_exact_terms_rank_expected_source(
    domain: Domain,
    query: str,
    expected_doc_ids: set[str],
) -> None:
    results = domain_bm25_retriever(domain).search(query, k=5)

    assert results
    assert results[0].doc_id in expected_doc_ids
    assert all(result.retrieval_method is RetrievalMethod.LEXICAL for result in results)


def test_bm25_results_are_repeatable() -> None:
    retriever = domain_bm25_retriever(Domain.SECURITY)

    first = retriever.search("TLS 1.2", k=5)
    second = retriever.search("TLS 1.2", k=5)

    assert first == second
    assert all(result.retrieval_method is RetrievalMethod.LEXICAL for result in first)


def test_bm25_rewards_term_frequency_for_equal_length_chunks() -> None:
    shared = {
        "domain": Domain.PRODUCT,
        "title": "Frequency Fixture",
        "version": "1.0",
        "effective_date": date(2026, 8, 29),
        "authority_rank": 3,
        "source_status": SourceStatus.CURRENT,
        "source_path": Path("frequency.md"),
    }
    chunks = [
        CorpusChunk(
            chunk_id="DOC-LOW::chunk-001",
            chunk_index=1,
            doc_id="DOC-LOW",
            text="alpha beta gamma delta",
            **shared,
        ),
        CorpusChunk(
            chunk_id="DOC-HIGH::chunk-001",
            chunk_index=1,
            doc_id="DOC-HIGH",
            text="alpha alpha alpha delta",
            **shared,
        ),
    ]

    results = BM25Retriever(chunks).search("alpha")

    assert [result.doc_id for result in results] == ["DOC-HIGH", "DOC-LOW"]
    assert results[0].score > results[1].score


def implementation_semantic_retriever() -> SemanticSubstituteRetriever:
    chunks = [
        chunk
        for chunk in load_corpus_chunks(KB_DIRECTORY, max_chars=500)
        if chunk.domain is Domain.IMPLEMENTATION
    ]
    return SemanticSubstituteRetriever(chunks)


@pytest.mark.parametrize(
    ("query", "expected_passage_text"),
    [
        ("How long does onboarding take once we are ready?", "six to eight weeks"),
        ("Who needs to participate from our side?", "executive sponsor"),
        (
            "What could cause the rollout schedule to slip?",
            "complex custom integrations",
        ),
    ],
)
def test_semantic_substitute_matches_implementation_paraphrases(
    query: str,
    expected_passage_text: str,
) -> None:
    results = implementation_semantic_retriever().search(query, k=3)

    assert results
    assert expected_passage_text in results[0].text.lower()
    assert results[0].domain is Domain.IMPLEMENTATION


def test_semantic_substitute_is_repeatable_and_honestly_labeled() -> None:
    retriever = implementation_semantic_retriever()

    first = retriever.search("What customer team is needed for rollout?", k=3)
    second = retriever.search("What customer team is needed for rollout?", k=3)

    assert first == second
    assert all(
        result.retrieval_method is RetrievalMethod.SEMANTIC_SUBSTITUTE
        for result in first
    )


def test_semantic_substitute_returns_empty_for_unrelated_concepts() -> None:
    retriever = implementation_semantic_retriever()

    assert retriever.search("photosynthesis chlorophyll") == []


def domain_hybrid_retriever(domain: Domain) -> HybridRetriever:
    chunks = [
        chunk for chunk in load_corpus_chunks(KB_DIRECTORY) if chunk.domain is domain
    ]
    return HybridRetriever(chunks)


@pytest.mark.parametrize(
    ("domain", "query", "expected_doc_ids"),
    [
        (
            Domain.PRODUCT,
            "Can employees be provisioned automatically from our identity platform?",
            {"PROD-CAP-001", "PROD-AVAIL-001"},
        ),
        (
            Domain.PRODUCT,
            "Can we control our own encryption keys?",
            {"PROD-CAP-001", "PROD-AVAIL-001"},
        ),
        (Domain.SECURITY, "Do you have independent security audit reports?", {"SEC-CTRL-001"}),
        (Domain.SECURITY, "Can our records stay in Europe?", {"SEC-DATA-001"}),
    ],
)
def test_hybrid_ranks_product_and_security_paraphrases(
    domain: Domain,
    query: str,
    expected_doc_ids: set[str],
) -> None:
    results = domain_hybrid_retriever(domain).search(query, k=5)

    assert results
    assert results[0].doc_id in expected_doc_ids
    assert all(result.retrieval_method is RetrievalMethod.HYBRID for result in results)


def test_hybrid_exposes_reproducible_weighted_score_components() -> None:
    result = domain_hybrid_retriever(Domain.SECURITY).search(
        "SOC 2 Type II security audit",
        k=1,
    )[0]

    components = result.score_components
    assert components is not None
    expected_score = (
        components.lexical_weight * components.lexical_normalized
        + components.semantic_weight * components.semantic_normalized
    )
    assert components.lexical_weight == 0.6
    assert components.semantic_weight == 0.4
    assert result.score == pytest.approx(expected_score, abs=1e-6)


def test_hybrid_results_are_repeatable() -> None:
    retriever = domain_hybrid_retriever(Domain.PRODUCT)

    first = retriever.search("identity provisioning", k=5)
    second = retriever.search("identity provisioning", k=5)

    assert first == second


@pytest.mark.parametrize(
    ("lexical_weight", "semantic_weight"),
    [(0.8, 0.3), (-0.1, 1.1)],
)
def test_hybrid_rejects_invalid_weights(
    lexical_weight: float,
    semantic_weight: float,
) -> None:
    chunks = [
        chunk
        for chunk in load_corpus_chunks(KB_DIRECTORY)
        if chunk.domain is Domain.PRODUCT
    ]

    with pytest.raises(ValueError, match="weights"):
        HybridRetriever(
            chunks,
            lexical_weight=lexical_weight,
            semantic_weight=semantic_weight,
        )


def test_hybrid_evidence_requires_observable_components() -> None:
    with pytest.raises(ValidationError, match="score_components"):
        EvidenceChunk(
            chunk_id="DOC-001::chunk-001",
            doc_id="DOC-001",
            domain=Domain.PRODUCT,
            title="Hybrid Fixture",
            text="fixture evidence",
            version="1.0",
            effective_date="2026-08-29",
            authority_rank=3,
            source_status="current",
            score=1.0,
            retrieval_method=RetrievalMethod.HYBRID,
        )


def test_current_tls_evidence_outranks_archived_but_both_remain_visible() -> None:
    results = domain_hybrid_retriever(Domain.SECURITY).search(
        "TLS 1.2 transport protocol",
        k=5,
    )
    ids = [result.doc_id for result in results]

    assert "SEC-CTRL-001" in ids
    assert "SEC-CTRL-OLD-001" in ids
    assert ids.index("SEC-CTRL-001") < ids.index("SEC-CTRL-OLD-001")
    current = next(result for result in results if result.doc_id == "SEC-CTRL-001")
    archived = next(result for result in results if result.doc_id == "SEC-CTRL-OLD-001")
    assert current.ordering_signals is not None
    assert archived.ordering_signals is not None
    assert current.ordering_signals.lifecycle_factor == 1.0
    assert archived.ordering_signals.lifecycle_factor == 0.45


def test_equal_authority_retention_conflict_remains_visible() -> None:
    results = domain_hybrid_retriever(Domain.SECURITY).search(
        "post termination retention recovery window",
        k=5,
    )
    by_id = {result.doc_id: result for result in results}

    assert {"SEC-RET-001", "SEC-RET-OPS-001"} <= by_id.keys()
    assert by_id["SEC-RET-001"].authority_rank == 5
    assert by_id["SEC-RET-OPS-001"].authority_rank == 5
    assert by_id["SEC-RET-001"].source_status == "current"
    assert by_id["SEC-RET-OPS-001"].source_status == "current"


def test_authority_orders_equally_relevant_current_sources() -> None:
    shared = {
        "domain": Domain.PRODUCT,
        "title": "Authority Fixture",
        "version": "1.0",
        "effective_date": date(2026, 8, 29),
        "source_status": SourceStatus.CURRENT,
        "text": "alpha beta",
        "source_path": Path("authority.md"),
    }
    chunks = [
        CorpusChunk(
            chunk_id="LOW::chunk-001",
            chunk_index=1,
            doc_id="LOW",
            authority_rank=2,
            **shared,
        ),
        CorpusChunk(
            chunk_id="HIGH::chunk-001",
            chunk_index=1,
            doc_id="HIGH",
            authority_rank=5,
            **shared,
        ),
    ]

    results = InMemoryRetriever(chunks).search("alpha")

    assert [result.doc_id for result in results] == ["HIGH", "LOW"]
    assert results[0].score == results[1].score
    assert results[0].ordering_signals is not None
    assert results[1].ordering_signals is not None
    assert (
        results[0].ordering_signals.ranking_score
        > results[1].ordering_signals.ranking_score
    )


def test_modest_authority_factor_does_not_override_strong_relevance() -> None:
    shared = {
        "domain": Domain.PRODUCT,
        "title": "Relevance Fixture",
        "version": "1.0",
        "effective_date": date(2026, 8, 29),
        "source_status": SourceStatus.CURRENT,
        "source_path": Path("relevance.md"),
    }
    chunks = [
        CorpusChunk(
            chunk_id="WEAK-HIGH::chunk-001",
            chunk_index=1,
            doc_id="WEAK-HIGH",
            authority_rank=5,
            text="alpha beta gamma delta",
            **shared,
        ),
        CorpusChunk(
            chunk_id="STRONG-LOW::chunk-001",
            chunk_index=1,
            doc_id="STRONG-LOW",
            authority_rank=2,
            text="alpha alpha alpha delta",
            **shared,
        ),
    ]

    results = BM25Retriever(chunks).search("alpha")

    assert [result.doc_id for result in results] == ["STRONG-LOW", "WEAK-HIGH"]
    assert results[0].score > results[1].score


@pytest.mark.parametrize(
    ("retriever_name", "expected_domain"),
    [
        ("product", Domain.PRODUCT),
        ("security", Domain.SECURITY),
        ("implementation", Domain.IMPLEMENTATION),
    ],
)
def test_specialist_boundary_prevents_cross_domain_results(
    retriever_name: str,
    expected_domain: Domain,
) -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)
    retriever = getattr(retrievers, retriever_name)

    results = retriever.search("customer implementation security product", k=5)

    assert results
    assert all(result.domain is expected_domain for result in results)


def test_specialist_boundary_uses_locked_offline_method_family() -> None:
    retrievers = build_offline_retrievers(KB_DIRECTORY)

    product = retrievers.product.search("SAML SCIM", k=1)[0]
    security = retrievers.security.search("TLS encryption", k=1)[0]
    implementation = retrievers.implementation.search("onboarding timeline", k=1)[0]

    assert product.retrieval_method is RetrievalMethod.HYBRID
    assert security.retrieval_method is RetrievalMethod.HYBRID
    assert implementation.retrieval_method is RetrievalMethod.SEMANTIC_SUBSTITUTE


def test_source_status_filter_applies_before_security_ranking() -> None:
    retriever = build_offline_retrievers(KB_DIRECTORY).security

    current = retriever.search(
        "TLS 1.2 transport protocol",
        filters=SearchFilters(source_statuses={SourceStatus.CURRENT}),
    )
    archived = retriever.search(
        "TLS 1.2 transport protocol",
        filters=SearchFilters(source_statuses={SourceStatus.ARCHIVED}),
    )

    assert current
    assert all(result.source_status == "current" for result in current)
    assert [result.doc_id for result in archived] == ["SEC-CTRL-OLD-001"]


def test_authority_document_and_effective_date_filters_apply_before_ranking() -> None:
    retriever = build_offline_retrievers(KB_DIRECTORY).security

    results = retriever.search(
        "TLS 1.2 transport protocol",
        filters=SearchFilters(
            min_authority_rank=5,
            doc_ids={"SEC-CTRL-001", "SEC-CTRL-OLD-001"},
            effective_on_or_before=date(2026, 7, 1),
        ),
    )

    assert [result.doc_id for result in results] == ["SEC-CTRL-001"]
    assert results[0].authority_rank == 5
    assert results[0].effective_date == "2026-07-01"


def test_domain_lock_cannot_be_bypassed_by_cross_domain_document_filter() -> None:
    retriever = build_offline_retrievers(KB_DIRECTORY).product

    results = retriever.search(
        "TLS encryption",
        filters=SearchFilters(doc_ids={"SEC-CTRL-001"}),
    )

    assert results == []


@pytest.mark.parametrize("invalid_k", [0, 6])
def test_specialist_boundary_rejects_values_outside_top_five(invalid_k: int) -> None:
    retriever = build_offline_retrievers(KB_DIRECTORY).product

    with pytest.raises(ValueError, match="between 1 and 5"):
        retriever.search("customer", k=invalid_k)


def test_specialist_boundary_never_returns_more_than_five() -> None:
    retriever = build_offline_retrievers(KB_DIRECTORY).security

    results = retriever.search("customer data security approval", k=5)

    assert len(results) <= 5


def test_specialist_boundary_drops_weak_tail_relative_to_best_result() -> None:
    retriever = build_offline_retrievers(KB_DIRECTORY).product

    results = retriever.search(
        "Can employees use SAML 2.0 and be provisioned automatically with SCIM 2.0?",
        k=5,
    )

    assert len(results) == 3
    assert results[-1].score >= results[0].score * 0.25
    assert {result.doc_id for result in results} == {
        "PROD-CAP-001",
        "PROD-DEPLOY-001",
        "PROD-AVAIL-001",
    }


def test_relative_score_floor_preserves_retention_conflict() -> None:
    retriever = build_offline_retrievers(KB_DIRECTORY).security

    results = retriever.search(
        "What is the post-termination data retention and deletion recovery window?",
        k=5,
    )

    assert {"SEC-RET-001", "SEC-RET-OPS-001"} <= {
        result.doc_id for result in results
    }


def test_relative_score_floor_preserves_relevant_archived_tls_evidence() -> None:
    retriever = build_offline_retrievers(KB_DIRECTORY).security

    results = retriever.search("TLS 1.2 transport protocol", k=5)

    assert {"SEC-CTRL-001", "SEC-CTRL-OLD-001"} <= {
        result.doc_id for result in results
    }


def test_search_filters_validate_authority_range() -> None:
    with pytest.raises(ValidationError):
        SearchFilters(min_authority_rank=6)
