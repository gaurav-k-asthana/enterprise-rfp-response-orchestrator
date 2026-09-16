"""Deterministic, content-addressed manifest for the paid provider comparison."""

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
    load_repeat_trial_plan,
)
from rfp_orchestrator.fair_comparison import (
    DEFAULT_FAIR_COMPARISON_PATH,
    ComparisonArchitecture,
)
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "provider_execution_manifest_step_4_g6.json"
)
DEFAULT_PROVIDER_EXECUTION_REVIEW_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "provider_execution_review_step_4_g6.md"
)
DEFAULT_PROVIDER_EXECUTION_DIGEST_PATH = (
    DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH.with_suffix(".sha256")
)
DEFAULT_FAKE_REHEARSAL_PATH = (
    PROJECT_ROOT / "outputs" / "evaluation" / "fake_provider_rehearsal_step_4_g5.json"
)
EXECUTION_APPROVAL_TOKEN = "EXECUTE-NORTHSTAR-RFP-COMPARISON-V1"
MANIFEST_ID = "northstar-rfp-provider-execution-step-4-g6"
PREPARED_AT = "2026-09-15T09:00:00-04:00"

EXECUTION_SOURCE_PATHS = (
    "src/rfp_orchestrator/openai_generation.py",
    "src/rfp_orchestrator/provider_retrieval.py",
    "src/rfp_orchestrator/provider_generalist.py",
    "src/rfp_orchestrator/provider_specialists.py",
    "src/rfp_orchestrator/provider_orchestrated.py",
    "src/rfp_orchestrator/provider_budget.py",
    "src/rfp_orchestrator/provider_execution.py",
    "src/rfp_orchestrator/provider_execution_cli.py",
    "src/rfp_orchestrator/evaluation_runner.py",
    "scripts/run_provider_comparison.py",
)


class ProviderExecutionManifestError(RuntimeError):
    """Raised before provider initialization when the reviewed scope drifts."""


