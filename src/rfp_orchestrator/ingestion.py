"""Deterministic, review-first corpus preparation and guarded provider ingestion."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass
from hashlib import sha256
from math import log
from pathlib import Path
from typing import Any, Protocol

from rfp_orchestrator.config import Settings
from rfp_orchestrator.corpus import CorpusChunk, load_corpus_chunks
from rfp_orchestrator.models import Domain
from rfp_orchestrator.provider_config import (
    BM25_B,
    BM25_K1,
    CHUNK_MAX_CHARS,
    EMBEDDING_DIMENSION,
    EMBEDDING_ENCODING,
    HYBRID_DENSE_WEIGHT,
    HYBRID_SPARSE_WEIGHT,
    OPENAI_EMBEDDING_MODEL,
    PINECONE_CLOUD,
    PINECONE_INDEX_NAME,
    PINECONE_METRIC,
    PINECONE_NAMESPACE,
    PINECONE_REGION,
    PINECONE_VECTOR_TYPE,
    RETRIEVAL_TOP_K,
)
from rfp_orchestrator.retrieval import tokenize_terms

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CORPUS_DIRECTORY = PROJECT_ROOT / "data" / "kb"
DEFAULT_MANIFEST_PATH = PROJECT_ROOT / "outputs" / "ingestion_manifest_v1.json"
MANIFEST_SCHEMA_VERSION = "1.0"
UPLOAD_APPROVAL_TOKEN = "UPLOAD-NORTHSTAR-V1"
MAX_V1_RECORDS_PER_RUN = 100
HYBRID_DOMAINS = frozenset({Domain.PRODUCT, Domain.SECURITY})


class IngestionError(RuntimeError):
    """Base error for review-first ingestion."""


class IngestionConfigurationError(IngestionError):
    """Raised before provider initialization when configuration is unsafe or inconsistent."""


class IngestionApprovalError(IngestionError):
    """Raised before provider initialization when explicit upload approval is incomplete."""


class IngestionManifestMismatchError(IngestionError):
    """Raised when the reviewed manifest no longer matches the current corpus."""


class IngestionProviderResponseError(IngestionError):
    """Raised when a provider response violates the frozen ingestion contract."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _display_path(path: Path) -> str:
    try:
        return path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix()
    except ValueError:
        return path.name


@dataclass(frozen=True)
class SparseVector:
    """One Pinecone-compatible sparse vector."""

    indices: tuple[int, ...]
    values: tuple[float, ...]

    def provider_fields(self) -> dict[str, list[int] | list[float]]:
        return {"indices": list(self.indices), "values": list(self.values)}


@dataclass(frozen=True)
class PlannedRecord:
    """One reviewed record before its dense vector is requested."""

    record_id: str
    embedding_input: str
    sparse_vector: SparseVector | None
    metadata: dict[str, str | int]

    def public_summary(self) -> dict[str, Any]:
        sparse_payload = self.sparse_vector.provider_fields() if self.sparse_vector else None
        return {
            "record_id": self.record_id,
            "doc_id": self.metadata["doc_id"],
            "domain": self.metadata["domain"],
            "source_status": self.metadata["source_status"],
            "embedding_input_characters": len(self.embedding_input),
            "embedding_input_sha256": sha256(
                self.embedding_input.encode("utf-8")
            ).hexdigest(),
            "sparse_nonzero_count": len(self.sparse_vector.indices)
            if self.sparse_vector
            else 0,
            "sparse_vector_sha256": _digest(sparse_payload) if sparse_payload else None,
            "metadata_fields": sorted(self.metadata),
        }


