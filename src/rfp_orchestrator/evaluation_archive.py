"""Immutable raw evaluation-run bundles for Step 4.15."""

from __future__ import annotations

import json
import re
from enum import Enum
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from rfp_orchestrator.evaluation_freeze import text_sha256
from rfp_orchestrator.evaluation_metrics import (
    EvaluationMetricsError,
    calculate_metrics,
    load_evaluation_run,
)
from rfp_orchestrator.evaluation_runner import (
    DEFAULT_DRY_RUN_OUTPUT_PATH,
    EvaluationRunArtifact,
    EvaluationRunFailure,
    EvaluationRunStatus,
    serialize_evaluation_run,
)
from rfp_orchestrator.fair_comparison import ComparisonArchitecture

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RAW_ARCHIVE_ROOT = PROJECT_ROOT / "outputs" / "evaluation" / "raw_runs"
CONTROLLED_FAILURE_FIXTURE_RUN_ID = "step-4-15-controlled-failure-fixture"
CONTROLLED_FAILURE_FIXTURE_STARTED_AT = "2026-09-14T10:00:00-04:00"
CONTROLLED_FAILURE_FIXTURE_COMPLETED_AT = "2026-09-14T10:00:01-04:00"
RUN_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class EvaluationArchiveError(ValueError):
    """Raised when a raw bundle would be incomplete, unsafe, or overwritten."""


class ArchivePurpose(str, Enum):
    EVALUATION_RUN = "EVALUATION_RUN"
    CONTROLLED_FAILURE_FIXTURE = "CONTROLLED_FAILURE_FIXTURE"


class ArchivedFileKind(str, Enum):
    RAW_RUN = "RAW_RUN"
    SUCCESS_RECORD = "SUCCESS_RECORD"
    FAILURE_RECORD = "FAILURE_RECORD"


class ArchivedFile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    relative_path: str = Field(min_length=1)
    kind: ArchivedFileKind
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    byte_count: int = Field(gt=0)
    case_id: str | None = None
    architecture: ComparisonArchitecture | None = None

    @model_validator(mode="after")
    def identity_matches_kind(self) -> ArchivedFile:
        if self.kind is ArchivedFileKind.RAW_RUN:
            if self.case_id is not None or self.architecture is not None:
                raise ValueError("raw run entry cannot claim one case identity")
        elif self.case_id is None or self.architecture is None:
            raise ValueError("record entries require case and architecture")
        return self


