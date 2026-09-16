from io import StringIO
from types import SimpleNamespace

import pytest

from rfp_orchestrator.config import Settings
from rfp_orchestrator.pinecone_smoke import (
    PineconeCheckConfigurationError,
    PineconeIndexMismatchError,
    main,
    run_index_description_check,
)


class FakePinecone:
    def __init__(self, description: dict[str, object]) -> None:
        self.description = description
        self.describe_calls: list[str] = []

    def describe_index(self, *, name: str) -> dict[str, object]:
        self.describe_calls.append(name)
        return self.description


def valid_description(**overrides: object) -> dict[str, object]:
    description: dict[str, object] = {
        "name": "rfp-agentic-ai-v1",
        "vector_type": "dense",
        "dimension": 1_536,
        "metric": "dotproduct",
        "spec": {"serverless": {"cloud": "aws", "region": "us-east-1"}},
        "status": {"ready": True, "state": "Ready"},
        "deletion_protection": "disabled",
    }
    description.update(overrides)
    return description


def configured_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "openai_api_key": None,
        "pinecone_api_key": "pcsk-test-secret-never-display",
        "pinecone_index": "rfp-agentic-ai-v1",
        "pinecone_namespace": "northstar-v1",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.mark.parametrize(
    ("overrides", "expected_message"),
    [
        ({"pinecone_api_key": None}, "PINECONE_API_KEY is blank"),
        ({"pinecone_index": None}, "PINECONE_INDEX is blank"),
        ({"pinecone_namespace": None}, "PINECONE_NAMESPACE is blank"),
        ({"pinecone_index": "wrong-index"}, "must be 'rfp-agentic-ai-v1'"),
        ({"pinecone_namespace": "wrong-namespace"}, "must be 'northstar-v1'"),
    ],
)
def test_invalid_local_configuration_fails_before_client_creation(
    overrides: dict[str, object],
    expected_message: str,
) -> None:
    factory_calls = 0

    def client_factory(unused_api_key: str) -> FakePinecone:
        nonlocal factory_calls
        factory_calls += 1
        return FakePinecone(valid_description())

    with pytest.raises(PineconeCheckConfigurationError, match=expected_message):
        run_index_description_check(
            settings=configured_settings(**overrides),
            client_factory=client_factory,
        )
    assert factory_calls == 0


def test_check_makes_one_read_only_describe_call_and_returns_safe_metadata() -> None:
    client = FakePinecone(valid_description())
    observed_key = ""

    def client_factory(api_key: str) -> FakePinecone:
        nonlocal observed_key
        observed_key = api_key
        return client

    result = run_index_description_check(
        settings=configured_settings(),
        client_factory=client_factory,
    )

    assert observed_key == "pcsk-test-secret-never-display"
    assert client.describe_calls == ["rfp-agentic-ai-v1"]
    assert result.status == "ok"
    assert result.dimension == 1_536
    assert result.metric == "dotproduct"
    assert result.namespace == "northstar-v1"
    assert "secret" not in str(result.public_fields()).lower()
    assert "host" not in result.public_fields()


def test_sdk_style_objects_are_supported() -> None:
    description = SimpleNamespace(
        name="rfp-agentic-ai-v1",
        vector_type="dense",
        dimension=1_536,
        metric="dotproduct",
        spec=SimpleNamespace(
            serverless=SimpleNamespace(cloud="aws", region="us-east-1")
        ),
        status=SimpleNamespace(ready=True, state="Ready"),
        deletion_protection="disabled",
    )
    client = SimpleNamespace(describe_index=lambda *, name: description)

    result = run_index_description_check(
        settings=configured_settings(),
        client_factory=lambda api_key: client,
    )

    assert result.cloud == "aws"
    assert result.region == "us-east-1"
    assert result.ready is True


@pytest.mark.parametrize(
    ("overrides", "expected_field"),
    [
        ({"dimension": 3_072}, "dimension"),
        ({"metric": "cosine"}, "metric"),
        ({"vector_type": "sparse"}, "vector_type"),
        ({"spec": {"serverless": {"cloud": "gcp", "region": "us-central1"}}}, "cloud"),
        ({"status": {"ready": False, "state": "Initializing"}}, "ready"),
    ],
)
def test_index_mismatches_fail_clearly(
    overrides: dict[str, object],
    expected_field: str,
) -> None:
    client = FakePinecone(valid_description(**overrides))

    with pytest.raises(PineconeIndexMismatchError, match=expected_field):
        run_index_description_check(
            settings=configured_settings(),
            client_factory=lambda api_key: client,
        )


def test_cli_configuration_error_does_not_print_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    monkeypatch.delenv("PINECONE_INDEX", raising=False)
    monkeypatch.delenv("PINECONE_NAMESPACE", raising=False)
    output = StringIO()
    error = StringIO()

    exit_code = main(
        settings=Settings(_env_file=None),
        output_stream=output,
        error_stream=error,
    )

    assert exit_code == 2
    assert output.getvalue() == ""
    assert "PINECONE_API_KEY is blank" in error.getvalue()
    assert "pcsk-" not in error.getvalue()
