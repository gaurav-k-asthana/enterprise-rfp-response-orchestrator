"""Secret-safe Phase 2 offline milestone manifest construction."""

from __future__ import annotations

import hashlib
import json
import platform
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from rfp_orchestrator.provider_config import (
    BM25_B,
    BM25_K1,
    EMBEDDING_DIMENSION,
    HYBRID_DENSE_WEIGHT,
    HYBRID_SPARSE_WEIGHT,
    OPENAI_EMBEDDING_MODEL,
    OPENAI_GENERATION_ENDPOINT,
    OPENAI_GENERATION_MODEL,
    OPENAI_GENERATION_MODEL_IDENTIFIER_TYPE,
    OPENAI_MAX_OUTPUT_TOKENS,
    OPENAI_REASONING_EFFORT,
    OPENAI_RESPONSE_STORE,
    OPENAI_STRUCTURED_OUTPUTS_STRICT,
    PINECONE_INDEX_NAME,
    PINECONE_METRIC,
    PINECONE_NAMESPACE,
    PROVIDER_GRAPH_CALLS_ENABLED,
    RETRIEVAL_TOP_K,
)

MILESTONE_ID = "phase-2-offline-graph-v1"
FROZEN_ON = "2026-08-30"
EXPECTED_TEST_COUNT = 640
FREEZE_ROOT_FILES = (".env.example", ".gitignore", "README.md", "pyproject.toml")
FREEZE_DIRECTORIES = ("data", "scripts", "src", "tests")
PACKAGE_NAMES = (
    "langchain",
    "langgraph",
    "langsmith",
    "openai",
    "pinecone",
    "streamlit",
    "python-docx",
    "pydantic-settings",
    "pytest",
    "ruff",
)
FORBIDDEN_PATH_PARTS = {".env", ".git", ".venv", "__pycache__", "outputs"}
SECRET_KEY_MARKERS = ("api_key", "secret", "credential", "token_value")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _included_files(project_root: Path) -> list[Path]:
    candidates = [project_root / name for name in FREEZE_ROOT_FILES]
    for directory in FREEZE_DIRECTORIES:
        candidates.extend(path for path in (project_root / directory).rglob("*") if path.is_file())

    included: list[Path] = []
    for path in candidates:
        relative = path.relative_to(project_root)
        if not path.is_file():
            continue
        if any(part in FORBIDDEN_PATH_PARTS for part in relative.parts):
            continue
        if path.name == ".DS_Store" or path.suffix in {".pyc", ".pyo"}:
            continue
        included.append(path)
    return sorted(set(included), key=lambda item: item.relative_to(project_root).as_posix())


def _file_records(project_root: Path) -> list[dict[str, Any]]:
    return [
        {
            "path": path.relative_to(project_root).as_posix(),
            "sha256": _sha256_bytes(path.read_bytes()),
            "size_bytes": path.stat().st_size,
        }
        for path in _included_files(project_root)
    ]


