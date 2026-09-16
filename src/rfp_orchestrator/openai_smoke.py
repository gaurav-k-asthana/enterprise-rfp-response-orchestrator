"""Guarded one-request OpenAI embedding connectivity check."""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Any, Protocol, TextIO

from rfp_orchestrator.config import Settings

SMOKE_TEST_INPUT = "Enterprise RFP retrieval connectivity check."


class EmbeddingSmokeConfigurationError(RuntimeError):
    """Raised before client creation when local OpenAI settings are incomplete."""


class EmbeddingSmokeResponseError(RuntimeError):
    """Raised when the provider returns no usable embedding vector."""


class EmbeddingsResource(Protocol):
    def create(self, **kwargs: Any) -> Any: ...


class EmbeddingsClient(Protocol):
    embeddings: EmbeddingsResource


ClientFactory = Callable[[str], EmbeddingsClient]
Clock = Callable[[], float]


@dataclass(frozen=True)
class EmbeddingSmokeResult:
    status: str
    requested_model: str
    response_model: str
    dimensions: int
    prompt_tokens: int | None
    total_tokens: int | None
    elapsed_ms: float

    def public_fields(self) -> dict[str, str | int | float | None]:
        """Return only non-secret fields that are safe to display or journal."""

        return asdict(self)


def _default_client_factory(api_key: str) -> EmbeddingsClient:
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _usage_value(response: Any, name: str) -> int | None:
    usage = getattr(response, "usage", None)
    value = getattr(usage, name, None)
    return int(value) if value is not None else None


def run_embedding_smoke(
    *,
    settings: Settings | None = None,
    client_factory: ClientFactory = _default_client_factory,
    clock: Clock = perf_counter,
) -> EmbeddingSmokeResult:
    """Make exactly one small embedding request after local validation."""

    active_settings = settings or Settings()
    if not active_settings.openai_api_key:
        raise EmbeddingSmokeConfigurationError(
            "OPENAI_API_KEY is blank; add it only to the ignored local .env file"
        )
    if not active_settings.openai_embedding_model:
        raise EmbeddingSmokeConfigurationError(
            "OPENAI_EMBEDDING_MODEL is blank; set it to the reviewed embedding model"
        )

    client = client_factory(active_settings.openai_api_key)
    started_at = clock()
    response = client.embeddings.create(
        model=active_settings.openai_embedding_model,
        input=SMOKE_TEST_INPUT,
        encoding_format="float",
    )
    elapsed_ms = (clock() - started_at) * 1_000

    response_data = getattr(response, "data", None)
    vector = getattr(response_data[0], "embedding", None) if response_data else None
    if not vector:
        raise EmbeddingSmokeResponseError("OpenAI returned no usable embedding vector")

    return EmbeddingSmokeResult(
        status="ok",
        requested_model=active_settings.openai_embedding_model,
        response_model=str(getattr(response, "model", "unknown")),
        dimensions=len(vector),
        prompt_tokens=_usage_value(response, "prompt_tokens"),
        total_tokens=_usage_value(response, "total_tokens"),
        elapsed_ms=round(elapsed_ms, 2),
    )


def main(
    *,
    settings: Settings | None = None,
    output_stream: TextIO = sys.stdout,
    error_stream: TextIO = sys.stderr,
) -> int:
    """Run the guarded check without ever printing credentials or vector values."""

    try:
        result = run_embedding_smoke(settings=settings)
    except EmbeddingSmokeConfigurationError as error:
        print(str(error), file=error_stream)
        return 2
    except Exception as error:  # noqa: BLE001 - CLI boundary redacts provider errors.
        safe_error = {
            "status": "failed",
            "error_type": type(error).__name__,
            "http_status": getattr(error, "status_code", None),
            "request_id": getattr(error, "request_id", None),
        }
        print(json.dumps(safe_error, sort_keys=True), file=error_stream)
        return 1

    print(json.dumps(result.public_fields(), sort_keys=True), file=output_stream)
    return 0
