"""Prepare two real offline graph states for Step 3.16 document QA."""

import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from rfp_orchestrator.graph_fanout import build_checkpointed_fanout_graph
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"
QA_DIRECTORY = PROJECT_ROOT / "outputs" / "docx" / "step_3_16_qa"
AUTONOMOUS_STATE_PATH = QA_DIRECTORY / "rfp_001_state.json"
HUMAN_STATE_PATH = QA_DIRECTORY / "rfp_005_human_approved_state.json"


def _graph():
    return build_checkpointed_fanout_graph(
        build_offline_retrievers(KB_DIRECTORY),
        event_clock=lambda: "2026-08-30T14:00:00Z",
        checkpointer=InMemorySaver(),
    )


def _run_autonomous() -> dict:
    requirement = load_sample_requirements()[0]
    graph = _graph()
    return graph.invoke(
        new_requirement_state(
            "step-3-16-qa",
            requirement.requirement_id,
            requirement.text,
        ),
        {"configurable": {"thread_id": "step-3-16-rfp-001"}},
    )


def _run_human_approved() -> dict:
    requirement = load_sample_requirements()[4]
    graph = _graph()
    config = {"configurable": {"thread_id": "step-3-16-rfp-005"}}
    interrupted = graph.invoke(
        new_requirement_state(
            "step-3-16-qa",
            requirement.requirement_id,
            requirement.text,
        ),
        config,
    )
    if "__interrupt__" not in interrupted:
        raise RuntimeError("RFP-005 must stop at the human-review checkpoint")
    proposals = interrupted.get("proposed_commitments", [])
    proposal_ids = [
        item["proposal_id"]
        for item in proposals
        if isinstance(item, dict) and isinstance(item.get("proposal_id"), str)
    ]
    result = graph.invoke(
        Command(
            resume={
                "requirement_id": requirement.requirement_id,
                "decision": "EDIT_AND_APPROVE",
                "reviewer": "proposal-reviewer@northstar.example",
                "timestamp": "2026-08-30T14:05:00Z",
                "edited_answer": (
                    "Northstar offers the documented 99.9% monthly uptime target. "
                    "No 99.99% uptime or service-credit commitment is made."
                ),
                "approved_proposal_ids": proposal_ids,
            }
        ),
        config,
    )
    if result.get("final_status") != "FINALIZED":
        raise RuntimeError("the representative human-approved path must finalize")
    return result


def main() -> None:
    QA_DIRECTORY.mkdir(parents=True, exist_ok=True)
    AUTONOMOUS_STATE_PATH.write_text(
        json.dumps(_run_autonomous(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    HUMAN_STATE_PATH.write_text(
        json.dumps(_run_human_approved(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(AUTONOMOUS_STATE_PATH)
    print(HUMAN_STATE_PATH)


if __name__ == "__main__":
    main()
