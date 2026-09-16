"""Content-addressed recovery manifest after the invalid Step 4.G7 attempt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.comparison_safety import DEFAULT_SHARED_SAFETY_POLICY_PATH
from rfp_orchestrator.evaluation_freeze import file_sha256, text_sha256
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    EXPECTED_CASE_IDS,
)
from rfp_orchestrator.evaluation_trials import (
    DEFAULT_PRICING_SNAPSHOT_PATH,
    DEFAULT_REPEAT_TRIAL_APPROVAL_PATH,
    DEFAULT_REPEAT_TRIAL_PLAN_PATH,
    SELECTED_REPEAT_CASE_IDS,
    load_repeat_trial_approval,
)
from rfp_orchestrator.fair_comparison import (
    DEFAULT_FAIR_COMPARISON_PATH,
    ComparisonArchitecture,
)
from rfp_orchestrator.provider_budget import ProviderBudgetUsageSeed
from rfp_orchestrator.provider_config import (
    EMBEDDING_DIMENSION,
    HYBRID_DENSE_WEIGHT,
    HYBRID_SPARSE_WEIGHT,
    OPENAI_EMBEDDING_MODEL,
    OPENAI_GENERATION_ENDPOINT,
    OPENAI_GENERATION_MODEL,
    OPENAI_MAX_OUTPUT_TOKENS,
    OPENAI_REASONING_EFFORT,
    OPENAI_RESPONSE_STORE,
    OPENAI_STRUCTURED_OUTPUTS_STRICT,
    PINECONE_INDEX_NAME,
    PINECONE_NAMESPACE,
    RETRIEVAL_TOP_K,
)
from rfp_orchestrator.provider_execution import RunSpecification
from rfp_orchestrator.provider_execution_manifest import (
    DEFAULT_FAKE_REHEARSAL_PATH,
    DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH,
    HashedArtifact,
    ProviderConfigurationManifest,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROVIDER_ATTEMPT_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "provider_execution_attempt_step_4_g7.json"
)
DEFAULT_PROVIDER_RECOVERY_MANIFEST_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "provider_recovery_manifest_step_4_g7.json"
)
DEFAULT_PROVIDER_RECOVERY_REVIEW_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "provider_recovery_review_step_4_g7.md"
)
RECOVERY_APPROVAL_TOKEN = "EXECUTE-NORTHSTAR-RFP-RECOVERY-V2"
RECOVERY_MANIFEST_ID = "northstar-rfp-provider-recovery-step-4-g7-v2"
RECOVERY_PREPARED_AT = "2026-09-15T14:00:00-04:00"
PREDECESSOR_MANIFEST_SHA256 = "48932d8e0da2ac7a764b03cc69e23faa6aa8d9579db659ffaac569c609ffc938"
ATTEMPT_RECORD_SHA256 = "ad74be609e1b4d17b694638d6ddcec11ec96c329cfd8885243b6e22bba4e8e3b"
ATTEMPT_ONE_ESTIMATED_GENERATION_COST_USD = 0.258458

RECOVERY_EXECUTION_SOURCE_PATHS = (
    "src/rfp_orchestrator/openai_generation.py",
    "src/rfp_orchestrator/provider_retrieval.py",
    "src/rfp_orchestrator/provider_generalist.py",
    "src/rfp_orchestrator/provider_specialists.py",
    "src/rfp_orchestrator/provider_orchestrated.py",
    "src/rfp_orchestrator/provider_budget.py",
    "src/rfp_orchestrator/provider_execution.py",
    "src/rfp_orchestrator/provider_recovery_manifest.py",
    "src/rfp_orchestrator/provider_recovery_cli.py",
    "src/rfp_orchestrator/evaluation_runner.py",
    "scripts/run_provider_recovery.py",
)


class ProviderRecoveryManifestError(RuntimeError):
    """Raised before provider initialization when recovery scope drifts."""


class ProviderRecoveryBudgetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    currency: Literal["USD"] = "USD"
    original_authorized_maximum_usd: Literal[5.12] = 5.12
    prior_estimated_generation_cost_usd: Literal[0.258458] = (
        ATTEMPT_ONE_ESTIMATED_GENERATION_COST_USD
    )
    remaining_estimated_generation_cost_ceiling_usd: Literal[4.861542] = 4.861542
    max_provider_calls_per_architecture_execution: Literal[3] = 3
    original_max_provider_calls_total: Literal[128] = 128
    remaining_provider_calls: Literal[92] = 92
    original_max_total_input_tokens: Literal[1024000] = 1_024_000
    remaining_input_tokens: Literal[966597] = 966_597
    original_max_total_output_tokens: Literal[256000] = 256_000
    remaining_output_tokens: Literal[244029] = 244_029
    automatic_provider_retries_allowed: Literal[False] = False
    stop_before_next_call_when_cap_would_be_exceeded: Literal[True] = True


class ProviderRecoveryManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    manifest_id: Literal["northstar-rfp-provider-recovery-step-4-g7-v2"] = RECOVERY_MANIFEST_ID
    prepared_at: Literal["2026-09-15T14:00:00-04:00"] = RECOVERY_PREPARED_AT
    status: Literal["AWAITING_EXACT_COMMAND_APPROVAL"] = "AWAITING_EXACT_COMMAND_APPROVAL"
    paid_command_approved: Literal[False] = False
    network_calls_made_during_preparation: Literal[0] = 0
    predecessor_manifest: HashedArtifact
    invalid_attempt_record: HashedArtifact
    source_artifacts: list[HashedArtifact] = Field(min_length=20)
    execution_sources: list[HashedArtifact] = Field(min_length=11, max_length=11)
    provider_configuration: ProviderConfigurationManifest
    architectures: list[ComparisonArchitecture] = Field(min_length=2, max_length=2)
    runs: list[RunSpecification] = Field(min_length=3, max_length=3)
    total_architecture_execution_count: Literal[64] = 64
    prior_usage: ProviderBudgetUsageSeed
    recovery_budget: ProviderRecoveryBudgetManifest
    required_environment_variables: list[str]
    execute_flag: Literal["--execute"] = "--execute"
    approval_token: Literal["EXECUTE-NORTHSTAR-RFP-RECOVERY-V2"] = RECOVERY_APPROVAL_TOKEN
    output_policy: Literal["new_write_once_raw_archives"] = "new_write_once_raw_archives"
    scoring_during_execution: Literal[False] = False
    gold_labels_exposed_to_executors: Literal[False] = False

    @model_validator(mode="after")
    def recovery_scope_is_exact(self) -> ProviderRecoveryManifest:
        if self.architectures != list(ComparisonArchitecture):
            raise ValueError("recovery architecture order drifted")
        if [item.trial_number for item in self.runs] != [1, 2, 3]:
            raise ValueError("recovery requires trials 1, 2, and 3")
        if self.runs[0].case_ids != list(EXPECTED_CASE_IDS):
            raise ValueError("recovery primary run must contain all frozen cases")
        if any(item.case_ids != list(SELECTED_REPEAT_CASE_IDS) for item in self.runs[1:]):
            raise ValueError("recovery repeat scope drifted")
        if len({item.run_id for item in self.runs}) != 3:
            raise ValueError("recovery run IDs cannot repeat")
        if any(not item.run_id.endswith("-recovery-v2") for item in self.runs):
            raise ValueError("recovery must use new write-once v2 run IDs")
        if [item.path for item in self.execution_sources] != list(RECOVERY_EXECUTION_SOURCE_PATHS):
            raise ValueError("recovery execution source list drifted")
        expected_remaining_calls = (
            self.recovery_budget.original_max_provider_calls_total
            - self.prior_usage.attempted_calls
        )
        if self.recovery_budget.remaining_provider_calls != expected_remaining_calls:
            raise ValueError("recovery call remainder does not match prior usage")
        return self


def _artifact(path: Path) -> HashedArtifact:
    return HashedArtifact(
        path=path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix(),
        sha256=file_sha256(path),
    )


def _provider_configuration() -> ProviderConfigurationManifest:
    return ProviderConfigurationManifest(
        generation_model=OPENAI_GENERATION_MODEL,
        generation_endpoint=OPENAI_GENERATION_ENDPOINT,
        reasoning_effort=OPENAI_REASONING_EFFORT,
        max_output_tokens_per_call=OPENAI_MAX_OUTPUT_TOKENS,
        response_store=OPENAI_RESPONSE_STORE,
        strict_structured_outputs=OPENAI_STRUCTURED_OUTPUTS_STRICT,
        embedding_model=OPENAI_EMBEDDING_MODEL,
        embedding_dimensions=EMBEDDING_DIMENSION,
        pinecone_index=PINECONE_INDEX_NAME,
        pinecone_namespace=PINECONE_NAMESPACE,
        retrieval_top_k=RETRIEVAL_TOP_K,
        product_retrieval="hybrid_dense_sparse_top_5",
        security_retrieval="hybrid_dense_sparse_top_5",
        implementation_retrieval="dense_top_5",
        hybrid_sparse_weight=HYBRID_SPARSE_WEIGHT,
        hybrid_dense_weight=HYBRID_DENSE_WEIGHT,
    )


def build_provider_recovery_manifest() -> ProviderRecoveryManifest:
    approval = load_repeat_trial_approval()
    if not approval.budget_authorized or approval.authorized_cost_usd != 5.12:
        raise ProviderRecoveryManifestError("the original $5.12 budget is not approved")
    if file_sha256(DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH) != PREDECESSOR_MANIFEST_SHA256:
        raise ProviderRecoveryManifestError("predecessor manifest digest drifted")
    if file_sha256(DEFAULT_PROVIDER_ATTEMPT_PATH) != ATTEMPT_RECORD_SHA256:
        raise ProviderRecoveryManifestError("invalid-attempt record digest drifted")
    execution_sources = [_artifact(PROJECT_ROOT / path) for path in RECOVERY_EXECUTION_SOURCE_PATHS]
    source_paths = [
        DEFAULT_EVALUATION_DATASET_PATH,
        DEFAULT_FAIR_COMPARISON_PATH,
        DEFAULT_SHARED_SAFETY_POLICY_PATH,
        DEFAULT_REPEAT_TRIAL_PLAN_PATH,
        DEFAULT_REPEAT_TRIAL_APPROVAL_PATH,
        DEFAULT_PRICING_SNAPSHOT_PATH,
        DEFAULT_FAKE_REHEARSAL_PATH,
        DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH,
        DEFAULT_PROVIDER_ATTEMPT_PATH,
        *(PROJECT_ROOT / path for path in RECOVERY_EXECUTION_SOURCE_PATHS),
    ]
    return ProviderRecoveryManifest(
        predecessor_manifest=_artifact(DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH),
        invalid_attempt_record=_artifact(DEFAULT_PROVIDER_ATTEMPT_PATH),
        source_artifacts=[_artifact(path) for path in source_paths],
        execution_sources=execution_sources,
        provider_configuration=_provider_configuration(),
        architectures=list(ComparisonArchitecture),
        runs=[
            RunSpecification(
                run_id="northstar-provider-primary-recovery-v2",
                trial_number=1,
                case_ids=list(EXPECTED_CASE_IDS),
            ),
            RunSpecification(
                run_id="northstar-provider-repeat-trial-2-recovery-v2",
                trial_number=2,
                case_ids=list(SELECTED_REPEAT_CASE_IDS),
            ),
            RunSpecification(
                run_id="northstar-provider-repeat-trial-3-recovery-v2",
                trial_number=3,
                case_ids=list(SELECTED_REPEAT_CASE_IDS),
            ),
        ],
        prior_usage=ProviderBudgetUsageSeed(
            attempted_calls=36,
            completed_calls=36,
            failed_calls=0,
            input_tokens=57_403,
            output_tokens=11_971,
        ),
        recovery_budget=ProviderRecoveryBudgetManifest(),
        required_environment_variables=[
            "OPENAI_API_KEY",
            "OPENAI_MODEL",
            "PROVIDER_GRAPH_CALLS_ENABLED",
            "OPENAI_EMBEDDING_MODEL",
            "PINECONE_API_KEY",
            "PINECONE_INDEX",
            "PINECONE_NAMESPACE",
        ],
    )


def serialize_provider_recovery_manifest(
    manifest: ProviderRecoveryManifest,
) -> tuple[str, str]:
    content = json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def exact_provider_recovery_command(manifest_sha256: str) -> str:
    return (
        ".venv/bin/python scripts/run_provider_recovery.py --execute "
        "--manifest outputs/evaluation/provider_recovery_manifest_step_4_g7.json "
        f"--expected-manifest-sha256 {manifest_sha256} "
        f"--approval-token {RECOVERY_APPROVAL_TOKEN}"
    )


def render_provider_recovery_review(
    manifest: ProviderRecoveryManifest,
    manifest_sha256: str,
) -> str:
    return "\n".join(
        [
            "# Provider Comparison Recovery — Exact Command Review",
            "",
            "**Status:** AWAITING EXACT-COMMAND APPROVAL",
            "",
            f"**Recovery manifest SHA-256:** `{manifest_sha256}`",
            "",
            "## Why this is a recovery run",
            "",
            "Attempt 1 is preserved but excluded from architecture comparison because three local integration defects invalidated its outputs. This recovery uses corrected, hashed code and new write-once run IDs.",
            "",
            "## Cumulative budget boundary",
            "",
            "- Original approved maximum: $5.12 USD.",
            "- Already consumed: 36 calls, 57,403 input tokens, 11,971 output tokens, and an estimated $0.258458 in generation cost.",
            "- Remaining hard counters: 92 calls, 966,597 input tokens, and 244,029 output tokens.",
            "- Remaining generation-cost ceiling by subtraction: $4.861542; retrieval-provider usage remains excluded from the estimate.",
            "- The ledger begins at the already-consumed totals and stops before any next call that could exceed the original limits.",
            "- No automatic provider retries; all failures remain visible.",
            "",
            "## Exact command requiring separate approval",
            "",
            "```bash",
            exact_provider_recovery_command(manifest_sha256),
            "```",
            "",
            "Do not run this command until the user explicitly approves this recovery manifest SHA-256 and exact command.",
            "",
        ]
    )


def _write_exact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise ProviderRecoveryManifestError(f"refusing to overwrite different content: {path.name}")
    path.write_text(content, encoding="utf-8")


def write_provider_recovery_manifest(
    manifest: ProviderRecoveryManifest,
    *,
    output_path: Path = DEFAULT_PROVIDER_RECOVERY_MANIFEST_PATH,
    review_path: Path = DEFAULT_PROVIDER_RECOVERY_REVIEW_PATH,
) -> tuple[str, str]:
    content, digest = serialize_provider_recovery_manifest(manifest)
    _write_exact(output_path, content)
    _write_exact(output_path.with_suffix(".sha256"), f"{digest}  {output_path.name}\n")
    _write_exact(review_path, render_provider_recovery_review(manifest, digest))
    return content, digest


def load_provider_recovery_manifest(
    path: Path = DEFAULT_PROVIDER_RECOVERY_MANIFEST_PATH,
) -> ProviderRecoveryManifest:
    return ProviderRecoveryManifest.model_validate_json(path.read_text(encoding="utf-8"))


def verify_recovery_manifest_against_current_files(
    manifest: ProviderRecoveryManifest,
) -> None:
    for artifact in manifest.source_artifacts:
        path = PROJECT_ROOT / artifact.path
        if not path.is_file() or file_sha256(path) != artifact.sha256:
            raise ProviderRecoveryManifestError(
                f"reviewed recovery source drifted: {artifact.path}"
            )