@dataclass(frozen=True)
class IngestionPlan:
    """Complete deterministic plan used for review and, later, guarded execution."""

    corpus_directory: Path
    document_count: int
    records: tuple[PlannedRecord, ...]
    sparse_vocabulary_size: int
    sparse_encoder_sha256: str

    def public_manifest(self) -> dict[str, Any]:
        domain_counts = Counter(str(record.metadata["domain"]) for record in self.records)
        status_counts = Counter(str(record.metadata["source_status"]) for record in self.records)
        record_summaries = [record.public_summary() for record in self.records]
        manifest: dict[str, Any] = {
            "schema_version": MANIFEST_SCHEMA_VERSION,
            "mode": "dry_run",
            "corpus_directory": _display_path(self.corpus_directory),
            "chunk_max_characters": CHUNK_MAX_CHARS,
            "document_count": self.document_count,
            "record_count": len(self.records),
            "record_ids": [record.record_id for record in self.records],
            "domain_record_counts": dict(sorted(domain_counts.items())),
            "source_status_record_counts": dict(sorted(status_counts.items())),
            "hybrid_record_count": sum(
                record.metadata["domain"] in {domain.value for domain in HYBRID_DOMAINS}
                for record in self.records
            ),
            "dense_only_record_count": sum(
                record.metadata["domain"] == Domain.IMPLEMENTATION.value
                for record in self.records
            ),
            "embedding_input_characters": sum(
                len(record.embedding_input) for record in self.records
            ),
            "openai": {
                "model": OPENAI_EMBEDDING_MODEL,
                "dimensions": EMBEDDING_DIMENSION,
                "encoding_format": EMBEDDING_ENCODING,
                "planned_requests_if_approved": 1,
            },
            "pinecone": {
                "index": PINECONE_INDEX_NAME,
                "namespace": PINECONE_NAMESPACE,
                "vector_type": PINECONE_VECTOR_TYPE,
                "metric": PINECONE_METRIC,
                "cloud": PINECONE_CLOUD,
                "region": PINECONE_REGION,
                "planned_upsert_requests_if_approved": 1,
            },
            "retrieval": {
                "product": "hybrid_dense_sparse_top_5",
                "security": "hybrid_dense_sparse_top_5",
                "implementation": "dense_top_5",
                "top_k": RETRIEVAL_TOP_K,
                "bm25_k1": BM25_K1,
                "bm25_b": BM25_B,
                "hybrid_sparse_weight": HYBRID_SPARSE_WEIGHT,
                "hybrid_dense_weight": HYBRID_DENSE_WEIGHT,
                "sparse_vocabulary_size": self.sparse_vocabulary_size,
                "sparse_encoder_sha256": self.sparse_encoder_sha256,
            },
            "records": record_summaries,
            "network_calls_made": 0,
            "upload_authorized": False,
        }
        manifest["corpus_sha256"] = _digest(record_summaries)
        manifest["manifest_sha256"] = _digest(manifest)
        return manifest


@dataclass(frozen=True)
class IngestionResult:
    """Safe execution result with no credentials or vector values."""

    status: str
    manifest_sha256: str
    record_count: int
    embedding_model: str
    embedding_dimensions: int
    embedding_prompt_tokens: int | None
    embedding_total_tokens: int | None
    pinecone_index: str
    pinecone_namespace: str
    openai_request_count: int
    pinecone_upsert_request_count: int

    def public_fields(self) -> dict[str, str | int | None]:
        return asdict(self)


