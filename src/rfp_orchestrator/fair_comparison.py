"""Frozen Step 4.9 contract for a fair two-architecture comparison."""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_freeze import (
    DEFAULT_FREEZE_MANIFEST_PATH,
    file_sha256,
    gold_content_sha256,
    text_sha256,
    validate_frozen_gold,
)
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    load_evaluation_dataset,
)
from rfp_orchestrator.generalist_baseline import GENERALIST_TOOL_SPECS
from rfp_orchestrator.ingestion import (
    DEFAULT_CORPUS_DIRECTORY,
    DEFAULT_MANIFEST_PATH,
    build_ingestion_plan,
    load_reviewed_manifest,
)
from rfp_orchestrator.provider_config import (
    BM25_B,
    BM25_K1,
    EMBEDDING_DIMENSION,
    EMBEDDING_ENCODING,
    HYBRID_DENSE_WEIGHT,
    HYBRID_SPARSE_WEIGHT,
    OPENAI_EMBEDDING_MODEL,
    OPENAI_GENERATION_ENDPOINT,
    OPENAI_GENERATION_MODEL,
    OPENAI_GENERATION_MODEL_IDENTIFIER_TYPE,
    OPENAI_MAX_OUTPUT_TOKENS,
    OPENAI_REASONING_EFFORT,
    OPENAI_RESPONSE_STORE,
    OPENAI_STRUCTURED_OUTPUTS_STRICT,
    PINECONE_INDEX_NAME,
    PINECONE_METRIC,
    PINECONE_NAMESPACE,
    RETRIEVAL_MIN_RELATIVE_SCORE,
    RETRIEVAL_TOP_K,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FAIR_COMPARISON_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "fair_comparison_config_v1.json"
)
DEFAULT_FAIR_COMPARISON_DIGEST_PATH = (
    PROJECT_ROOT / "data" / "evaluation" / "fair_comparison_config_v1.sha256"
)
COMPARISON_ID = "northstar-rfp-fair-comparison-v1"
COMPARISON_FROZEN_AT = "2026-09-03T22:20:06-04:00"

NORMALIZED_OUTPUT_FIELDS = (
    "case_id",
    "requirement_id",
    "architecture",
    "atomic_requirements",
    "consulted_domains",
    "retrieval_calls",
    "evidence",
    "claims",
    "proposed_answer",
    "support_status",
    "citation_valid",
    "source_metadata_valid",
    "conflicts",
    "retry_count",
    "risk_classes",
    "authority_required",
    "awaiting_human_review",
    "final_status",
    "final_answer",
    "errors",
    "model_usage",
    "latency_ms",
)

INTENDED_ARCHITECTURE_DIFFERENCES = (
    "reasoning prompt roles",
    "one generalist versus orchestrator-selected peer specialists",
    "dynamic topology and fan-out/fan-in",
    "architecture-driven model-call count, routing, and recovery path",
)


class ComparisonArchitecture(str, Enum):
    SINGLE_GENERALIST = "single_generalist"
    ORCHESTRATED_PEERS = "orchestrated_peer_specialists"


