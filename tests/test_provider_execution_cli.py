from __future__ import annotations

from io import StringIO
from pathlib import Path

import pytest

from rfp_orchestrator.config import Settings
from rfp_orchestrator.provider_budget import ProviderBudgetSnapshot
from rfp_orchestrator.provider_execution import (
    ArchivedProviderRun,
    ProviderExecutionReceipt,
)
from rfp_orchestrator.provider_execution_cli import main
from rfp_orchestrator.provider_execution_manifest import (
    EXECUTION_APPROVAL_TOKEN,
    build_provider_execution_manifest,
    serialize_provider_execution_manifest,
    write_provider_execution_manifest,
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
    path = tmp_path / "manifest.json"
    _, digest = write_provider_execution_manifest(
        build_provider_execution_manifest(),
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
            ["--execute", "--approval-token", EXECUTION_APPROVAL_TOKEN],
            "expected manifest SHA-256 is invalid",
        ),
    ],
)
def test_cli_refuses_missing_guards_before_execution(
    tmp_path: Path,
    extra_args: list[str],
    message: str,
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


def test_cli_refuses_manifest_digest_drift_before_execution(tmp_path: Path) -> None:
    path, _ = write_manifest(tmp_path)
    calls: list[dict] = []
    error = StringIO()

    result = main(
        [
            "--execute",
            "--manifest",
            str(path),
            "--expected-manifest-sha256",
            "0" * 64,
            "--approval-token",
            EXECUTION_APPROVAL_TOKEN,
        ],
        settings=valid_settings(),
        execution_function=lambda **kwargs: calls.append(kwargs),  # type: ignore[arg-type,return-value]
        error_stream=error,
    )

    assert result == 2
    assert "manifest SHA-256 does not match" in error.getvalue()
    assert calls == []


@pytest.mark.parametrize(
    "settings_update",
    [
        {"provider_graph_calls_enabled": False},
        {"openai_model": "different-model"},
        {"pinecone_namespace": "different-namespace"},
        {"openai_api_key": ""},
    ],
)
def test_cli_refuses_runtime_drift_before_execution(
    tmp_path: Path,
    settings_update: dict[str, object],
) -> None:
    path, digest = write_manifest(tmp_path)
    payload = valid_settings().model_dump()
    payload.update(settings_update)
    settings = Settings(_env_file=None, **payload)
    calls: list[dict] = []

    result = main(
        [
            "--execute",
            "--manifest",
            str(path),
            "--expected-manifest-sha256",
            digest,
            "--approval-token",
            EXECUTION_APPROVAL_TOKEN,
        ],
        settings=settings,
        execution_function=lambda **kwargs: calls.append(kwargs),  # type: ignore[arg-type,return-value]
        error_stream=StringIO(),
    )

    assert result == 2
    assert calls == []


def fake_receipt(manifest_sha256: str) -> ProviderExecutionReceipt:
    runs = [
        ArchivedProviderRun(
            run_id=f"fake-run-{number}",
            trial_number=number,
            case_count=24 if number == 1 else 4,
            architecture_execution_count=48 if number == 1 else 8,
            provider_calls_made=0,
            status="COMPLETE",
            archive_path=f"evaluation/raw_runs/fake-run-{number}",
            archive_manifest_sha256=str(number) * 64,
        )
        for number in (1, 2, 3)
    ]
    return ProviderExecutionReceipt(
        manifest_sha256=manifest_sha256,
        runs=runs,
        generation_budget=ProviderBudgetSnapshot(
            attempted_calls=0,
            completed_calls=0,
            failed_calls=0,
            blocked_calls=0,
            total_input_tokens=0,
            total_output_tokens=0,
            total_tokens=0,
            calls_by_execution={},
            halted=False,
        ),
        total_architecture_executions=64,
    )


def test_exact_validated_command_reaches_only_the_injected_executor(
    tmp_path: Path,
) -> None:
    path, digest = write_manifest(tmp_path)
    calls: list[dict] = []
    output = StringIO()

    def execute(**kwargs):
        calls.append(kwargs)
        return fake_receipt(kwargs["manifest_sha256"])

    result = main(
        [
            "--execute",
            "--manifest",
            str(path),
            "--expected-manifest-sha256",
            digest,
            "--approval-token",
            EXECUTION_APPROVAL_TOKEN,
        ],
        settings=valid_settings(),
        execution_function=execute,
        output_stream=output,
    )

    assert result == 0
    assert len(calls) == 1
    assert calls[0]["manifest_sha256"] == digest
    assert len(calls[0]["run_specifications"]) == 3
    assert '"total_architecture_executions": 64' in output.getvalue()


def test_cli_module_does_not_contain_or_print_credentials(tmp_path: Path) -> None:
    _, digest = write_manifest(tmp_path)
    content, _ = serialize_provider_execution_manifest(
        build_provider_execution_manifest()
    )

    assert "test-openai-key" not in content
    assert "test-pinecone-key" not in content
    assert digest not in valid_settings().model_dump_json()