class BM25SparseEncoder:
    """Deterministic domain-aware BM25 document encoder using one shared vocabulary."""

    def __init__(self, chunks: Sequence[CorpusChunk]) -> None:
        hybrid_chunks = [chunk for chunk in chunks if chunk.domain in HYBRID_DOMAINS]
        if not hybrid_chunks:
            raise IngestionConfigurationError("hybrid sparse encoding requires corpus chunks")

        terms_by_record = {
            chunk.chunk_id: tokenize_terms(f"{chunk.title}\n{chunk.text}")
            for chunk in hybrid_chunks
        }
        vocabulary = sorted({term for terms in terms_by_record.values() for term in terms})
        self._term_indices = {term: index for index, term in enumerate(vocabulary)}
        self._terms_by_record = terms_by_record
        self._domain_statistics: dict[Domain, dict[str, Any]] = {}

        for domain in sorted(HYBRID_DOMAINS, key=lambda item: item.value):
            domain_chunks = [chunk for chunk in hybrid_chunks if chunk.domain is domain]
            document_frequency: Counter[str] = Counter()
            total_terms = 0
            for chunk in domain_chunks:
                terms = terms_by_record[chunk.chunk_id]
                document_frequency.update(set(terms))
                total_terms += len(terms)
            self._domain_statistics[domain] = {
                "document_count": len(domain_chunks),
                "average_document_length": total_terms / len(domain_chunks),
                "document_frequency": document_frequency,
            }

        digest_payload = {
            "k1": BM25_K1,
            "b": BM25_B,
            "vocabulary": vocabulary,
            "domains": {
                domain.value: {
                    "document_count": statistics["document_count"],
                    "average_document_length": round(
                        statistics["average_document_length"], 12
                    ),
                    "document_frequency": dict(
                        sorted(statistics["document_frequency"].items())
                    ),
                }
                for domain, statistics in self._domain_statistics.items()
            },
        }
        self._digest = _digest(digest_payload)

    @property
    def vocabulary_size(self) -> int:
        return len(self._term_indices)

    @property
    def digest(self) -> str:
        return self._digest

    def encode_document(self, chunk: CorpusChunk) -> SparseVector | None:
        if chunk.domain not in HYBRID_DOMAINS:
            return None

        terms = self._terms_by_record[chunk.chunk_id]
        counts = Counter(terms)
        statistics = self._domain_statistics[chunk.domain]
        document_count = int(statistics["document_count"])
        average_document_length = float(statistics["average_document_length"])
        document_frequency: Counter[str] = statistics["document_frequency"]
        document_length = len(terms)

        weighted_terms: list[tuple[int, float]] = []
        for term, term_frequency in counts.items():
            frequency = document_frequency[term]
            inverse_document_frequency = log(
                1 + (document_count - frequency + 0.5) / (frequency + 0.5)
            )
            length_normalization = BM25_K1 * (
                1 - BM25_B + BM25_B * document_length / average_document_length
            )
            value = inverse_document_frequency * (
                term_frequency * (BM25_K1 + 1)
            ) / (term_frequency + length_normalization)
            weighted_terms.append((self._term_indices[term], round(value, 12)))

        weighted_terms.sort(key=lambda item: item[0])
        return SparseVector(
            indices=tuple(index for index, _ in weighted_terms),
            values=tuple(value for _, value in weighted_terms),
        )

    def encode_query(self, domain: Domain, query: str) -> SparseVector:
        """Encode unique known query terms; query-time weighting is applied separately."""

        if domain not in HYBRID_DOMAINS:
            raise ValueError("sparse queries are only valid for Product and Security")
        indices = sorted(
            {
                self._term_indices[term]
                for term in tokenize_terms(query)
                if term in self._term_indices
            }
        )
        return SparseVector(indices=tuple(indices), values=tuple(1.0 for _ in indices))


def _record_metadata(chunk: CorpusChunk) -> dict[str, str | int]:
    return {
        "chunk_id": chunk.chunk_id,
        "chunk_index": chunk.chunk_index,
        "doc_id": chunk.doc_id,
        "domain": chunk.domain.value,
        "title": chunk.title,
        "text": chunk.text,
        "version": chunk.version,
        "effective_date": chunk.effective_date.isoformat(),
        "authority_rank": chunk.authority_rank,
        "source_status": chunk.source_status.value,
        "source_file": chunk.source_path.name,
    }


def build_ingestion_plan(
    corpus_directory: str | Path = DEFAULT_CORPUS_DIRECTORY,
) -> IngestionPlan:
    """Build a deterministic plan without credentials, provider imports, or network access."""

    directory = Path(corpus_directory)
    chunks = sorted(
        load_corpus_chunks(directory, max_chars=CHUNK_MAX_CHARS),
        key=lambda chunk: chunk.chunk_id,
    )
    if len(chunks) > MAX_V1_RECORDS_PER_RUN:
        raise IngestionConfigurationError(
            f"V1 ingestion is capped at {MAX_V1_RECORDS_PER_RUN} records per reviewed run; "
            f"the corpus produced {len(chunks)}"
        )

    sparse_encoder = BM25SparseEncoder(chunks)
    records = tuple(
        PlannedRecord(
            record_id=chunk.chunk_id,
            embedding_input=f"{chunk.title}\n\n{chunk.text}",
            sparse_vector=sparse_encoder.encode_document(chunk),
            metadata=_record_metadata(chunk),
        )
        for chunk in chunks
    )
    return IngestionPlan(
        corpus_directory=directory,
        document_count=len({chunk.doc_id for chunk in chunks}),
        records=records,
        sparse_vocabulary_size=sparse_encoder.vocabulary_size,
        sparse_encoder_sha256=sparse_encoder.digest,
    )


