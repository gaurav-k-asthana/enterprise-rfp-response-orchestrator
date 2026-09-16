"""Read-only Pinecone index-description check for the locked V1 design."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from typing import Any, Protocol, TextIO

from rfp_orchestrator import provider_config
from rfp_orchestrator.config import Settings

EXPECTED_INDEX_NAME = provider_config.PINECONE_INDEX_NAME
EXPECTED_NAMESPACE = provider_config.PINECONE_NAMESPACE
EXPECTED_VECTOR_TYPE = provider_config.PINECONE_VECTOR_TYPE
EXPECTED_DIMENSION = provider_config.EMBEDDING_DIMENSION
EXPECTED_METRIC = provider_config.PINECONE_METRIC
EXPECTED_CLOUD = provider_config.PINECONE_CLOUD
EXPECTED_REGION = provider_config.PINECONE_REGION


class PineconeCheckConfigurationError(RuntimeError):
    """Raised before client creation when local Pinecone settings are incomplete."""


class PineconeIndexMismatchError(RuntimeError):
    """Raised when the described index does not match the locked V1 design."""


class PineconeControlClient(Protocol):
    def describe_index(self, *, name: str) -> Any: ...


ClientFactory = Callable[[str], PineconeControlClient]


@dataclass(frozen=True)
class PineconeIndexCheckResult:
    status: str
    index_name: str
    namespace: str
    vector_type: str
    dimension: int
    metric: str
    cloud: str
    region: str
    ready: bool
    state: str
    deletion_protection: str

    def public_fields(self) -> dict[str, str | int | bool]:
        """Return only non-secret configuration and readiness fields."""

        return asdict(self)


def _default_client_factory(api_key: str) -> PineconeControlClient:
    from pinecone import Pinecone

    return Pinecone(api_key=api_key)


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _string_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _serverless_field(description: Any, name: str) -> Any:
    spec = _field(description, "spec")
    serverless = _field(spec, "serverless")
    return _field(serverless, name)


def _validate_local_settings(settings: Settings) -> None:
    if not settings.pinecone_api_key:
        raise PineconeCheckConfigurationError(
            "PINECONE_API_KEY is blank; add it only to the ignored local .env file"
        )
    if not settings.pinecone_index:
        raise PineconeCheckConfigurationError(
            "PINECONE_INDEX is blank; set it to the reviewed index name"
        )
    if not settings.pinecone_namespace:
        raise PineconeCheckConfigurationError(
            "PINECONE_NAMESPACE is blank; set it to the reviewed namespace"
        )
    if settings.pinecone_index != EXPECTED_INDEX_NAME:
        raise PineconeCheckConfigurationError(
            f"PINECONE_INDEX must be '{EXPECTED_INDEX_NAME}' for the locked V1 design"
        )
    if settings.pinecone_namespace != EXPECTED_NAMESPACE:
        raise PineconeCheckConfigurationError(
            f"PINECONE_NAMESPACE must be '{EXPECTED_NAMESPACE}' for the locked V1 design"
        )


def _as_result(description: Any, *, namespace: str) -> PineconeIndexCheckResult:
    status = _field(description, "status")
    return PineconeIndexCheckResult(
        status="ok",
        index_name=_string_value(_field(description, "name")),
        namespace=namespace,
        vector_type=_string_value(_field(description, "vector_type")),
        dimension=int(_field(description, "dimension")),
        metric=_string_value(_field(description, "metric")),
        cloud=_string_value(_serverless_field(description, "cloud")),
        region=_string_value(_serverless_field(description, "region")),
        ready=bool(_field(status, "ready", False)),
        state=_string_value(_field(status, "state", "unknown")),
        deletion_protection=_string_value(
            _field(description, "deletion_protection", "unknown")
        ),
    )


def _configuration_mismatches(result: PineconeIndexCheckResult) -> list[str]:
    expected = {
        "index_name": EXPECTED_INDEX_NAME,
        "vector_type": EXPECTED_VECTOR_TYPE,
        "dimension": EXPECTED_DIMENSION,
        "metric": EXPECTED_METRIC,
        "cloud": EXPECTED_CLOUD,
        "region": EXPECTED_REGION,
    }
    observed = result.public_fields()
    mismatches = [
        f"{field}: expected {wanted!r}, received {observed[field]!r}"
        for field, wanted in expected.items()
        if observed[field] != wanted
    ]
    if not result.ready:
        mismatches.append(f"ready: expected True, received state {result.state!r}")
    return mismatches


def run_index_description_check(
    *,
    settings: Settings | None = None,
    client_factory: ClientFactory = _default_client_factory,
) -> PineconeIndexCheckResult:
    """Make exactly one control-plane read and verify the locked index settings."""

    active_settings = settings or Settings()
    _validate_local_settings(active_settings)

    client = client_factory(active_settings.pinecone_api_key or "")
    description = client.describe_index(name=active_settings.pinecone_index or "")
    result = _as_result(
        description,
        namespace=active_settings.pinecone_namespace or "",
    )
    mismatches = _configuration_mismatches(result)
    if mismatches:
        raise PineconeIndexMismatchError(
            "Pinecone index does not match the locked V1 design: " + "; ".join(mismatches)
        )
    return result


def main(
    *,
    settings: Settings | None = None,
    output_stream: TextIO = sys.stdout,
    error_stream: TextIO = sys.stderr,
) -> int:
    """Run the read-only check without printing credentials or index host details."""

    try:
        result = run_index_description_check(settings=settings)
    except (PineconeCheckConfigurationError, PineconeIndexMismatchError) as error:
        print(str(error), file=error_stream)
        return 2
    except Exception as error:  # noqa: BLE001 - CLI boundary redacts provider errors.
        safe_error = {
            "status": "failed",
            "error_type": type(error).__name__,
            "http_status": getattr(error, "status_code", None),
        }
        print(json.dumps(safe_error, sort_keys=True), file=error_stream)
        return 1

    print(json.dumps(result.public_fields(), sort_keys=True), file=output_stream)
    return 0
