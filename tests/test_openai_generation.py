from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from rfp_orchestrator.openai_generation import (
    OpenAIGenerationCallError,
    OpenAIGenerationConfigurationError,
    OpenAIGenerationDisabledError,
    OpenAIGenerationResponseError,
    OpenAIStructuredGenerationGateway,
    StructuredGenerationRequest,
)
from rfp_orchestrator.provider_config import (
    OPENAI_GENERATION_MODEL,
    OPENAI_MAX_OUTPUT_TOKENS,
    OPENAI_REASONING_EFFORT,
)


class ExampleOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    answer: str = Field(min_length=1)
    supported: bool


def request() -> StructuredGenerationRequest:
    return StructuredGenerationRequest(
        request_id="EVAL-001-generalist-trial-1",
        schema_name="rfp_evaluation_output",
        instructions="Use only the supplied synthetic evidence.",
        input_text="Requirement and evidence go here.",
    )


def response(**overrides: object) -> SimpleNamespace:
    values = {
        "id": "resp_test_001",
        "status": "completed",
        "model": "gpt-5.6-terra-2026-08-01",
        "output_text": '{"answer":"Supported response","supported":true}',
        "usage": SimpleNamespace(
            input_tokens=120,
            output_tokens=30,
            total_tokens=150,
        ),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class FakeResponses:
    def __init__(self, result: object | Exception) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class FakeClient:
    def __init__(self, result: object | Exception) -> None:
        self.responses = FakeResponses(result)


class RecordingFactory:
    def __init__(self, result: object | Exception) -> None:
        self.client = FakeClient(result)
        self.keys: list[str] = []

    def __call__(self, api_key: str) -> FakeClient:
        self.keys.append(api_key)
        return self.client


def test_gateway_is_disabled_before_client_creation() -> None:
    factory = RecordingFactory(response())
    gateway = OpenAIStructuredGenerationGateway(
        api_key="secret-key",
        client_factory=factory,
    )

    with pytest.raises(OpenAIGenerationDisabledError, match="exact paid command"):
        gateway.generate(request(), output_model=ExampleOutput)

    assert factory.keys == []
    assert factory.client.responses.calls == []


@pytest.mark.parametrize("api_key", [None, "", "   "])
def test_gateway_requires_a_nonblank_key_before_client_creation(
    api_key: str | None,
) -> None:
    factory = RecordingFactory(response())
    gateway = OpenAIStructuredGenerationGateway(
        api_key=api_key,
        enabled=True,
        client_factory=factory,
    )

    with pytest.raises(OpenAIGenerationConfigurationError, match="OPENAI_API_KEY"):
        gateway.generate(request(), output_model=ExampleOutput)

    assert factory.keys == []


def test_gateway_uses_the_exact_frozen_responses_configuration() -> None:
    factory = RecordingFactory(response())
    gateway = OpenAIStructuredGenerationGateway(
        api_key="secret-key",
        enabled=True,
        client_factory=factory,
    )

    result = gateway.generate(request(), output_model=ExampleOutput)
    call = factory.client.responses.calls[0]

    assert factory.keys == ["secret-key"]
    assert call["model"] == OPENAI_GENERATION_MODEL
    assert call["reasoning"] == {"effort": OPENAI_REASONING_EFFORT}
    assert call["max_output_tokens"] == OPENAI_MAX_OUTPUT_TOKENS
    assert call["store"] is False
    assert call["instructions"] == request().instructions
    assert call["input"] == request().input_text
    assert call["metadata"] == {"request_id": request().request_id}
    assert "temperature" not in call
    assert "top_p" not in call
    assert "tools" not in call
    assert result.output == ExampleOutput(answer="Supported response", supported=True)


def test_gateway_sends_a_strict_pydantic_json_schema() -> None:
    factory = RecordingFactory(response())
    gateway = OpenAIStructuredGenerationGateway(
        api_key="secret-key",
        enabled=True,
        client_factory=factory,
    )

    gateway.generate(request(), output_model=ExampleOutput)
    format_config = factory.client.responses.calls[0]["text"]["format"]

    assert format_config["type"] == "json_schema"
    assert format_config["name"] == "rfp_evaluation_output"
    assert format_config["strict"] is True
    assert format_config["schema"] == ExampleOutput.model_json_schema()


def test_gateway_records_response_identity_and_exact_usage() -> None:
    factory = RecordingFactory(response())
    result = OpenAIStructuredGenerationGateway(
        api_key="secret-key",
        enabled=True,
        client_factory=factory,
    ).generate(request(), output_model=ExampleOutput)

    assert result.request_id == "EVAL-001-generalist-trial-1"
    assert result.response_id == "resp_test_001"
    assert result.requested_model == OPENAI_GENERATION_MODEL
    assert result.response_model == "gpt-5.6-terra-2026-08-01"
    assert result.provider_calls == 1
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 30
    assert result.usage.total_tokens == 150


@pytest.mark.parametrize("status", ["failed", "incomplete", "in_progress", None])
def test_gateway_rejects_any_noncompleted_status(status: object) -> None:
    gateway = OpenAIStructuredGenerationGateway(
        api_key="secret-key",
        enabled=True,
        client_factory=RecordingFactory(response(status=status)),
    )

    with pytest.raises(OpenAIGenerationResponseError, match="did not complete"):
        gateway.generate(request(), output_model=ExampleOutput)


@pytest.mark.parametrize("output_text", [None, "", "   "])
def test_gateway_rejects_missing_structured_output(output_text: object) -> None:
    gateway = OpenAIStructuredGenerationGateway(
        api_key="secret-key",
        enabled=True,
        client_factory=RecordingFactory(response(output_text=output_text)),
    )

    with pytest.raises(OpenAIGenerationResponseError, match="structured output"):
        gateway.generate(request(), output_model=ExampleOutput)


@pytest.mark.parametrize(
    "output_text",
    [
        "not-json",
        '{"answer":"Missing supported"}',
        '{"answer":"Answer","supported":true,"extra":"forbidden"}',
    ],
)
def test_gateway_rejects_output_that_fails_local_schema_validation(
    output_text: str,
) -> None:
    gateway = OpenAIStructuredGenerationGateway(
        api_key="secret-key",
        enabled=True,
        client_factory=RecordingFactory(response(output_text=output_text)),
    )

    with pytest.raises(OpenAIGenerationResponseError, match="local schema validation"):
        gateway.generate(request(), output_model=ExampleOutput)


def test_gateway_rejects_missing_or_inexact_usage() -> None:
    missing = OpenAIStructuredGenerationGateway(
        api_key="secret-key",
        enabled=True,
        client_factory=RecordingFactory(response(usage=None)),
    )
    with pytest.raises(OpenAIGenerationResponseError, match="missing token usage"):
        missing.generate(request(), output_model=ExampleOutput)

    inexact = OpenAIStructuredGenerationGateway(
        api_key="secret-key",
        enabled=True,
        client_factory=RecordingFactory(
            response(
                usage=SimpleNamespace(
                    input_tokens=120,
                    output_tokens=30,
                    total_tokens=149,
                )
            )
        ),
    )
    with pytest.raises(ValidationError, match="provider token total"):
        inexact.generate(request(), output_model=ExampleOutput)


def test_provider_failure_is_redacted_and_does_not_leak_key_or_payload() -> None:
    secret = "sk-secret-value"
    provider_message = f"request failed with {secret} and private payload"
    gateway = OpenAIStructuredGenerationGateway(
        api_key=secret,
        enabled=True,
        client_factory=RecordingFactory(RuntimeError(provider_message)),
    )

    with pytest.raises(OpenAIGenerationCallError) as captured:
        gateway.generate(request(), output_model=ExampleOutput)

    rendered = str(captured.value)
    assert "provider details were redacted" in rendered
    assert secret not in rendered
    assert "private payload" not in rendered


def test_request_rejects_blank_text_and_unsafe_identifiers() -> None:
    with pytest.raises(ValidationError):
        StructuredGenerationRequest(
            request_id="unsafe identifier with spaces",
            schema_name="output",
            instructions="instructions",
            input_text="input",
        )
    with pytest.raises(ValidationError):
        StructuredGenerationRequest(
            request_id="safe-id",
            schema_name="output",
            instructions="   ",
            input_text="input",
        )
