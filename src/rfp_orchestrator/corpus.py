"""Validated loading and deterministic chunking for synthetic KB documents."""

from __future__ import annotations

import textwrap
from datetime import date
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rfp_orchestrator.models import Domain


class CorpusValidationError(ValueError):
    """Raised when a corpus source cannot be trusted as valid input."""


class SourceStatus(str, Enum):
    CURRENT = "current"
    ARCHIVED = "archived"


class SourceDocument(BaseModel):
    """One validated knowledge-base source plus its Markdown body."""

    model_config = ConfigDict(extra="forbid")

    doc_id: str = Field(min_length=1)
    domain: Domain
    title: str = Field(min_length=1)
    version: str = Field(min_length=1)
    effective_date: date
    authority_rank: int = Field(ge=1, le=5)
    status: SourceStatus
    text: str = Field(min_length=1)
    source_path: Path


class CorpusChunk(BaseModel):
    """A deterministic chunk that retains all source provenance."""

    chunk_id: str
    chunk_index: int = Field(ge=1)
    doc_id: str
    domain: Domain
    title: str
    version: str
    effective_date: date
    authority_rank: int = Field(ge=1, le=5)
    source_status: SourceStatus
    text: str = Field(min_length=1)
    source_path: Path


REQUIRED_METADATA_FIELDS = frozenset(
    {
        "doc_id",
        "domain",
        "title",
        "version",
        "effective_date",
        "authority_rank",
        "status",
    }
)


def _parse_front_matter(raw_text: str, source_path: Path) -> tuple[dict[str, str], str]:
    lines = raw_text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise CorpusValidationError(f"{source_path}: expected opening '---' front-matter line")

    try:
        closing_index = next(
            index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---"
        )
    except StopIteration as error:
        raise CorpusValidationError(
            f"{source_path}: expected closing '---' front-matter line"
        ) from error

    metadata: dict[str, str] = {}
    for line_number, line in enumerate(lines[1:closing_index], start=2):
        if not line.strip():
            continue
        if ":" not in line:
            raise CorpusValidationError(
                f"{source_path}:{line_number}: metadata must use 'field: value'"
            )
        key, value = (part.strip() for part in line.split(":", maxsplit=1))
        if not key or not value:
            raise CorpusValidationError(
                f"{source_path}:{line_number}: metadata field and value cannot be blank"
            )
        if key in metadata:
            raise CorpusValidationError(
                f"{source_path}:{line_number}: duplicate metadata field '{key}'"
            )
        metadata[key] = value

    missing = sorted(REQUIRED_METADATA_FIELDS - metadata.keys())
    if missing:
        raise CorpusValidationError(
            f"{source_path}: missing required metadata: {', '.join(missing)}"
        )

    body = "\n".join(lines[closing_index + 1 :]).strip()
    if not body:
        raise CorpusValidationError(f"{source_path}: document body cannot be blank")
    return metadata, body


def load_source_document(path: str | Path) -> SourceDocument:
    """Load one Markdown source and fail clearly if its contract is invalid."""

    source_path = Path(path)
    if source_path.suffix.lower() != ".md":
        raise CorpusValidationError(f"{source_path}: corpus sources must be Markdown files")

    try:
        raw_text = source_path.read_text(encoding="utf-8")
    except OSError as error:
        raise CorpusValidationError(f"{source_path}: could not read source: {error}") from error

    metadata, body = _parse_front_matter(raw_text, source_path)
    try:
        return SourceDocument(**metadata, text=body, source_path=source_path)
    except ValidationError as error:
        raise CorpusValidationError(f"{source_path}: invalid source metadata: {error}") from error


def load_source_documents(directory: str | Path) -> list[SourceDocument]:
    """Load every Markdown source in filename order and reject duplicate IDs."""

    corpus_directory = Path(directory)
    paths = sorted(corpus_directory.glob("*.md"))
    if not paths:
        raise CorpusValidationError(f"{corpus_directory}: no Markdown corpus sources found")

    documents: list[SourceDocument] = []
    seen_ids: dict[str, Path] = {}
    for path in paths:
        document = load_source_document(path)
        if document.doc_id in seen_ids:
            raise CorpusValidationError(
                f"{path}: duplicate doc_id '{document.doc_id}' also used by "
                f"{seen_ids[document.doc_id]}"
            )
        seen_ids[document.doc_id] = path
        documents.append(document)
    return documents


def _deterministic_text_chunks(text: str, max_chars: int) -> list[str]:
    if max_chars < 1:
        raise ValueError("max_chars must be at least 1")

    paragraphs = [paragraph.strip() for paragraph in text.split("\n\n") if paragraph.strip()]
    pieces: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= max_chars:
            pieces.append(paragraph)
            continue
        pieces.extend(
            textwrap.wrap(
                paragraph,
                width=max_chars,
                break_long_words=True,
                break_on_hyphens=False,
            )
        )

    chunks: list[str] = []
    current = ""
    for piece in pieces:
        candidate = piece if not current else f"{current}\n\n{piece}"
        if current and len(candidate) > max_chars:
            chunks.append(current)
            current = piece
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def chunk_document(document: SourceDocument, *, max_chars: int = 1_200) -> list[CorpusChunk]:
    """Create repeatable, human-readable chunk IDs for one validated source."""

    texts = _deterministic_text_chunks(document.text, max_chars)
    return [
        CorpusChunk(
            chunk_id=f"{document.doc_id}::chunk-{index:03d}",
            chunk_index=index,
            doc_id=document.doc_id,
            domain=document.domain,
            title=document.title,
            version=document.version,
            effective_date=document.effective_date,
            authority_rank=document.authority_rank,
            source_status=document.status,
            text=chunk_text,
            source_path=document.source_path,
        )
        for index, chunk_text in enumerate(texts, start=1)
    ]


def load_corpus_chunks(directory: str | Path, *, max_chars: int = 1_200) -> list[CorpusChunk]:
    """Validate and chunk a corpus directory with no network or provider calls."""

    return [
        chunk
        for document in load_source_documents(directory)
        for chunk in chunk_document(document, max_chars=max_chars)
    ]
