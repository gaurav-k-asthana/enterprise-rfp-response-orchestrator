import re
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from enum import Enum
from math import log, sqrt
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, Field, model_validator

from rfp_orchestrator.corpus import CorpusChunk, SourceStatus, load_corpus_chunks
from rfp_orchestrator.models import Domain
from rfp_orchestrator.provider_config import (
    BM25_B,
    BM25_K1,
    HYBRID_DENSE_WEIGHT,
    HYBRID_SPARSE_WEIGHT,
    RETRIEVAL_MIN_RELATIVE_SCORE,
    RETRIEVAL_TOP_K,
)


class RetrievalMethod(str, Enum):
    BOOTSTRAP = "bootstrap"
    LEXICAL = "lexical"
    SEMANTIC_SUBSTITUTE = "semantic_substitute"
    HYBRID = "hybrid"
    DENSE = "dense"


class HybridScoreComponents(BaseModel):
    lexical_raw: float | None = Field(default=None, ge=0)
    semantic_raw: float | None = Field(default=None, ge=0)
    lexical_normalized: float | None = Field(default=None, ge=0, le=1)
    semantic_normalized: float | None = Field(default=None, ge=0, le=1)
    lexical_weight: float = Field(ge=0, le=1)
    semantic_weight: float = Field(ge=0, le=1)
    provider_combined_score: float | None = None
    visibility: Literal["full", "combined_only"] = "full"

    @model_validator(mode="after")
    def validate_observability_mode(self) -> "HybridScoreComponents":
        if abs(self.lexical_weight + self.semantic_weight - 1.0) > 1e-9:
            raise ValueError("hybrid weights must sum to 1.0")

        detailed = (
            self.lexical_raw,
            self.semantic_raw,
            self.lexical_normalized,
            self.semantic_normalized,
        )
        if self.visibility == "full":
            if any(value is None for value in detailed):
                raise ValueError("full hybrid visibility requires every score component")
            if self.provider_combined_score is not None:
                raise ValueError("full hybrid visibility cannot include a provider score")
        else:
            if any(value is not None for value in detailed):
                raise ValueError("combined-only visibility cannot claim hidden components")
            if self.provider_combined_score is None:
                raise ValueError("combined-only visibility requires the provider score")
        return self


class SourceOrderingSignals(BaseModel):
    lifecycle_factor: float = Field(ge=0, le=1)
    authority_factor: float = Field(ge=0, le=1)
    ranking_score: float = Field(ge=0)


class EvidenceChunk(BaseModel):
    chunk_id: str
    doc_id: str
    domain: Domain
    title: str
    text: str
    version: str
    effective_date: str
    authority_rank: int = Field(ge=1, le=5)
    source_status: str
    score: float
    retrieval_method: RetrievalMethod
    score_components: HybridScoreComponents | None = None
    ordering_signals: SourceOrderingSignals | None = None

    @model_validator(mode="after")
    def hybrid_results_expose_score_components(self) -> "EvidenceChunk":
        if self.retrieval_method is RetrievalMethod.HYBRID and self.score_components is None:
            raise ValueError("hybrid evidence requires observable score_components")
        if self.retrieval_method is not RetrievalMethod.HYBRID and self.score_components is not None:
            raise ValueError("score_components are only valid for hybrid evidence")
        return self


class SearchFilters(BaseModel):
    source_statuses: set[SourceStatus] | None = None
    min_authority_rank: int | None = Field(default=None, ge=1, le=5)
    doc_ids: set[str] | None = None
    effective_on_or_before: date | None = None


class Retriever(Protocol):
    def search(self, query: str, *, k: int = 5) -> list[EvidenceChunk]: ...


def enforce_top_k(k: int) -> int:
    if not 1 <= k <= RETRIEVAL_TOP_K:
        raise ValueError(f"V1 retrieval k must be between 1 and {RETRIEVAL_TOP_K}")
    return k