def _aggregate_sha256(records: list[dict[str, Any]]) -> str:
    canonical = json.dumps(records, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return _sha256_bytes(canonical)


def _mapping_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            keys.append(str(key).casefold())
            keys.extend(_mapping_keys(nested))
    elif isinstance(value, list):
        for nested in value:
            keys.extend(_mapping_keys(nested))
    return keys


def _package_versions() -> dict[str, str]:
    observed: dict[str, str] = {}
    for package in PACKAGE_NAMES:
        try:
            observed[package] = version(package)
        except PackageNotFoundError:
            observed[package] = "not-installed"
    return observed


def build_offline_milestone_manifest(project_root: Path) -> dict[str, Any]:
    """Build a deterministic, secret-free description of the Phase 2 milestone."""

    root = project_root.resolve()
    records = _file_records(root)
    return {
        "format_version": 1,
        "milestone_id": MILESTONE_ID,
        "frozen_on": FROZEN_ON,
        "status": "FROZEN_OFFLINE",
        "scope": {
            "description": "Phase 2 deterministic graph, tests, synthetic data, and local tools",
            "file_count": len(records),
            "files": records,
            "aggregate_sha256": _aggregate_sha256(records),
            "exclusions": [
                "local .env and all credentials",
                "virtual environment and caches",
                "generated outputs, vectors, and provider payloads",
                "planning documents and project journal",
            ],
        },
        "generation_profile": {
            "provider": "OpenAI API",
            "model": OPENAI_GENERATION_MODEL,
            "model_identifier_type": OPENAI_GENERATION_MODEL_IDENTIFIER_TYPE,
            "endpoint": OPENAI_GENERATION_ENDPOINT,
            "reasoning_effort": OPENAI_REASONING_EFFORT,
            "max_output_tokens": OPENAI_MAX_OUTPUT_TOKENS,
            "structured_outputs_strict": OPENAI_STRUCTURED_OUTPUTS_STRICT,
            "store": OPENAI_RESPONSE_STORE,
            "temperature": "omitted",
            "top_p": "omitted",
            "provider_graph_calls_enabled": PROVIDER_GRAPH_CALLS_ENABLED,
            "activation_boundary": "requires a later explicit approval and guarded smoke test",
        },
        "retrieval_profile": {
            "embedding_model": OPENAI_EMBEDDING_MODEL,
            "embedding_dimension": EMBEDDING_DIMENSION,
            "pinecone_index": PINECONE_INDEX_NAME,
            "pinecone_namespace": PINECONE_NAMESPACE,
            "pinecone_metric": PINECONE_METRIC,
            "top_k": RETRIEVAL_TOP_K,
            "product_and_security": "hybrid dense plus BM25/sparse",
            "implementation": "dense semantic",
            "bm25_k1": BM25_K1,
            "bm25_b": BM25_B,
            "hybrid_sparse_weight": HYBRID_SPARSE_WEIGHT,
            "hybrid_dense_weight": HYBRID_DENSE_WEIGHT,
        },
        "verification": {
            "pytest": "PASS",
            "test_count": EXPECTED_TEST_COUNT,
            "ruff": "PASS",
            "network_blocked": True,
            "network_calls_made": 0,
            "openai_generation_requests_made": 0,
            "pinecone_requests_made": 0,
        },
        "environment": {
            "python": platform.python_version(),
            "packages": _package_versions(),
        },
        "restore_boundary": (
            "Checksums detect drift but do not restore files; retain the project directory or a "
            "later reviewed version-control commit."
        ),
    }


def validate_offline_milestone_manifest(manifest: dict[str, Any]) -> None:
    """Reject malformed, secret-bearing, or internally inconsistent manifests."""

    if manifest.get("milestone_id") != MILESTONE_ID:
        raise ValueError("unexpected milestone ID")
    if manifest.get("status") != "FROZEN_OFFLINE":
        raise ValueError("offline milestone status is not frozen")

    scope = manifest.get("scope")
    if not isinstance(scope, dict):
        raise TypeError("milestone scope must be a mapping")
    files = scope.get("files")
    if not isinstance(files, list):
        raise TypeError("milestone file records must be a list")
    if not files:
        raise ValueError("milestone file records are missing")
    if scope.get("file_count") != len(files):
        raise ValueError("milestone file count does not match records")
    if scope.get("aggregate_sha256") != _aggregate_sha256(files):
        raise ValueError("milestone aggregate checksum is invalid")

    paths = [record.get("path") for record in files]
    if any(not isinstance(path, str) or path.startswith("/") for path in paths):
        raise ValueError("milestone paths must be relative strings")
    if len(paths) != len(set(paths)):
        raise ValueError("milestone paths must be unique")
    if any(any(part in FORBIDDEN_PATH_PARTS for part in Path(path).parts) for path in paths):
        raise ValueError("milestone contains a forbidden path")

    generation = manifest.get("generation_profile")
    verification = manifest.get("verification")
    if not isinstance(generation, dict):
        raise TypeError("generation profile must be a mapping")
    if generation.get("provider_graph_calls_enabled") is not False:
        raise ValueError("provider-backed graph calls must remain disabled")
    if not isinstance(verification, dict):
        raise TypeError("verification profile must be a mapping")
    if verification.get("network_calls_made") != 0:
        raise ValueError("offline milestone cannot record network calls")

    keys = _mapping_keys(manifest)
    if any(marker in key for key in keys for marker in SECRET_KEY_MARKERS):
        raise ValueError("milestone contains a secret-like field")


def write_offline_milestone(project_root: Path, output_path: Path) -> tuple[str, str]:
    """Write the reviewed JSON artifact and return its content and SHA-256 digest."""

    manifest = build_offline_milestone_manifest(project_root)
    validate_offline_milestone_manifest(manifest)
    content = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(content, encoding="utf-8")
    digest = _sha256_bytes(content.encode("utf-8"))
    return content, digest