class HashedArtifact(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    path: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ProviderConfigurationManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generation_model: str
    generation_endpoint: str
    reasoning_effort: str
    max_output_tokens_per_call: int
    response_store: bool
    strict_structured_outputs: bool
    embedding_model: str
    embedding_dimensions: int
    pinecone_index: str
    pinecone_namespace: str
    retrieval_top_k: int
    product_retrieval: Literal["hybrid_dense_sparse_top_5"]
    security_retrieval: Literal["hybrid_dense_sparse_top_5"]
    implementation_retrieval: Literal["dense_top_5"]
    hybrid_sparse_weight: float
    hybrid_dense_weight: float


class ProviderBudgetManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    currency: Literal["USD"]
    authorized_maximum_usd: Literal[5.12]
    max_provider_calls_per_architecture_execution: Literal[3]
    max_provider_calls_total: Literal[128]
    max_input_tokens_per_provider_call: Literal[8000]
    max_output_tokens_per_provider_call: Literal[2000]
    max_total_input_tokens: Literal[1024000]
    max_total_output_tokens: Literal[256000]
    automatic_provider_retries_allowed: Literal[False]
    stop_before_next_call_when_cap_would_be_exceeded: Literal[True]


class ProviderExecutionManifest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    manifest_id: Literal["northstar-rfp-provider-execution-step-4-g6"] = MANIFEST_ID
    prepared_at: Literal["2026-09-15T09:00:00-04:00"] = PREPARED_AT
    status: Literal["AWAITING_EXACT_COMMAND_APPROVAL"] = (
        "AWAITING_EXACT_COMMAND_APPROVAL"
    )
    paid_command_approved: Literal[False] = False
    provider_calls_made: Literal[0] = 0
    network_calls_made: Literal[0] = 0
    gold_labels_exposed_to_executors: Literal[False] = False
    scoring_during_execution: Literal[False] = False
    source_artifacts: list[HashedArtifact] = Field(min_length=17)
    execution_sources: list[HashedArtifact] = Field(min_length=10, max_length=10)
    provider_configuration: ProviderConfigurationManifest
    architectures: list[ComparisonArchitecture] = Field(min_length=2, max_length=2)
    runs: list[RunSpecification] = Field(min_length=3, max_length=3)
    primary_architecture_execution_count: Literal[48] = 48
    repeat_architecture_execution_count: Literal[16] = 16
    total_architecture_execution_count: Literal[64] = 64
    budget: ProviderBudgetManifest
    required_environment_variables: list[str]
    execute_flag: Literal["--execute"] = "--execute"
    approval_token: Literal["EXECUTE-NORTHSTAR-RFP-COMPARISON-V1"] = (
        EXECUTION_APPROVAL_TOKEN
    )
    output_policy: Literal["write_once_raw_archives"] = "write_once_raw_archives"

    @model_validator(mode="after")
    def scope_is_exact(self) -> ProviderExecutionManifest:
        if self.architectures != list(ComparisonArchitecture):
            raise ValueError("provider manifest architecture order drifted")
        if [item.trial_number for item in self.runs] != [1, 2, 3]:
            raise ValueError("provider manifest requires trials 1, 2, and 3")
        if self.runs[0].case_ids != list(EXPECTED_CASE_IDS):
            raise ValueError("primary run must contain all 24 frozen cases")
        if any(
            item.case_ids != list(SELECTED_REPEAT_CASE_IDS)
            for item in self.runs[1:]
        ):
            raise ValueError("repeat runs must contain the approved four-case subset")
        if len({item.run_id for item in self.runs}) != 3:
            raise ValueError("provider run IDs cannot repeat")
        if self.total_architecture_execution_count != sum(
            len(item.case_ids) * len(self.architectures) for item in self.runs
        ):
            raise ValueError("provider architecture execution count drifted")
        paths = [item.path for item in self.source_artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("provider source artifact paths cannot repeat")
        execution_paths = [item.path for item in self.execution_sources]
        if execution_paths != list(EXECUTION_SOURCE_PATHS):
            raise ValueError("provider execution source list drifted")
        return self


def _artifact(path: Path) -> HashedArtifact:
    return HashedArtifact(
        path=path.resolve().relative_to(PROJECT_ROOT.resolve()).as_posix(),
        sha256=file_sha256(path),
    )


def _source_paths() -> list[Path]:
    return [
        DEFAULT_EVALUATION_DATASET_PATH,
        DEFAULT_FAIR_COMPARISON_PATH,
        DEFAULT_SHARED_SAFETY_POLICY_PATH,
        DEFAULT_REPEAT_TRIAL_PLAN_PATH,
        DEFAULT_REPEAT_TRIAL_APPROVAL_PATH,
        DEFAULT_PRICING_SNAPSHOT_PATH,
        DEFAULT_FAKE_REHEARSAL_PATH,
        *(PROJECT_ROOT / path for path in EXECUTION_SOURCE_PATHS),
    ]


def build_provider_execution_manifest() -> ProviderExecutionManifest:
    plan = load_repeat_trial_plan()
    approval = load_repeat_trial_approval()
    if file_sha256(DEFAULT_REPEAT_TRIAL_PLAN_PATH) != approval.proposal_sha256:
        raise ProviderExecutionManifestError("repeat-trial approval does not match the plan")
    if not approval.budget_authorized or approval.authorized_cost_usd != 5.12:
        raise ProviderExecutionManifestError("the exact $5.12 budget is not approved")
    if approval.paid_command_approved or approval.provider_calls_made:
        raise ProviderExecutionManifestError("approval history is not at its pre-command state")
    if plan.primary_case_ids != list(EXPECTED_CASE_IDS):
        raise ProviderExecutionManifestError("primary case scope drifted")

    budget = plan.budget
    return ProviderExecutionManifest(
        source_artifacts=[_artifact(path) for path in _source_paths()],
        execution_sources=[
            _artifact(PROJECT_ROOT / path) for path in EXECUTION_SOURCE_PATHS
        ],
        provider_configuration=ProviderConfigurationManifest(
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
        ),
        architectures=list(ComparisonArchitecture),
        runs=[
            RunSpecification(
                run_id="northstar-provider-primary-v1",
                trial_number=1,
                case_ids=list(EXPECTED_CASE_IDS),
            ),
            RunSpecification(
                run_id="northstar-provider-repeat-trial-2-v1",
                trial_number=2,
                case_ids=list(SELECTED_REPEAT_CASE_IDS),
            ),
            RunSpecification(
                run_id="northstar-provider-repeat-trial-3-v1",
                trial_number=3,
                case_ids=list(SELECTED_REPEAT_CASE_IDS),
            ),
        ],
        budget=ProviderBudgetManifest(
            currency=approval.currency,
            authorized_maximum_usd=approval.authorized_cost_usd,
            max_provider_calls_per_architecture_execution=(
                budget.max_provider_calls_per_architecture_execution
            ),
            max_provider_calls_total=budget.max_provider_calls_total,
            max_input_tokens_per_provider_call=budget.max_input_tokens_per_provider_call,
            max_output_tokens_per_provider_call=budget.max_output_tokens_per_provider_call,
            max_total_input_tokens=budget.max_total_input_tokens,
            max_total_output_tokens=budget.max_total_output_tokens,
            automatic_provider_retries_allowed=budget.automatic_provider_retries_allowed,
            stop_before_next_call_when_cap_would_be_exceeded=(
                budget.stop_before_next_call_when_cap_would_be_exceeded
            ),
        ),
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


def serialize_provider_execution_manifest(
    manifest: ProviderExecutionManifest,
) -> tuple[str, str]:
    content = json.dumps(manifest.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def exact_provider_command(manifest_sha256: str) -> str:
    return (
        ".venv/bin/python scripts/run_provider_comparison.py --execute "
        "--manifest outputs/evaluation/provider_execution_manifest_step_4_g6.json "
        f"--expected-manifest-sha256 {manifest_sha256} "
        f"--approval-token {EXECUTION_APPROVAL_TOKEN}"
    )


def render_provider_execution_review(
    manifest: ProviderExecutionManifest,
    manifest_sha256: str,
) -> str:
    command = exact_provider_command(manifest_sha256)
    return "\n".join(
        [
            "# Provider Comparison Execution — Exact Command Review",
            "",
            "**Status:** AWAITING EXACT-COMMAND APPROVAL",
            "",
            f"**Manifest SHA-256:** `{manifest_sha256}`",
            "",
            "## Reviewed scope",
            "",
            "- 24 primary cases through both architectures: 48 executions.",
            "- Trials 2 and 3 for EVAL-001, EVAL-002, EVAL-015, and EVAL-021: 16 executions.",
            "- Maximum total: 64 architecture executions and 128 generation calls.",
            "- Maximum tokens: 1,024,000 input and 256,000 output.",
            "- Maximum authorized spend: $5.12 USD; this is a ceiling, not an estimate.",
            "- No automatic provider retries; every execution failure remains in the denominator.",
            "- Raw outputs are write-once and scoring occurs only after execution.",
            "",
            "## Required local `.env` state at execution time",
            "",
            "- `OPENAI_API_KEY` and `PINECONE_API_KEY` must be populated locally; values never enter the manifest or output.",
            f"- `OPENAI_MODEL={OPENAI_GENERATION_MODEL}`",
            "- `PROVIDER_GRAPH_CALLS_ENABLED=true`",
            f"- `OPENAI_EMBEDDING_MODEL={OPENAI_EMBEDDING_MODEL}`",
            f"- `PINECONE_INDEX={PINECONE_INDEX_NAME}`",
            f"- `PINECONE_NAMESPACE={PINECONE_NAMESPACE}`",
            "",
            "## Exact command requiring separate approval",
            "",
            "```bash",
            command,
            "```",
            "",
            "Do not run this command until the user explicitly approves this exact manifest SHA-256 and exact command. Step 4.G6 prepares the boundary only and makes zero provider calls.",
            "",
        ]
    )


def _write_exact(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") != content:
        raise ProviderExecutionManifestError(
            f"refusing to overwrite different content: {path.name}"
        )
    path.write_text(content, encoding="utf-8")


def write_provider_execution_manifest(
    manifest: ProviderExecutionManifest,
    *,
    output_path: Path = DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH,
    review_path: Path = DEFAULT_PROVIDER_EXECUTION_REVIEW_PATH,
) -> tuple[str, str]:
    content, digest = serialize_provider_execution_manifest(manifest)
    _write_exact(output_path, content)
    _write_exact(output_path.with_suffix(".sha256"), f"{digest}  {output_path.name}\n")
    _write_exact(review_path, render_provider_execution_review(manifest, digest))
    return content, digest


def load_provider_execution_manifest(
    path: Path = DEFAULT_PROVIDER_EXECUTION_MANIFEST_PATH,
) -> ProviderExecutionManifest:
    return ProviderExecutionManifest.model_validate_json(path.read_text(encoding="utf-8"))


def verify_manifest_against_current_files(
    manifest: ProviderExecutionManifest,
) -> None:
    for artifact in manifest.source_artifacts:
        path = PROJECT_ROOT / artifact.path
        if not path.is_file() or file_sha256(path) != artifact.sha256:
            raise ProviderExecutionManifestError(
                f"reviewed source artifact drifted: {artifact.path}"
            )
