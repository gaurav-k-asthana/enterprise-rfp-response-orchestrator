"""Step 5.9: frozen demo selection stays tied to gold and the offline graph."""

import hashlib
import json
from pathlib import Path

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from rfp_orchestrator.evaluation_schema import load_evaluation_dataset
from rfp_orchestrator.graph_fanout import build_checkpointed_fanout_graph
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.state import new_requirement_state

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "fixtures" / "demo_cases_v1.json"
PATH_ORDER = ("simple", "cross_domain", "recovery", "contradiction", "authority_risk")
REQUIREMENT_ORDER = ("RFP-001", "RFP-002", "RFP-021", "RFP-014", "RFP-005")


def _manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_frozen_demo_manifest_is_exactly_five_and_source_bound() -> None:
    manifest = _manifest()

    assert manifest["schema_version"] == "1.0"
    assert manifest["status"] == "FROZEN"
    assert manifest["execution_mode"] == "offline_synthetic"
    assert tuple(case["path"] for case in manifest["cases"]) == PATH_ORDER
    assert tuple(case["requirement_id"] for case in manifest["cases"]) == REQUIREMENT_ORDER
    assert len({case["case_id"] for case in manifest["cases"]}) == 5
    for source, expected_hash in manifest["source_sha256"].items():
        assert hashlib.sha256((ROOT / source).read_bytes()).hexdigest() == expected_hash


def test_demo_cases_match_reviewed_gold_and_sample_text() -> None:
    dataset = load_evaluation_dataset()
    gold_by_id = {case.case_id: case for case in dataset.cases}
    sample_by_id = {
        requirement.requirement_id: requirement.text
        for requirement in load_sample_requirements()
    }

    for demo in _manifest()["cases"]:
        gold = gold_by_id[demo["case_id"]]
        labels = gold.gold_labels
        assert gold.requirement_id == demo["requirement_id"]
        assert gold.untrusted_rfp_text == demo["requirement_text"]
        assert sample_by_id[demo["requirement_id"]] == demo["requirement_text"]
        assert labels.expected_strategy_family.value == demo["expected_strategy_family"]
        assert [domain.value for domain in labels.expected_specialists] == demo[
            "expected_specialists"
        ]
        assert demo["expected_status"] in [
            status.value for status in labels.allowed_final_statuses
        ]


@pytest.mark.parametrize("index", range(5))
def test_frozen_case_matches_real_checkpointed_offline_path(index: int) -> None:
    demo = _manifest()["cases"][index]
    graph = build_checkpointed_fanout_graph(
        build_offline_retrievers(ROOT / "data" / "kb"),
        checkpointer=InMemorySaver(),
        event_clock=lambda: "fixed",
    )
    state = graph.invoke(
        new_requirement_state(
            "demo-step-5-9", demo["requirement_id"], demo["requirement_text"]
        ),
        {"configurable": {"thread_id": f"demo-5-9-{index}"}},
    )

    assert state["initial_specialists"] == demo["expected_specialists"]
    assert state["strategy"] == demo["expected_terminal_strategy"]
    assert state["final_status"] == demo["expected_status"]
    assert state["retry_count"] == demo["expected_retries"]
    assert state["conflict_reanalysis_count"] == demo[
        "expected_conflict_reanalyses"
    ]
    assert bool(state["final_answer"]) is demo["expected_final_answer"]
    if demo["expected_review_reason"] is None:
        assert "__interrupt__" not in state
        assert state["human_review_request"] is None
        assert state["finalization_passed"] is True
    else:
        assert "__interrupt__" in state
        assert state["human_review_request"]["reason"] == demo[
            "expected_review_reason"
        ]
        assert state["commitment_promotion"] is None
