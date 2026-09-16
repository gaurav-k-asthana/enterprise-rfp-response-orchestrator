from io import StringIO
from types import SimpleNamespace

import pytest

from rfp_orchestrator.config import Settings
from rfp_orchestrator.openai_smoke import (
    EmbeddingSmokeConfigurationError,
    EmbeddingSmokeResponseError,
    main,
    run_embedding_smoke,
)


class FakeEmbeddings:
    def __init__(self, response: SimpleNamespace) -> None:
        self._response = response
        self.requests: list[dict[str, object]] = []

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.requests.append(kwargs)
        return self._response


class FakeClient:
    def __init__(self, response: SimpleNamespace) -> None:
        self.embeddings = FakeEmbeddings(response)


def fake_response(*, dimensions: int = 1_536) -> SimpleNamespace:
    return SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.0] * dimensions)],
        model="text-embedding-3-small",
        usage=SimpleNamespace(prompt_tokens=8, total_tokens=8),
    )


def configured_settings() -> Settings:
    return Settings(
        _env_file=None,
        openai_api_key="sk-test-secret-never-display",
        openai_embedding_model="text-embedding-3-small",
    )


@pytest.mark.parametrize(
    ("api_key", "model", "expected_message"),
    [
        (None, "text-embedding-3-small", "OPENAI_API_KEY is blank"),
        ("sk-test", None, "OPENAI_EMBEDDING_MODEL is blank"),
    ],
)
def test_missing_configuration_fails_before_client_creation(
    api_key: str | None,
    model: str | None,
    expected_message: str,
) -> None:
    factory_calls = 0

    def client_factory(unused_api_key: str) -> FakeClient:
        nonlocal factory_calls
        factory_calls += 1
        return FakeClient(fake_response())

    settings = Settings(
        _env_file=None,
        openai_api_key=api_key,
        openai_embedding_model=model,
    )

    with pytest.raises(EmbeddingSmokeConfigurationError, match=expected_message):
        run_embedding_smoke(settings=settings, client_factory=client_factory)
    assert factory_calls == 0


def test_smoke_check_makes_one_small_request_and_returns_only_metadata() -> None:
    client = FakeClient(fake_response())
    observed_key = ""
    clock_values = iter([10.0, 10.125])

    def client_factory(api_key: str) -> FakeClient:
        nonlocal observed_key
        observed_key = api_key
        return client

    result = run_embedding_smoke(
        settings=configured_settings(),
        client_factory=client_factory,
        clock=lambda: next(clock_values),
    )

    assert observed_key == "sk-test-secret-never-display"
    assert client.embeddings.requests == [
        {
            "model": "text-embedding-3-small",
            "input": "Enterprise RFP retrieval connectivity check.",
            "encoding_format": "float",
        }
    ]
    assert result.status == "ok"
    assert result.dimensions == 1_536
    assert result.prompt_tokens == 8
    assert result.total_tokens == 8
    assert result.elapsed_ms == 125.0
    assert "secret" not in str(result.public_fields()).lower()


def test_empty_provider_vector_fails_clearly() -> None:
    client = FakeClient(fake_response(dimensions=0))

    with pytest.raises(EmbeddingSmokeResponseError, match="no usable embedding"):
        run_embedding_smoke(
            settings=configured_settings(),
            client_factory=lambda api_key: client,
        )


def test_cli_configuration_error_does_not_print_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_EMBEDDING_MODEL", raising=False)
    output = StringIO()
    error = StringIO()

    exit_code = main(
        settings=Settings(_env_file=None),
        output_stream=output,
        error_stream=error,
    )

    assert exit_code == 2
    assert output.getvalue() == ""
    assert "OPENAI_API_KEY is blank" in error.getvalue()
    assert "sk-" not in error.getvalue()