def apply_relative_score_floor(
    results: Sequence[EvidenceChunk],
    *,
    minimum_ratio: float = RETRIEVAL_MIN_RELATIVE_SCORE,
) -> list[EvidenceChunk]:
    """Drop weak tail results relative to the strongest result in one query.

    Retrieval remains "up to Top 5": this guard prevents marginal evidence from
    filling unused slots merely because the corpus is small.
    """

    if not 0 <= minimum_ratio <= 1:
        raise ValueError("minimum relative score must be between zero and one")
    if not results:
        return []

    strongest_score = max(result.score for result in results)
    if strongest_score <= 0:
        return []
    minimum_score = strongest_score * minimum_ratio
    return [result for result in results if result.score >= minimum_score]


TOKEN_PATTERN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def tokenize_terms(text: str) -> list[str]:
    """Return the shared deterministic terms used by BM25 and sparse ingestion."""

    return TOKEN_PATTERN.findall(text.lower())


def _tokenize(text: str) -> set[str]:
    """Normalize unique text terms for the transparent bootstrap score."""

    return set(tokenize_terms(text))


def _token_overlap_score(query: str, chunk: CorpusChunk) -> float:
    """Return simple query-token coverage; this is intentionally not BM25."""

    query_tokens = _tokenize(query)
    searchable_tokens = _tokenize(f"{chunk.title}\n{chunk.text}")
    return len(query_tokens & searchable_tokens) / len(query_tokens)


@dataclass(frozen=True)
class _ScoredChunk:
    score: float
    chunk: CorpusChunk
    score_components: HybridScoreComponents | None = None


@dataclass(frozen=True)
class _OrderedChunk:
    score: float
    chunk: CorpusChunk
    score_components: HybridScoreComponents | None
    ordering_signals: SourceOrderingSignals


LIFECYCLE_FACTORS = {
    SourceStatus.CURRENT: 1.0,
    SourceStatus.ARCHIVED: 0.45,
}


def _source_ordering_signals(item: _ScoredChunk) -> SourceOrderingSignals:
    lifecycle_factor = LIFECYCLE_FACTORS[item.chunk.source_status]
    authority_factor = 0.90 + 0.02 * item.chunk.authority_rank
    return SourceOrderingSignals(
        lifecycle_factor=lifecycle_factor,
        authority_factor=authority_factor,
        ranking_score=item.score * lifecycle_factor * authority_factor,
    )


class InMemoryRetriever:
    """Credential-free deterministic retrieval over validated local chunks.

    Step 1.16 intentionally uses a simple token-overlap bootstrap score. Later
    steps replace domain-specific scoring without changing the Retriever contract.
    """

    def __init__(
        self,
        chunks: Sequence[CorpusChunk],
    ) -> None:
        self._chunks = tuple(chunks)
        self._retrieval_method = RetrievalMethod.BOOTSTRAP

    @classmethod
    def from_corpus_directory(
        cls,
        directory: str | Path,
        *,
        max_chars: int = 1_200,
    ) -> "InMemoryRetriever":
        """Build a retriever locally without initializing any provider client."""

        return cls(
            load_corpus_chunks(directory, max_chars=max_chars),
        )

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    def _score(self, query: str, chunk: CorpusChunk) -> float:
        return _token_overlap_score(query, chunk)

    def _score_chunks(self, query: str) -> list[_ScoredChunk]:
        return [
            _ScoredChunk(score=score, chunk=chunk)
            for chunk in self._chunks
            if (score := self._score(query, chunk)) > 0
        ]

    def search(self, query: str, *, k: int = 5) -> list[EvidenceChunk]:
        """Return matching chunks in repeatable score/ID order."""

        limit = enforce_top_k(k)
        if not _tokenize(query):
            raise ValueError("retrieval query must contain at least one searchable token")

        scored = self._score_chunks(query)
        ordered = [
            _OrderedChunk(
                score=item.score,
                chunk=item.chunk,
                score_components=item.score_components,
                ordering_signals=_source_ordering_signals(item),
            )
            for item in scored
        ]
        ordered.sort(
            key=lambda item: (
                -item.ordering_signals.ranking_score,
                -item.score,
                -item.chunk.authority_rank,
                item.chunk.chunk_id,
            )
        )

        return [
            EvidenceChunk(
                chunk_id=item.chunk.chunk_id,
                doc_id=item.chunk.doc_id,
                domain=item.chunk.domain,
                title=item.chunk.title,
                text=item.chunk.text,
                version=item.chunk.version,
                effective_date=item.chunk.effective_date.isoformat(),
                authority_rank=item.chunk.authority_rank,
                source_status=item.chunk.source_status.value,
                score=round(item.score, 6),
                retrieval_method=self._retrieval_method,
                score_components=item.score_components,
                ordering_signals=item.ordering_signals,
            )
            for item in ordered[:limit]
        ]


