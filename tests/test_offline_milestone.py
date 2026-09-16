import hashlib
import json
from pathlib import Path

import pytest

from rfp_orchestrator.offline_milestone import (
    EXPECTED_TEST_COUNT,
    build_offline_milestone_manifest,
    validate_offline_milestone_manifest,
)
from rfp_orchestrator.provider_config import (
    OPENAI_GENERATION_ENDPOINT,
    OPENAI_GENERATION_MODEL,
    OPENAI_GENERATION_MODEL_IDENTIFIER_TYPE,
    OPENAI_MAX_OUTPUT_TOKENS,
    OPENAI_REASONING_EFFORT,
    OPENAI_RESPONSE_STORE,
    OPENAI_STRUCTURED_OUTPUTS_STRICT,
    PROVIDER_GRAPH_CALLS_ENABLED,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = PROJECT_ROOT / "outputs" / "offline_graph_milestone_v1.json"
DIGEST_PATH = PROJECT_ROOT / "outputs" / "offline_graph_milestone_v1.sha256"


def test_generation_configuration_is_exact_but_provider_calls_remain_disabled() -> None:
    assert OPENAI_GENERATION_MODEL == "gpt-5.6-terra"
    assert OPENAI_GENERATION_MODEL_IDENTIFIER_TYPE == "alias"
    assert OPENAI_GENERATION_ENDPOINT == "responses"
    assert OPENAI_REASONING_EFFORT == "low"
    assert OPENAI_MAX_OUTPUT_TOKENS == 2_000
    assert OPENAI_STRUCTURED_OUTPUTS_STRICT is True
    assert OPENAI_RESPONSE_STORE is False
    assert PROVIDER_GRAPH_CALLS_ENABLED is False


def test_manifest_builder_excludes_secrets_outputs_and_absolute_paths() -> None:
    manifest = build_offline_milestone_manifest(PROJECT_ROOT)
    validate_offline_milestone_manifest(manifest)
    paths = [record["path"] for record in manifest["scope"]["files"]]

    assert ".env" not in paths
    assert all(not path.startswith("/") for path in paths)
    assert all(not path.startswith("outputs/") for path in paths)
    assert all("__pycache__" not in path for path in paths)
    assert "src/rfp_orchestrator/graph_fanout.py" in paths
    assert "tests/test_graph_paths.py" in paths
    assert manifest["verification"]["network_calls_made"] == 0


def test_manifest_validation_rejects_enabled_provider_calls() -> None:
    manifest = build_offline_milestone_manifest(PROJECT_ROOT)
    manifest["generation_profile"]["provider_graph_calls_enabled"] = True

    with pytest.raises(ValueError, match="must remain disabled"):
        validate_offline_milestone_manifest(manifest)


def test_checked_in_artifact_is_valid_and_records_the_phase_two_test_count() -> None:
    manifest = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))

    validate_offline_milestone_manifest(manifest)
    assert manifest["verification"]["pytest"] == "PASS"
    assert manifest["verification"]["test_count"] == EXPECTED_TEST_COUNT
    assert manifest["verification"]["ruff"] == "PASS"
    assert manifest["verification"]["network_blocked"] is True
    assert manifest["verification"]["openai_generation_requests_made"] == 0
    assert manifest["verification"]["pinecone_requests_made"] == 0


def test_artifact_sidecar_matches_the_exact_json_bytes() -> None:
    observed = hashlib.sha256(ARTIFACT_PATH.read_bytes()).hexdigest()
    recorded = DIGEST_PATH.read_text(encoding="utf-8").split()[0]

    assert recorded == observed
