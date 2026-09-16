"""Disabled-by-default OpenAI Responses API boundary for provider evaluation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from rfp_orchestrator.provider_config import (
    OPENAI_GENERATION_MODEL,
    OPENAI_MAX_OUTPUT_TOKENS,
    OPENAI_REASONING_EFFORT,
    OPENAI_RESPONSE_STORE,
)

OutputT = TypeVar("OutputT", bound=BaseModel)


class OpenAIGenerationError(RuntimeError):
    """Base error for the guarded generation boundary."""


class OpenAIGenerationDisabledError(OpenAIGenerationError):
    """Raised before client creation when provider generation is disabled."""


class OpenAIGenerationConfigurationError(OpenAIGenerationError):
    """Raised before client creation when required local configuration is absent."""


class OpenAIGenerationCallError(OpenAIGenerationError):
    """Raised when the provider request fails without exposing provider details."""


class OpenAIGenerationResponseError(OpenAIGenerationError):
    """Raised when a provider response violates the frozen contract."""


class StructuredGenerationRequest(BaseModel):
    """Non-secret inputs for one strict structured-output request."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    schema_name: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    instructions: str = Field(min_length=1)
    input_text: str = Field(min_length=1)

    @model_validator(mode="after")
    def text_fields_are_not_whitespace(self) -> StructuredGenerationRequest:
        if not self.instructions.strip() or not self.input_text.strip():
            raise ValueError("generation instructions and input cannot be blank")
        return self


class ProviderTokenUsage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    total_tokens: int = Field(ge=0)

    @model_validator(mode="after")
    def total_is_exact(self) -> ProviderTokenUsage:
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("provider token total must equal input plus output tokens")
        return self


class StructuredGenerationResult(BaseModel, Generic[OutputT]):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1)
    response_id: str = Field(min_length=1)
    requested_model: str = Field(min_length=1)
    response_model: str = Field(min_length=1)
    provider_calls: int = Field(default=1, ge=1, le=1)
    usage: ProviderTokenUsage
    output: OutputT


class ResponsesResource(Protocol):
    def create(self, **kwargs: object) -> object: ...


class OpenAIClient(Protocol):
    responses: ResponsesResource


OpenAIClientFactory = Callable[[str], OpenAIClient]


def _default_client_factory(api_key: str) -> OpenAIClient:
    from openai import OpenAI

    return OpenAI(api_key=api_key)


def _field(value: object, name: str) -> object:
    if isinstance(value, dict):
        return value.get(name)
    return getattr(value, name, None)


def _required_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise OpenAIGenerationResponseError(
            f"OpenAI response is missing a usable {field_name}"
        )
    return value


def _required_token_count(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OpenAIGenerationResponseError(
            f"OpenAI response has invalid {field_name} usage"
        )
    return value


class OpenAIStructuredGenerationGateway:
    """One-call strict-output adapter; construction never initializes a provider client."""

    def __init__(
        self,
        *,
        api_key: str | None,
        enabled: bool = False,
        client_factory: OpenAIClientFactory = _default_client_factory,
    ) -> None:
        self._api_key = api_key
        self._enabled = enabled
        self._client_factory = client_factory

    def generate(
        self,
        request: StructuredGenerationRequest,
        *,
        output_model: type[OutputT],
    ) -> StructuredGenerationResult[OutputT]:
        if not self._enabled:
            raise OpenAIGenerationDisabledError(
                "OpenAI generation is disabled until the exact paid command is approved"
            )
        if not self._api_key or not self._api_key.strip():
            raise OpenAIGenerationConfigurationError(
                "OPENAI_API_KEY is required for an approved provider generation"
            )

        try:
            client = self._client_factory(self._api_key)
            response = client.responses.create(
                model=OPENAI_GENERATION_MODEL,
                instructions=request.instructions,
                input=request.input_text,
                reasoning={"effort": OPENAI_REASONING_EFFORT},
                max_output_tokens=OPENAI_MAX_OUTPUT_TOKENS,
                store=OPENAI_RESPONSE_STORE,
                text={
                    "format": {
                        "type": "json_schema",
                        "name": request.schema_name,
                        "schema": output_model.model_json_schema(),
                        "strict": True,
                    }
                },
                metadata={"request_id": request.request_id},
            )
        except OpenAIGenerationError:
            raise
        except Exception:  # noqa: BLE001 - external-provider boundary redacts all details.
            raise OpenAIGenerationCallError(
                "OpenAI Responses API request failed; provider details were redacted"
            ) from None

        status = _field(response, "status")
        if status != "completed":
            raise OpenAIGenerationResponseError(
                "OpenAI response did not complete successfully"
            )
        response_id = _required_text(_field(response, "id"), "response ID")
        response_model = _required_text(_field(response, "model"), "model ID")
        output_text = _required_text(_field(response, "output_text"), "structured output")

        usage_value = _field(response, "usage")
        if usage_value is None:
            raise OpenAIGenerationResponseError("OpenAI response is missing token usage")
        usage = ProviderTokenUsage(
            input_tokens=_required_token_count(
                _field(usage_value, "input_tokens"), "input token"
            ),
            output_tokens=_required_token_count(
                _field(usage_value, "output_tokens"), "output token"
            ),
            total_tokens=_required_token_count(
                _field(usage_value, "total_tokens"), "total token"
            ),
        )

        try:
            parsed = output_model.model_validate_json(output_text)
        except ValidationError:
            raise OpenAIGenerationResponseError(
                "OpenAI structured output failed local schema validation"
            ) from None

        return StructuredGenerationResult[output_model](
            request_id=request.request_id,
            response_id=response_id,
            requested_model=OPENAI_GENERATION_MODEL,
            response_model=response_model,
            usage=usage,
            output=parsed,
        )