class RawEvaluationBundleManifest(BaseModel):
    """Complete content map for a write-once raw evaluation directory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    format_version: Literal[1] = 1
    bundle_id: str = Field(min_length=1)
    purpose: ArchivePurpose
    source_run_id: str = Field(min_length=1)
    source_run_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    source_run_mode: str = Field(min_length=1)
    source_run_status: str = Field(min_length=1)
    source_started_at: str = Field(min_length=1)
    source_completed_at: str = Field(min_length=1)
    case_ids: list[str] = Field(min_length=1)
    architectures: list[ComparisonArchitecture] = Field(min_length=2, max_length=2)
    expected_execution_count: int = Field(ge=2)
    success_record_count: int = Field(ge=0)
    failure_record_count: int = Field(ge=0)
    raw_outputs_canonical: Literal[True] = True
    summary_files_in_bundle: Literal[False] = False
    overwrite_allowed: Literal[False] = False
    controlled_fixture_notice: str | None = None
    frozen_dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    fair_comparison_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    shared_safety_policy_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    files: list[ArchivedFile] = Field(min_length=3)

    @model_validator(mode="after")
    def manifest_is_complete(self) -> RawEvaluationBundleManifest:
        expected_count = len(self.case_ids) * len(self.architectures)
        if self.expected_execution_count != expected_count:
            raise ValueError("expected execution count must cover the full cross product")
        if self.success_record_count + self.failure_record_count != expected_count:
            raise ValueError("successes and failures must cover every execution")
        if len(self.files) != 1 + expected_count:
            raise ValueError("bundle requires one raw run plus one shard per execution")
        paths = [item.relative_path for item in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("archived file paths cannot repeat")
        raw_entries = [item for item in self.files if item.kind is ArchivedFileKind.RAW_RUN]
        if len(raw_entries) != 1 or raw_entries[0].relative_path != "raw/run.json":
            raise ValueError("bundle requires exactly one canonical raw/run.json")
        shard_keys = {
            (item.case_id, item.architecture)
            for item in self.files
            if item.kind is not ArchivedFileKind.RAW_RUN
        }
        expected_keys = {
            (case_id, architecture)
            for case_id in self.case_ids
            for architecture in self.architectures
        }
        if shard_keys != expected_keys:
            raise ValueError("record shards must cover every case and architecture")
        if (
            self.purpose is ArchivePurpose.CONTROLLED_FAILURE_FIXTURE
            and not self.controlled_fixture_notice
        ):
            raise ValueError("controlled fixture requires a prominent notice")
        if (
            self.purpose is ArchivePurpose.EVALUATION_RUN
            and self.controlled_fixture_notice is not None
        ):
            raise ValueError("real run bundle cannot carry a fixture notice")
        return self


def _stable_json(model: BaseModel) -> str:
    return json.dumps(model.model_dump(mode="json"), indent=2, sort_keys=True) + "\n"


def _file_entry(
    *,
    relative_path: str,
    kind: ArchivedFileKind,
    content: str,
    case_id: str | None = None,
    architecture: ComparisonArchitecture | None = None,
) -> ArchivedFile:
    return ArchivedFile(
        relative_path=relative_path,
        kind=kind,
        sha256=text_sha256(content),
        byte_count=len(content.encode("utf-8")),
        case_id=case_id,
        architecture=architecture,
    )


def build_controlled_failure_fixture() -> EvaluationRunArtifact:
    """Create a labeled non-result artifact solely to prove failure preservation."""

    source = load_evaluation_run(DEFAULT_DRY_RUN_OUTPUT_PATH)
    payload = source.model_dump(mode="python")
    failed_record = payload["records"].pop()
    payload.update(
        run_id=CONTROLLED_FAILURE_FIXTURE_RUN_ID,
        status=EvaluationRunStatus.PARTIAL,
        started_at=CONTROLLED_FAILURE_FIXTURE_STARTED_AT,
        completed_at=CONTROLLED_FAILURE_FIXTURE_COMPLETED_AT,
        failures=[
            EvaluationRunFailure(
                case_id=failed_record["case_id"],
                requirement_id=failed_record["requirement_id"],
                architecture=failed_record["architecture"],
                error_type="ControlledArchiveFixtureFailure",
                message=(
                    "Synthetic Step 4.15 fixture used only to verify that a failed "
                    "case is stored independently and never omitted."
                ),
            )
        ],
    )
    return EvaluationRunArtifact.model_validate(payload)


def build_bundle_contents(
    artifact: EvaluationRunArtifact,
    *,
    purpose: ArchivePurpose,
) -> tuple[RawEvaluationBundleManifest, dict[str, str]]:
    """Create the exact files for one immutable bundle without writing them."""

    if not RUN_ID_PATTERN.fullmatch(artifact.run_id):
        raise EvaluationArchiveError(
            "run ID may contain only letters, numbers, dots, underscores, and hyphens"
        )
    try:
        calculate_metrics(artifact)
    except EvaluationMetricsError as error:
        raise EvaluationArchiveError(str(error)) from error
    raw_content, raw_digest = serialize_evaluation_run(artifact)
    contents: dict[str, str] = {"raw/run.json": raw_content}
    files = [
        _file_entry(
            relative_path="raw/run.json",
            kind=ArchivedFileKind.RAW_RUN,
            content=raw_content,
        )
    ]
    for record in artifact.records:
        relative_path = (
            f"records/{record.case_id}/{record.architecture.value}.json"
        )
        content = _stable_json(record)
        contents[relative_path] = content
        files.append(
            _file_entry(
                relative_path=relative_path,
                kind=ArchivedFileKind.SUCCESS_RECORD,
                content=content,
                case_id=record.case_id,
                architecture=record.architecture,
            )
        )
    for failure in artifact.failures:
        relative_path = (
            f"failures/{failure.case_id}/{failure.architecture.value}.json"
        )
        content = _stable_json(failure)
        contents[relative_path] = content
        files.append(
            _file_entry(
                relative_path=relative_path,
                kind=ArchivedFileKind.FAILURE_RECORD,
                content=content,
                case_id=failure.case_id,
                architecture=failure.architecture,
            )
        )
    files.sort(key=lambda item: item.relative_path)
    notice = (
        "CONTROLLED TEST FIXTURE — this bundle does not report an observed agent "
        "failure and must not be included in comparative metrics."
        if purpose is ArchivePurpose.CONTROLLED_FAILURE_FIXTURE
        else None
    )
    manifest = RawEvaluationBundleManifest(
        bundle_id=f"raw-evaluation-bundle:{artifact.run_id}:v1",
        purpose=purpose,
        source_run_id=artifact.run_id,
        source_run_sha256=raw_digest,
        source_run_mode=artifact.mode.value,
        source_run_status=artifact.status.value,
        source_started_at=artifact.started_at,
        source_completed_at=artifact.completed_at,
        case_ids=artifact.case_ids,
        architectures=artifact.architectures,
        expected_execution_count=len(artifact.case_ids) * len(artifact.architectures),
        success_record_count=len(artifact.records),
        failure_record_count=len(artifact.failures),
        controlled_fixture_notice=notice,
        frozen_dataset_sha256=artifact.frozen_dataset_sha256,
        fair_comparison_sha256=artifact.fair_comparison_sha256,
        shared_safety_policy_sha256=artifact.shared_safety_policy_sha256,
        files=files,
    )
    return manifest, contents


def serialize_bundle_manifest(
    manifest: RawEvaluationBundleManifest,
) -> tuple[str, str]:
    content = _stable_json(manifest)
    return content, text_sha256(content)


def _expected_bundle_files(
    manifest: RawEvaluationBundleManifest,
    contents: dict[str, str],
) -> dict[str, str]:
    manifest_content, manifest_digest = serialize_bundle_manifest(manifest)
    return {
        **contents,
        "manifest.json": manifest_content,
        "manifest.sha256": f"{manifest_digest}  manifest.json\n",
    }


def _verify_existing_bundle(
    target: Path,
    expected: dict[str, str],
) -> None:
    actual_paths = {
        path.relative_to(target).as_posix()
        for path in target.rglob("*")
        if path.is_file()
    }
    if actual_paths != set(expected):
        raise EvaluationArchiveError(
            "existing raw bundle file set differs; refusing overwrite"
        )
    for relative_path, content in expected.items():
        if (target / relative_path).read_text(encoding="utf-8") != content:
            raise EvaluationArchiveError(
                f"existing raw bundle content differs at {relative_path}; refusing overwrite"
            )


def archive_evaluation_run(
    artifact: EvaluationRunArtifact,
    *,
    archive_root: Path = DEFAULT_RAW_ARCHIVE_ROOT,
    purpose: ArchivePurpose = ArchivePurpose.EVALUATION_RUN,
) -> tuple[Path, RawEvaluationBundleManifest, str]:
    """Atomically create or exactly reverify one write-once run directory."""

    manifest, contents = build_bundle_contents(artifact, purpose=purpose)
    expected = _expected_bundle_files(manifest, contents)
    archive_root.mkdir(parents=True, exist_ok=True)
    target = archive_root / artifact.run_id
    if target.exists():
        if not target.is_dir():
            raise EvaluationArchiveError("raw bundle target exists but is not a directory")
        _verify_existing_bundle(target, expected)
        _, digest = serialize_bundle_manifest(manifest)
        return target, manifest, digest

    with TemporaryDirectory(prefix=".archive-staging-", dir=archive_root) as temp_name:
        staging = Path(temp_name) / "bundle"
        staging.mkdir()
        for relative_path, content in expected.items():
            destination = staging / relative_path
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
        staging.replace(target)
    _verify_existing_bundle(target, expected)
    _, digest = serialize_bundle_manifest(manifest)
    return target, manifest, digest