class BM25Scorer:
    """Deterministic BM25-style scoring over one fixed collection of chunks."""

    def __init__(
        self,
        chunks: Sequence[CorpusChunk],
        *,
        k1: float = BM25_K1,
        b: float = BM25_B,
    ) -> None:
        if not chunks:
            raise ValueError("BM25 scoring requires at least one corpus chunk")
        if k1 <= 0:
            raise ValueError("BM25 k1 must be greater than zero")
        if not 0 <= b <= 1:
            raise ValueError("BM25 b must be between zero and one")

        self._k1 = k1
        self._b = b
        self._document_count = len(chunks)
        self._term_counts: dict[str, Counter[str]] = {}
        self._document_frequency: Counter[str] = Counter()

        total_terms = 0
        for chunk in chunks:
            terms = tokenize_terms(f"{chunk.title}\n{chunk.text}")
            counts = Counter(terms)
            self._term_counts[chunk.chunk_id] = counts
            self._document_frequency.update(counts.keys())
            total_terms += len(terms)
        self._average_document_length = total_terms / self._document_count

    def score(self, query: str, chunk: CorpusChunk) -> float:
        """Score exact query terms using BM25 term rarity, frequency, and length."""

        counts = self._term_counts[chunk.chunk_id]
        document_length = sum(counts.values())
        score = 0.0
        for term in set(tokenize_terms(query)):
            term_frequency = counts[term]
            if term_frequency == 0:
                continue
            document_frequency = self._document_frequency[term]
            inverse_document_frequency = log(
                1
                + (self._document_count - document_frequency + 0.5)
                / (document_frequency + 0.5)
            )
            length_normalization = self._k1 * (
                1
                - self._b
                + self._b * document_length / self._average_document_length
            )
            score += inverse_document_frequency * (
                term_frequency * (self._k1 + 1)
            ) / (term_frequency + length_normalization)
        return score


class BM25Retriever(InMemoryRetriever):
    """Local lexical retriever for Product and Security/Compliance collections."""

    def __init__(
        self,
        chunks: Sequence[CorpusChunk],
        *,
        k1: float = BM25_K1,
        b: float = BM25_B,
    ) -> None:
        super().__init__(chunks)
        self._retrieval_method = RetrievalMethod.LEXICAL
        self._bm25 = BM25Scorer(chunks, k1=k1, b=b)

    def _score(self, query: str, chunk: CorpusChunk) -> float:
        return self._bm25.score(query, chunk)