class FrozenQuestionSet(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str
    dataset_status: Literal["FROZEN"]
    case_count: Literal[24]
    case_ids: list[str] = Field(min_length=24, max_length=24)
    question_set_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    frozen_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    analyzer_path: Literal["src/rfp_orchestrator/requirement_classification.py"]
    analyzer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def case_ids_are_unique(self) -> FrozenQuestionSet:
        if len(self.case_ids) != len(set(self.case_ids)):
            raise ValueError("comparison case IDs cannot repeat")
        return self


class FrozenCorpusProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    corpus_directory: Literal["data/kb"]
    reviewed_manifest_path: Literal["outputs/ingestion_manifest_v1.json"]
    reviewed_manifest_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewed_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    corpus_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    document_count: Literal[12]
    record_count: Literal[20]
    record_ids: list[str] = Field(min_length=20, max_length=20)

    @model_validator(mode="after")
    def record_ids_are_unique(self) -> FrozenCorpusProfile:
        if len(self.record_ids) != len(set(self.record_ids)):
            raise ValueError("comparison corpus record IDs cannot repeat")
        return self


class FrozenGenerationProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["OpenAI API"] = "OpenAI API"
    model: str
    model_identifier_type: str
    endpoint: str
    reasoning_effort: str
    max_output_tokens: int = Field(gt=0)
    structured_outputs_strict: bool
    store: bool
    temperature: Literal["omitted"] = "omitted"
    top_p: Literal["omitted"] = "omitted"


class FrozenRetrievalTool(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_name: str
    domain: str
    retrieval_policy: str
    top_k: Literal[5]
    minimum_relative_score: float = Field(ge=0, le=1)
    embedding_model: str
    embedding_dimension: int = Field(gt=0)
    embedding_encoding: str
    index: str
    namespace: str
    metric: str
    bm25_k1: float | None = None
    bm25_b: float | None = None
    sparse_weight: float | None = None
    dense_weight: float

    @model_validator(mode="after")
    def weights_match_retrieval_policy(self) -> FrozenRetrievalTool:
        is_hybrid = self.domain in {"product", "security"}
        hybrid_values = (
            self.bm25_k1,
            self.bm25_b,
            self.sparse_weight,
        )
        if is_hybrid:
            if any(value is None for value in hybrid_values):
                raise ValueError("hybrid comparison tools require sparse configuration")
            if abs((self.sparse_weight or 0) + self.dense_weight - 1.0) > 1e-9:
                raise ValueError("hybrid comparison weights must sum to one")
        elif any(value is not None for value in hybrid_values):
            raise ValueError("dense-only comparison tools cannot claim sparse settings")
        elif self.dense_weight != 1.0:
            raise ValueError("dense-only comparison tools require dense weight one")
        return self


class FrozenOutputContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    normalized_fields: list[str] = Field(min_length=len(NORMALIZED_OUTPUT_FIELDS))
    claim_support_type: Literal["per-atomic-claim boolean"]
    aggregate_support_values: list[str] = Field(min_length=3, max_length=3)
    citation_rule: str
    failure_rule: str

    @model_validator(mode="after")
    def fields_and_statuses_are_exact(self) -> FrozenOutputContract:
        if tuple(self.normalized_fields) != NORMALIZED_OUTPUT_FIELDS:
            raise ValueError("normalized comparison output fields drifted")
        if self.aggregate_support_values != [
            "SUPPORTED",
            "PARTIAL",
            "UNSUPPORTED",
        ]:
            raise ValueError("aggregate comparison support values drifted")
        return self


class ComparisonArmProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    architecture: ComparisonArchitecture
    questions: FrozenQuestionSet
    corpus: FrozenCorpusProfile
    generation: FrozenGenerationProfile
    retrieval_tools: list[FrozenRetrievalTool] = Field(min_length=3, max_length=3)
    output_contract: FrozenOutputContract


class GoldScoringReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_id: str
    gold_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    freeze_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    exposed_to_comparison_arms: Literal[False] = False


class FairComparisonFreeze(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    comparison_id: Literal["northstar-rfp-fair-comparison-v1"] = COMPARISON_ID
    status: Literal["FROZEN"] = "FROZEN"
    frozen_at: str
    baseline: ComparisonArmProfile
    orchestrated: ComparisonArmProfile
    shared_profile_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    gold_scoring_reference: GoldScoringReference
    intended_architecture_differences: list[str]
    deferred_controls: list[str]
    verification: dict[str, bool | int]

    @model_validator(mode="after")
    def profiles_are_fair_and_scope_is_explicit(self) -> FairComparisonFreeze:
        validate_fair_profiles(self.baseline, self.orchestrated)
        observed_digest = shared_profile_sha256(self.baseline)
        if self.shared_profile_sha256 != observed_digest:
            raise ValueError("shared comparison profile checksum drifted")
        if tuple(self.intended_architecture_differences) != (
            INTENDED_ARCHITECTURE_DIFFERENCES
        ):
            raise ValueError("intended architecture differences drifted")
        if self.gold_scoring_reference.exposed_to_comparison_arms:
            raise ValueError("comparison arms cannot receive gold labels")
        return self


def _canonical_sha256(value: object) -> str:
    canonical = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    return text_sha256(canonical)


def _question_set_sha256() -> str:
    dataset = load_evaluation_dataset()
    questions = [
        {
            "case_id": case.case_id,
            "requirement_id": case.requirement_id,
            "untrusted_rfp_text": case.untrusted_rfp_text,
        }
        for case in dataset.cases
    ]
    return _canonical_sha256(questions)


def _build_question_profile(project_root: Path) -> FrozenQuestionSet:
    dataset = load_evaluation_dataset()
    validate_frozen_gold(dataset)
    analyzer_path = project_root / "src" / "rfp_orchestrator" / "requirement_classification.py"
    return FrozenQuestionSet(
        dataset_id=dataset.dataset_id,
        dataset_status=dataset.status.value,
        case_count=len(dataset.cases),
        case_ids=[case.case_id for case in dataset.cases],
        question_set_sha256=_question_set_sha256(),
        frozen_dataset_sha256=file_sha256(DEFAULT_EVALUATION_DATASET_PATH),
        analyzer_path="src/rfp_orchestrator/requirement_classification.py",
        analyzer_sha256=file_sha256(analyzer_path),
    )


def _build_corpus_profile() -> FrozenCorpusProfile:
    reviewed = load_reviewed_manifest(DEFAULT_MANIFEST_PATH)
    current = build_ingestion_plan(DEFAULT_CORPUS_DIRECTORY).public_manifest()
    if reviewed != current:
        raise ValueError("reviewed corpus manifest no longer matches the current corpus")
    return FrozenCorpusProfile(
        corpus_directory="data/kb",
        reviewed_manifest_path="outputs/ingestion_manifest_v1.json",
        reviewed_manifest_file_sha256=file_sha256(DEFAULT_MANIFEST_PATH),
        reviewed_manifest_sha256=str(reviewed["manifest_sha256"]),
        corpus_sha256=str(reviewed["corpus_sha256"]),
        document_count=int(reviewed["document_count"]),
        record_count=int(reviewed["record_count"]),
        record_ids=[str(value) for value in reviewed["record_ids"]],
    )


def _build_generation_profile() -> FrozenGenerationProfile:
    return FrozenGenerationProfile(
        model=OPENAI_GENERATION_MODEL,
        model_identifier_type=OPENAI_GENERATION_MODEL_IDENTIFIER_TYPE,
        endpoint=OPENAI_GENERATION_ENDPOINT,
        reasoning_effort=OPENAI_REASONING_EFFORT,
        max_output_tokens=OPENAI_MAX_OUTPUT_TOKENS,
        structured_outputs_strict=OPENAI_STRUCTURED_OUTPUTS_STRICT,
        store=OPENAI_RESPONSE_STORE,
    )


def _build_retrieval_tools() -> list[FrozenRetrievalTool]:
    tools: list[FrozenRetrievalTool] = []
    for spec in GENERALIST_TOOL_SPECS:
        is_hybrid = spec.domain.value in {"product", "security"}
        tools.append(
            FrozenRetrievalTool(
                tool_name=spec.name.value,
                domain=spec.domain.value,
                retrieval_policy=spec.retrieval_policy,
                top_k=RETRIEVAL_TOP_K,
                minimum_relative_score=RETRIEVAL_MIN_RELATIVE_SCORE,
                embedding_model=OPENAI_EMBEDDING_MODEL,
                embedding_dimension=EMBEDDING_DIMENSION,
                embedding_encoding=EMBEDDING_ENCODING,
                index=PINECONE_INDEX_NAME,
                namespace=PINECONE_NAMESPACE,
                metric=PINECONE_METRIC,
                bm25_k1=BM25_K1 if is_hybrid else None,
                bm25_b=BM25_B if is_hybrid else None,
                sparse_weight=HYBRID_SPARSE_WEIGHT if is_hybrid else None,
                dense_weight=HYBRID_DENSE_WEIGHT if is_hybrid else 1.0,
            )
        )
    return tools


def _build_output_contract() -> FrozenOutputContract:
    return FrozenOutputContract(
        normalized_fields=list(NORMALIZED_OUTPUT_FIELDS),
        claim_support_type="per-atomic-claim boolean",
        aggregate_support_values=["SUPPORTED", "PARTIAL", "UNSUPPORTED"],
        citation_rule="Citations must identify evidence returned by that architecture's recorded retrieval calls.",
        failure_rule="Errors, blocked cases, and unsafe outcomes remain visible in raw results and denominators.",
    )


def build_comparison_profiles(
    project_root: Path = PROJECT_ROOT,
) -> tuple[ComparisonArmProfile, ComparisonArmProfile]:
    """Build both arms from one shared configuration source."""

    shared = {
        "questions": _build_question_profile(project_root),
        "corpus": _build_corpus_profile(),
        "generation": _build_generation_profile(),
        "retrieval_tools": _build_retrieval_tools(),
        "output_contract": _build_output_contract(),
    }
    baseline = ComparisonArmProfile(
        architecture=ComparisonArchitecture.SINGLE_GENERALIST,
        **shared,
    )
    orchestrated = ComparisonArmProfile(
        architecture=ComparisonArchitecture.ORCHESTRATED_PEERS,
        **shared,
    )
    validate_fair_profiles(baseline, orchestrated)
    return baseline, orchestrated


def _shared_profile_payload(profile: ComparisonArmProfile) -> dict[str, object]:
    return profile.model_dump(mode="json", exclude={"architecture"})


def shared_profile_sha256(profile: ComparisonArmProfile) -> str:
    return _canonical_sha256(_shared_profile_payload(profile))


def validate_fair_profiles(
    baseline: ComparisonArmProfile,
    orchestrated: ComparisonArmProfile,
) -> None:
    """Reject any difference outside the named architecture identity."""

    if baseline.architecture is not ComparisonArchitecture.SINGLE_GENERALIST:
        raise ValueError("baseline profile has the wrong architecture identity")
    if orchestrated.architecture is not ComparisonArchitecture.ORCHESTRATED_PEERS:
        raise ValueError("orchestrated profile has the wrong architecture identity")
    if _shared_profile_payload(baseline) != _shared_profile_payload(orchestrated):
        raise ValueError(
            "fair comparison drift: questions, corpus, model, tools, and output must match"
        )


def build_fair_comparison_freeze(
    project_root: Path = PROJECT_ROOT,
) -> FairComparisonFreeze:
    """Build the complete secret-free Step 4.9 freeze artifact."""

    baseline, orchestrated = build_comparison_profiles(project_root)
    dataset = load_evaluation_dataset()
    return FairComparisonFreeze(
        frozen_at=COMPARISON_FROZEN_AT,
        baseline=baseline,
        orchestrated=orchestrated,
        shared_profile_sha256=shared_profile_sha256(baseline),
        gold_scoring_reference=GoldScoringReference(
            dataset_id=dataset.dataset_id,
            gold_content_sha256=gold_content_sha256(dataset),
            freeze_manifest_sha256=file_sha256(DEFAULT_FREEZE_MANIFEST_PATH),
        ),
        intended_architecture_differences=list(INTENDED_ARCHITECTURE_DIFFERENCES),
        deferred_controls=[
            "Step 4.10 applies identical deterministic risk and authority rules.",
            "Step 4.11 implements the runner and performs the first guided dry case.",
            "No comparative result exists at this freeze checkpoint.",
        ],
        verification={
            "profiles_equal_except_architecture": True,
            "frozen_gold_valid": True,
            "reviewed_corpus_matches_current": True,
            "gold_exposed_to_comparison_arms": False,
            "network_calls_made": 0,
            "comparative_cases_run": 0,
        },
    )


def validate_fair_comparison_freeze(freeze: FairComparisonFreeze) -> None:
    """Revalidate the artifact against current checked-in shared inputs."""

    current = build_fair_comparison_freeze(PROJECT_ROOT)
    if freeze != current:
        raise ValueError("frozen fair-comparison configuration drifted")


def serialize_fair_comparison_freeze(
    freeze: FairComparisonFreeze,
) -> tuple[str, str]:
    """Return the canonical checked-in representation and its digest."""

    content = json.dumps(freeze.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"
    return content, text_sha256(content)


def write_fair_comparison_freeze(
    output_path: Path = DEFAULT_FAIR_COMPARISON_PATH,
) -> tuple[str, str]:
    """Write once or verify the identical existing Step 4.9 artifact."""

    freeze = build_fair_comparison_freeze(PROJECT_ROOT)
    validate_fair_comparison_freeze(freeze)
    content, digest = serialize_fair_comparison_freeze(freeze)
    if output_path.exists() and output_path.read_text(encoding="utf-8") != content:
        raise ValueError("refusing to overwrite a different fair-comparison freeze")
    output_path.write_text(content, encoding="utf-8")
    digest_path = output_path.with_suffix(".sha256")
    digest_content = f"{digest}  {output_path.name}\n"
    if digest_path.exists() and digest_path.read_text(encoding="utf-8") != digest_content:
        raise ValueError("refusing to overwrite a different comparison checksum")
    digest_path.write_text(digest_content, encoding="utf-8")
    return content, digest
