from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from rfp_orchestrator.config import Settings
from rfp_orchestrator.provider_recovery_cli import main
from rfp_orchestrator.provider_recovery_manifest import (
    RECOVERY_APPROVAL_TOKEN,
    build_provider_recovery_manifest,
    write_provider_recovery_manifest,
)


def valid_settings() -> Settings:
    return Settings(
        _env_file=None,
        openai_api_key="test-openai-key",
        openai_model="gpt-5.6-terra",
        provider_graph_calls_enabled=True,
        openai_embedding_model="text-embedding-3-small",
        pinecone_api_key="test-pinecone-key",
        pinecone_index="rfp-agentic-ai-v1",
        pinecone_namespace="northstar-v1",
        max_retrieval_retries=2,
        retrieval_top_k=5,
    )


def write_manifest(tmp_path: Path) -> tuple[Path, str]:
    path = tmp_path / "recovery.json"
    _, digest = write_provider_recovery_manifest(
        build_provider_recovery_manifest(),
        output_path=path,
        review_path=tmp_path / "review.md",
    )
    return path, digest


@pytest.mark.parametrize(
    ("extra_args", "message"),
    [
        ([], "requires --execute"),
        (["--execute"], "approval token does not match"),
        (
            ["--execute", "--approval-token", RECOVERY_APPROVAL_TOKEN],
            "manifest SHA-256 is invalid",
        ),
    ],
)
def test_recovery_cli_refuses_missing_guards(
    tmp_path: Path, extra_args: list[str], message: str
) -> None:
    path, _ = write_manifest(tmp_path)
    calls: list[dict] = []
    error = StringIO()

    result = main(
        ["--manifest", str(path), *extra_args],
        settings=valid_settings(),
        execution_function=lambda **kwargs: calls.append(kwargs),  # type: ignore[arg-type,return-value]
        error_stream=error,
    )

    assert result == 2
    assert message in error.getvalue()
    assert calls == []


def test_exact_recovery_request_passes_seed_to_injected_execution(tmp_path: Path) -> None:
    path, digest = write_manifest(tmp_path)
    calls: list[dict] = []

    def capture(**kwargs):
        calls.append(kwargs)
        raise RuntimeError("stop after offline capture")

    result = main(
        [
            "--execute",
            "--manifest",
            str(path),
            "--expected-manifest-sha256",
            digest,
            "--approval-token",
            RECOVERY_APPROVAL_TOKEN,
        ],
        settings=valid_settings(),
        execution_function=capture,
        error_stream=StringIO(),
    )

    assert result == 1
    assert len(calls) == 1
    assert calls[0]["initial_budget_usage"].attempted_calls == 36
    assert calls[0]["initial_budget_usage"].input_tokens == 57_403
    assert [item.run_id for item in calls[0]["run_specifications"]] == [
        "northstar-provider-primary-recovery-v2",
        "northstar-provider-repeat-trial-2-recovery-v2",
        "northstar-provider-repeat-trial-3-recovery-v2",
    ]