SEMANTIC_CONCEPTS: dict[str, tuple[str, ...]] = {
    "identity_access": (
        "saml",
        "single sign on",
        "sso",
        "scim",
        "user provisioning",
        "identity provider",
        "identity platform",
        "employee accounts",
        "synchronize users",
        "provision users",
    ),
    "key_management": (
        "customer managed encryption keys",
        "customer managed keys",
        "cmek",
        "cmk",
        "bring your own key",
        "byok",
        "control our own encryption keys",
        "key policy",
    ),
    "product_availability": (
        "generally available",
        "ga",
        "production ready",
        "currently supported",
        "roadmap",
        "not generally available",
        "unsupported",
    ),
    "deployment_model": (
        "standard cloud",
        "enterprise cloud",
        "on premises",
        "private data center",
        "customer operated",
        "kubernetes package",
        "hosting environment",
    ),
    "integration": (
        "salesforce",
        "sap s 4hana",
        "connector",
        "integration",
        "connect our systems",
    ),
    "encryption": (
        "encryption",
        "encrypted",
        "aes 256",
        "tls",
        "data at rest",
        "data in transit",
        "protect stored data",
    ),
    "assurance": (
        "soc 2",
        "type ii",
        "iso 27001",
        "audit report",
        "independent security audit",
        "certification",
        "assurance evidence",
    ),
    "government_compliance": (
        "fips",
        "fedramp",
        "government authorization",
        "public sector certification",
    ),
    "data_residency": (
        "data residency",
        "european union",
        "europe",
        "united states",
        "regional hosting",
        "data location",
        "records stay",
    ),
    "data_retention": (
        "retention",
        "retained",
        "deletion",
        "recovery window",
        "contract termination",
        "keep our data",
    ),
    "service_level": (
        "uptime",
        "availability target",
        "sla",
        "service credit",
        "service level",
    ),
    "proposal_governance": (
        "approval",
        "human review",
        "commitment",
        "authority",
        "conflicting evidence",
        "cannot confirm",
    ),
    "delivery_process": (
        "implementation",
        "onboarding",
        "rollout",
        "deployment project",
        "go live",
    ),
    "timeline": (
        "how long",
        "duration",
        "timeline",
        "schedule",
        "weeks",
        "deadline",
        "completion date",
        "lasts",
    ),
    "readiness": (
        "prerequisite",
        "prerequisites",
        "ready",
        "readiness",
        "before work begins",
        "access",
        "staffing",
    ),
    "customer_team": (
        "customer provides",
        "customer role",
        "customer roles",
        "who needs",
        "participate",
        "our side",
        "sponsor",
        "administrator",
        "integration owners",
        "test users",
    ),
    "delivery_risk": (
        "delay",
        "delayed",
        "slip",
        "scope change",
        "dependencies",
        "unavailable",
        "complex",
        "change the timeline",
    ),
    "discovery": (
        "discovery",
        "kickoff",
        "workshop",
        "requirements session",
    ),
    "validation": (
        "user acceptance testing",
        "uat",
        "test scenarios",
        "data validation",
        "test resources",
    ),
    "enablement": (
        "enablement",
        "training",
        "administrator education",
    ),
}


def _normalize_phrase_text(text: str) -> str:
    return " ".join(tokenize_terms(text))


def _semantic_features(text: str) -> set[str]:
    normalized = f" {_normalize_phrase_text(text)} "
    return {
        concept
        for concept, indicators in SEMANTIC_CONCEPTS.items()
        if any(f" {_normalize_phrase_text(indicator)} " in normalized for indicator in indicators)
    }


class SemanticSubstituteScorer:
    """Rule-based offline surrogate for semantic similarity, not embeddings."""

    def score(self, query: str, chunk: CorpusChunk) -> float:
        searchable_text = f"{chunk.title}\n{chunk.text}"
        query_concepts = _semantic_features(query)
        chunk_concepts = _semantic_features(searchable_text)
        shared_concepts = query_concepts & chunk_concepts
        concept_score = 0.0
        if query_concepts and chunk_concepts:
            concept_score = len(shared_concepts) / sqrt(
                len(query_concepts) * len(chunk_concepts)
            )

        query_tokens = _tokenize(query)
        chunk_tokens = _tokenize(searchable_text)
        lexical_score = len(query_tokens & chunk_tokens) / len(query_tokens)
        return 0.85 * concept_score + 0.15 * lexical_score


class SemanticSubstituteRetriever(InMemoryRetriever):
    """Deterministic semantic surrogate for offline Implementation tests."""

    def __init__(self, chunks: Sequence[CorpusChunk]) -> None:
        super().__init__(chunks)
        self._retrieval_method = RetrievalMethod.SEMANTIC_SUBSTITUTE
        self._semantic_scorer = SemanticSubstituteScorer()

    def _score(self, query: str, chunk: CorpusChunk) -> float:
        return self._semantic_scorer.score(query, chunk)


