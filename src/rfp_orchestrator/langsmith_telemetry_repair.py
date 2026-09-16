"""Hash-bound metadata-only repair for the existing Step 5.3 root run."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from langsmith import Client

from rfp_orchestrator.config import Settings
from rfp_orchestrator.evaluation_freeze import file_sha256
from rfp_orchestrator.langsmith_metadata import TraceOperationalMetadata
from rfp_orchestrator.langsmith_smoke import validate_langsmith_settings
from rfp_orchestrator.langsmith_telemetry import TraceTelemetry

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TELEMETRY_RECEIPT_PATH = (
    PROJECT_ROOT / "outputs" / "observability" / "langsmith_telemetry_trace_step_5_3.json"
)
TELEMETRY_RECEIPT_SHA256 = (
    "a9f0a83197b45d7e4f37086326727c5ef6d857c825969489589c4a119d5feeed"
)
TELEMETRY_TRACE_ID = UUID("6faf6cf3-e9fb-4252-9e2e-b63add6ea42e")
TELEMETRY_REPAIR_APPROVAL_TOKEN = "REPAIR-TELEMETRY-METADATA-RFP-003"
TELEMETRY_REPAIR_DISABLED_REASON = (
    "LangSmith refused the finalized-run patch with HTTP 409; retries are disabled"
)


class LangSmithTelemetryRepairError(ValueError):
    """Raised before network activity if the saved trace receipt has drifted."""


@dataclass(frozen=True)
class LangSmithTelemetryRepairReceipt:
    trace_id: str
    source_receipt_sha256: str
    metadata_field_count: int
    langsmith_metadata_updates: int = 1
    langsmith_root_traces_written: int = 0
    openai_calls_made: int = 0
    pinecone_calls_made: int = 0


def _validated_repair_metadata(
    receipt_path: Path = TELEMETRY_RECEIPT_PATH,
) -> dict[str, object]:
    observed_digest = file_sha256(receipt_path)
    if observed_digest != TELEMETRY_RECEIPT_SHA256:
        raise LangSmithTelemetryRepairError(
            "Step 5.3 receipt SHA-256 does not match the reviewed trace"
        )
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    expected_identity = {
        "project_name": "enterprise-rfp-orchestrator",
        "run_name": "step-5-3-rfp-003-safe-telemetry-check",
        "trace_id": str(TELEMETRY_TRACE_ID),
        "data_classification": "SYNTHETIC_ONLY",
        "api_key_recorded": False,
    }
    for key, expected in expected_identity.items():
        if receipt.get(key) != expected:
            raise LangSmithTelemetryRepairError(f"Step 5.3 receipt identity drifted: {key}")

    operational_payload = receipt.get("operational_metadata")
    telemetry_payload = receipt.get("telemetry")
    if not isinstance(operational_payload, dict) or not isinstance(telemetry_payload, dict):
        raise LangSmithTelemetryRepairError("Step 5.3 receipt metadata is missing")
    operational = TraceOperationalMetadata.model_validate(
        {
            "trace_metadata_schema_version": operational_payload.get(
                "rfp_trace_metadata_schema_version"
            ),
            "case_id": operational_payload.get("rfp_case_id"),
            "requirement_id": operational_payload.get("rfp_requirement_id"),
            "strategy": operational_payload.get("rfp_strategy"),
            "selected_specialists": operational_payload.get("rfp_selected_specialists"),
            "retry_count": operational_payload.get("rfp_retry_count"),
            "risk_classes": operational_payload.get("rfp_risk_classes"),
            "final_status": operational_payload.get("rfp_final_status"),
        }
    )
    telemetry = TraceTelemetry.model_validate(
        {
            "trace_telemetry_schema_version": telemetry_payload.get(
                "rfp_trace_telemetry_schema_version"
            ),
            "latency_ms": telemetry_payload.get("rfp_latency_ms"),
            "provider_calls": telemetry_payload.get("rfp_provider_calls"),
            "token_usage_observed": telemetry_payload.get("rfp_token_usage_observed"),
            "input_tokens": telemetry_payload.get("rfp_input_tokens"),
            "output_tokens": telemetry_payload.get("rfp_output_tokens"),
            "total_tokens": telemetry_payload.get("rfp_total_tokens"),
            "error_count": telemetry_payload.get("rfp_error_count"),
            "error_code": telemetry_payload.get("rfp_error_code"),
            "raw_inputs_logged": telemetry_payload.get("rfp_raw_inputs_logged"),
            "raw_outputs_logged": telemetry_payload.get("rfp_raw_outputs_logged"),
            "raw_error_details_logged": telemetry_payload.get(
                "rfp_raw_error_details_logged"
            ),
        }
    )
    return {
        **operational.as_langsmith_metadata(),
        **telemetry.as_langsmith_metadata(),
    }


def repair_langsmith_telemetry_metadata(
    *,
    settings: Settings | None = None,
    client_factory: Callable[..., Any] = Client,
    receipt_path: Path = TELEMETRY_RECEIPT_PATH,
) -> LangSmithTelemetryRepairReceipt:
    """Retain the reviewed repair boundary but refuse retries after HTTP 409."""

    active_settings = settings or Settings()
    validate_langsmith_settings(active_settings)
    _validated_repair_metadata(receipt_path)
    del client_factory
    raise LangSmithTelemetryRepairError(TELEMETRY_REPAIR_DISABLED_REASON)