def write_manifest(
    plan: IngestionPlan,
    path: str | Path = DEFAULT_MANIFEST_PATH,
) -> dict[str, Any]:
    """Write the safe dry-run manifest for human review."""

    manifest = plan.public_manifest()
    manifest_path = Path(path)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def load_reviewed_manifest(path: str | Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    """Load a saved manifest and reject malformed or non-object JSON."""

    manifest_path = Path(path)
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise IngestionManifestMismatchError(
            f"could not load reviewed manifest '{manifest_path}': {type(error).__name__}"
        ) from error
    if not isinstance(value, dict):
        raise IngestionManifestMismatchError("reviewed manifest must contain one JSON object")
    return value


def validate_runtime_settings(settings: Settings, *, require_secrets: bool) -> None:
    """Fail before client creation when runtime values drift from the frozen design."""

    expected_optional = {
        "OPENAI_EMBEDDING_MODEL": (
            settings.openai_embedding_model,
            OPENAI_EMBEDDING_MODEL,
        ),
        "PINECONE_INDEX": (settings.pinecone_index, PINECONE_INDEX_NAME),
        "PINECONE_NAMESPACE": (settings.pinecone_namespace, PINECONE_NAMESPACE),
    }
    for variable, (observed, expected) in expected_optional.items():
        if observed is not None and observed != expected:
            raise IngestionConfigurationError(
                f"{variable} must be '{expected}' for the reviewed V1 manifest"
            )

    if not require_secrets:
        return

    required = {
        "OPENAI_API_KEY": settings.openai_api_key,
        "OPENAI_EMBEDDING_MODEL": settings.openai_embedding_model,
        "PINECONE_API_KEY": settings.pinecone_api_key,
        "PINECONE_INDEX": settings.pinecone_index,
        "PINECONE_NAMESPACE": settings.pinecone_namespace,
    }
    missing = [variable for variable, value in required.items() if not value]
    if missing:
        raise IngestionConfigurationError(
            "live ingestion configuration is incomplete: " + ", ".join(missing)
        )


class EmbeddingsResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class OpenAIClient(Protocol):
    embeddings: EmbeddingsResource


class PineconeIndex(Protocol):
    def upsert(self, **kwargs: Any) -> Any: ...


OpenAIClientFactory = Callable[[str], OpenAIClient]
PineconeIndexFactory = Callable[[str, str], PineconeIndex]


def _default_openai_client_factory(api_key: str) -> OpenAIClient:
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _default_pinecone_index_factory(api_key: str, index_name: str) -> PineconeIndex:
    from pinecone import Pinecone

    return Pinecone(api_key=api_key).Index(index_name)


def _validate_reviewed_manifest(
    plan: IngestionPlan,
    reviewed_manifest: Mapping[str, Any],
    expected_manifest_sha256: str,
) -> dict[str, Any]:
    current = plan.public_manifest()
    current_hash = str(current["manifest_sha256"])
    reviewed_hash = str(reviewed_manifest.get("manifest_sha256", ""))
    if not expected_manifest_sha256:
        raise IngestionApprovalError("expected manifest SHA-256 is required for upload")
    if reviewed_hash != expected_manifest_sha256:
        raise IngestionManifestMismatchError(
            "the supplied manifest SHA-256 does not match the reviewed file"
        )
    if current_hash != reviewed_hash or dict(reviewed_manifest) != current:
        raise IngestionManifestMismatchError(
            "the corpus or configuration changed after the manifest was reviewed; "
            "run the dry run again"
        )
    return current


def _ordered_embeddings(response: Any, expected_count: int) -> list[list[float]]:
    response_data = _field(response, "data")
    if not isinstance(response_data, Sequence) or len(response_data) != expected_count:
        raise IngestionProviderResponseError(
            "OpenAI embedding count did not match the reviewed record count"
        )

    indexed: list[tuple[int, list[float]]] = []
    for fallback_index, item in enumerate(response_data):
        item_index = int(_field(item, "index", fallback_index))
        vector = _field(item, "embedding")
        if not isinstance(vector, Sequence) or isinstance(vector, (str, bytes)):
            raise IngestionProviderResponseError("OpenAI returned an invalid embedding vector")
        numeric = [float(value) for value in vector]
        if len(numeric) != EMBEDDING_DIMENSION:
            raise IngestionProviderResponseError(
                "OpenAI embedding dimension did not match the reviewed Pinecone index"
            )
        indexed.append((item_index, numeric))

    indexed.sort(key=lambda item: item[0])
    if [index for index, _ in indexed] != list(range(expected_count)):
        raise IngestionProviderResponseError(
            "OpenAI embedding indexes were missing, duplicated, or out of range"
        )
    return [vector for _, vector in indexed]


def execute_reviewed_ingestion(
    *,
    plan: IngestionPlan,
    reviewed_manifest: Mapping[str, Any],
    expected_manifest_sha256: str,
    approval_token: str,
    settings: Settings | None = None,
    openai_client_factory: OpenAIClientFactory = _default_openai_client_factory,
    pinecone_index_factory: PineconeIndexFactory = _default_pinecone_index_factory,
) -> IngestionResult:
    """Execute one reviewed embedding request and one upsert, with no automatic retry."""

    if approval_token != UPLOAD_APPROVAL_TOKEN:
        raise IngestionApprovalError(
            "the exact upload approval token is required; dry run remains the default"
        )

    active_settings = settings or Settings()
    validate_runtime_settings(active_settings, require_secrets=True)
    manifest = _validate_reviewed_manifest(
        plan,
        reviewed_manifest,
        expected_manifest_sha256,
    )

    openai_client = openai_client_factory(active_settings.openai_api_key or "")
    embedding_response = openai_client.embeddings.create(
        model=OPENAI_EMBEDDING_MODEL,
        input=[record.embedding_input for record in plan.records],
        encoding_format=EMBEDDING_ENCODING,
    )
    response_model = str(_field(embedding_response, "model", ""))
    if response_model != OPENAI_EMBEDDING_MODEL:
        raise IngestionProviderResponseError(
            "OpenAI returned a different embedding model than the reviewed manifest"
        )
    dense_vectors = _ordered_embeddings(embedding_response, len(plan.records))

    provider_records: list[dict[str, Any]] = []
    for planned, dense_vector in zip(plan.records, dense_vectors, strict=True):
        provider_record: dict[str, Any] = {
            "id": planned.record_id,
            "values": dense_vector,
            "metadata": planned.metadata,
        }
        if planned.sparse_vector is not None:
            provider_record["sparse_values"] = planned.sparse_vector.provider_fields()
        provider_records.append(provider_record)

    index = pinecone_index_factory(
        active_settings.pinecone_api_key or "",
        active_settings.pinecone_index or "",
    )
    upsert_response = index.upsert(
        vectors=provider_records,
        namespace=active_settings.pinecone_namespace or "",
    )
    upserted_count = _field(upsert_response, "upserted_count")
    if upserted_count is None or int(upserted_count) != len(plan.records):
        raise IngestionProviderResponseError(
            "Pinecone did not confirm the reviewed record count; do not retry automatically"
        )

    usage = _field(embedding_response, "usage")
    return IngestionResult(
        status="uploaded",
        manifest_sha256=str(manifest["manifest_sha256"]),
        record_count=len(plan.records),
        embedding_model=OPENAI_EMBEDDING_MODEL,
        embedding_dimensions=EMBEDDING_DIMENSION,
        embedding_prompt_tokens=_field(usage, "prompt_tokens"),
        embedding_total_tokens=_field(usage, "total_tokens"),
        pinecone_index=PINECONE_INDEX_NAME,
        pinecone_namespace=PINECONE_NAMESPACE,
        openai_request_count=1,
        pinecone_upsert_request_count=1,
    )