class HybridRetriever(InMemoryRetriever):
    """Deterministic weighted fusion for Product and Security/Compliance."""

    def __init__(
        self,
        chunks: Sequence[CorpusChunk],
        *,
        lexical_weight: float = HYBRID_SPARSE_WEIGHT,
        semantic_weight: float = HYBRID_DENSE_WEIGHT,
    ) -> None:
        if lexical_weight < 0 or semantic_weight < 0:
            raise ValueError("hybrid weights cannot be negative")
        if abs(lexical_weight + semantic_weight - 1.0) > 1e-9:
            raise ValueError("hybrid weights must sum to 1.0")

        super().__init__(chunks)
        self._retrieval_method = RetrievalMethod.HYBRID
        self._lexical_weight = lexical_weight
        self._semantic_weight = semantic_weight
        self._bm25 = BM25Scorer(chunks)
        self._semantic_scorer = SemanticSubstituteScorer()

    def _score_chunks(self, query: str) -> list[_ScoredChunk]:
        lexical_scores = {
            chunk.chunk_id: self._bm25.score(query, chunk) for chunk in self._chunks
        }
        semantic_scores = {
            chunk.chunk_id: self._semantic_scorer.score(query, chunk)
            for chunk in self._chunks
        }
        max_lexical = max(lexical_scores.values(), default=0.0)
        max_semantic = max(semantic_scores.values(), default=0.0)

        scored: list[_ScoredChunk] = []
        for chunk in self._chunks:
            lexical_raw = lexical_scores[chunk.chunk_id]
            semantic_raw = semantic_scores[chunk.chunk_id]
            lexical_normalized = lexical_raw / max_lexical if max_lexical else 0.0
            semantic_normalized = semantic_raw / max_semantic if max_semantic else 0.0
            fused_score = (
                self._lexical_weight * lexical_normalized
                + self._semantic_weight * semantic_normalized
            )
            if fused_score == 0:
                continue
            scored.append(
                _ScoredChunk(
                    score=fused_score,
                    chunk=chunk,
                    score_components=HybridScoreComponents(
                        lexical_raw=lexical_raw,
                        semantic_raw=semantic_raw,
                        lexical_normalized=lexical_normalized,
                        semantic_normalized=semantic_normalized,
                        lexical_weight=self._lexical_weight,
                        semantic_weight=self._semantic_weight,
                    ),
                )
            )
        return scored


def _apply_metadata_filters(
    chunks: Sequence[CorpusChunk],
    filters: SearchFilters | None,
) -> list[CorpusChunk]:
    if filters is None:
        return list(chunks)
    return [
        chunk
        for chunk in chunks
        if (
            filters.source_statuses is None
            or chunk.source_status in filters.source_statuses
        )
        and (
            filters.min_authority_rank is None
            or chunk.authority_rank >= filters.min_authority_rank
        )
        and (filters.doc_ids is None or chunk.doc_id in filters.doc_ids)
        and (
            filters.effective_on_or_before is None
            or chunk.effective_date <= filters.effective_on_or_before
        )
    ]


class SpecialistRetriever:
    """Domain-locked, filtered Top-5 boundary used by specialist tools."""

    def __init__(self, chunks: Sequence[CorpusChunk], *, domain: Domain) -> None:
        domain_chunks = [chunk for chunk in chunks if chunk.domain is domain]
        if not domain_chunks:
            raise ValueError(f"no corpus chunks are available for domain '{domain.value}'")
        self._domain = domain
        self._domain_chunks = tuple(domain_chunks)

    @property
    def domain(self) -> Domain:
        return self._domain

    @property
    def chunk_count(self) -> int:
        return len(self._domain_chunks)

    def search(
        self,
        query: str,
        *,
        k: int = 5,
        filters: SearchFilters | None = None,
    ) -> list[EvidenceChunk]:
        limit = enforce_top_k(k)
        candidates = _apply_metadata_filters(self._domain_chunks, filters)
        if not candidates:
            return []

        if self._domain in {Domain.PRODUCT, Domain.SECURITY}:
            retriever: InMemoryRetriever = HybridRetriever(candidates)
        else:
            retriever = SemanticSubstituteRetriever(candidates)
        return apply_relative_score_floor(retriever.search(query, k=limit))


@dataclass(frozen=True)
class OfflineSpecialistRetrievers:
    product: SpecialistRetriever
    security: SpecialistRetriever
    implementation: SpecialistRetriever


def build_offline_retrievers(
    corpus_directory: str | Path,
    *,
    max_chars: int = 1_200,
) -> OfflineSpecialistRetrievers:
    """Build the three domain-locked local tool boundaries with no providers."""

    chunks = load_corpus_chunks(corpus_directory, max_chars=max_chars)
    return OfflineSpecialistRetrievers(
        product=SpecialistRetriever(chunks, domain=Domain.PRODUCT),
        security=SpecialistRetriever(chunks, domain=Domain.SECURITY),
        implementation=SpecialistRetriever(chunks, domain=Domain.IMPLEMENTATION),
    )
