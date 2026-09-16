from copy import deepcopy
from pathlib import Path

import pytest

from rfp_orchestrator.graph_fanout import build_selected_fanout_graph
from rfp_orchestrator.models import Claim, Domain, SpecialistOutput, SupportStatus
from rfp_orchestrator.retrieval import EvidenceChunk, RetrievalMethod
from rfp_orchestrator.specialist_merge import (
    SpecialistMergeError,
    merge_specialist_state,
)
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


def output(domain: Domain, citation_id: str) -> dict:
    return SpecialistOutput(
        specialist=domain,
        claims=[
            Claim(
                claim_id=f"{domain.value}-claim-001",
                text=f"Supported {domain.value} claim.",
                evidence_ids=[citation_id],
                supported=True,
            )
        ],
        proposed_answer=f"Supported {domain.value} answer.",
        support_status=SupportStatus.SUPPORTED,
    ).model_dump(mode="json")


def evidence(domain: Domain, chunk_id: str, score: float = 1.0) -> dict:
    return EvidenceChunk(
        chunk_id=chunk_id,
        doc_id=f"{domain.value.upper()}-DOC",
        domain=domain,
        title=f"{domain.value.title()} Evidence",
        text=f"Supported {domain.value} passage.",
        version="1.0",
        effective_date="2026-08-30",
        authority_rank=5,
        source_status="current",
        score=score,
        retrieval_method=(
            RetrievalMethod.SEMANTIC_SUBSTITUTE
            if domain is Domain.IMPLEMENTATION
            else RetrievalMethod.HYBRID
        ),
        score_components=(
            None
            if domain is Domain.IMPLEMENTATION
            else {
                "lexical_raw": 1.0,
                "semantic_raw": 1.0,
                "lexical_normalized": 1.0,
                "semantic_normalized": 1.0,
                "lexical_weight": 0.6,
                "semantic_weight": 0.4,
            }
        ),
    ).model_dump(mode="json")


def unordered_three_peer_state() -> dict:
    return {
        "selected_specialists": ["implementation", "security", "product"],
        "specialist_outputs": {
            "implementation": output(Domain.IMPLEMENTATION, "impl-1"),
            "security": output(Domain.SECURITY, "sec-1"),
            "product": output(Domain.PRODUCT, "prod-1"),
        },
        "specialist_evidence": {
            "security": [evidence(Domain.SECURITY, "sec-1")],
            "product": [evidence(Domain.PRODUCT, "prod-1")],
            "implementation": [evidence(Domain.IMPLEMENTATION, "impl-1")],
        },
    }


def test_merge_uses_canonical_order_not_selected_or_completion_order() -> None:
    merged = merge_specialist_state(unordered_three_peer_state())

    assert merged["merge_order"] == ["product", "security", "implementation"]
    assert [
        item["specialist"] for item in merged["merged_specialist_outputs"]
    ] == ["product", "security", "implementation"]
    assert [item["domain"] for item in merged["evidence"]] == [
        "product",
        "security",
        "implementation",
    ]


def test_merge_preserves_ranking_inside_each_specialist_branch() -> None:
    state = unordered_three_peer_state()
    state["specialist_evidence"]["product"] = [
        evidence(Domain.PRODUCT, "prod-1", 1.0),
        evidence(Domain.PRODUCT, "prod-2", 0.8),
    ]

    merged = merge_specialist_state(state)

    assert [
        item["chunk_id"]
        for item in merged["evidence"]
        if item["domain"] == "product"
    ] == ["prod-1", "prod-2"]


def test_merge_does_not_mutate_keyed_branch_state() -> None:
    state = unordered_three_peer_state()
    original = deepcopy(state)

    merge_specialist_state(state)

    assert state == original


@pytest.mark.parametrize(
    ("field", "replacement", "message"),
    [
        ("specialist_outputs", {}, "output keys"),
        ("specialist_evidence", {}, "evidence keys"),
        (
            "specialist_outputs",
            {
                "product": output(Domain.PRODUCT, "prod-1"),
                "security": output(Domain.SECURITY, "sec-1"),
                "implementation": output(Domain.IMPLEMENTATION, "impl-1"),
                "unexpected": output(Domain.PRODUCT, "prod-1"),
            },
            "output keys",
        ),
    ],
)
def test_merge_rejects_missing_or_extra_branch_keys(
    field: str,
    replacement: dict,
    message: str,
) -> None:
    state = unordered_three_peer_state()
    state[field] = replacement

    with pytest.raises(SpecialistMergeError, match=message):
        merge_specialist_state(state)


def test_merge_rejects_output_whose_declared_specialist_disagrees_with_key() -> None:
    state = unordered_three_peer_state()
    state["specialist_outputs"]["product"] = output(Domain.SECURITY, "prod-1")

    with pytest.raises(SpecialistMergeError, match="declares specialist"):
        merge_specialist_state(state)


def test_merge_rejects_evidence_from_another_domain() -> None:
    state = unordered_three_peer_state()
    state["specialist_evidence"]["product"] = [
        evidence(Domain.SECURITY, "prod-1")
    ]

    with pytest.raises(SpecialistMergeError, match="another domain"):
        merge_specialist_state(state)


def test_merge_rejects_citation_outside_originating_branch() -> None:
    state = unordered_three_peer_state()
    state["specialist_outputs"]["product"] = output(Domain.PRODUCT, "sec-1")

    with pytest.raises(SpecialistMergeError, match="outside its own branch"):
        merge_specialist_state(state)


def test_merge_rejects_empty_duplicate_or_unknown_selection() -> None:
    state = unordered_three_peer_state()
    state["selected_specialists"] = []
    with pytest.raises(SpecialistMergeError, match="at least one"):
        merge_specialist_state(state)

    state["selected_specialists"] = ["product", "product"]
    with pytest.raises(SpecialistMergeError, match="duplicates"):
        merge_specialist_state(state)

    state["selected_specialists"] = ["unknown"]
    with pytest.raises(SpecialistMergeError, match="unknown domain"):
        merge_specialist_state(state)


def test_live_parallel_graph_exposes_deterministic_merged_views() -> None:
    from rfp_orchestrator.retrieval import build_offline_retrievers

    graph = build_selected_fanout_graph(build_offline_retrievers(KB_DIRECTORY))
    initial = new_requirement_state(
        "case-1",
        "RFP-002",
        (
            "Describe customer-managed encryption keys and identify supported "
            "deployment environments."
        ),
    )

    result = graph.invoke(initial)

    assert result["merge_order"] == ["product", "security"]
    assert [
        item["specialist"] for item in result["merged_specialist_outputs"]
    ] == ["product", "security"]
    assert [item["domain"] for item in result["evidence"]] == sorted(
        [item["domain"] for item in result["evidence"]],
        key={"product": 0, "security": 1, "implementation": 2}.get,
    )


def test_live_single_graph_merges_one_branch() -> None:
    from rfp_orchestrator.retrieval import build_offline_retrievers

    graph = build_selected_fanout_graph(build_offline_retrievers(KB_DIRECTORY))
    initial = new_requirement_state(
        "case-1",
        "RFP-001",
        "Confirm support for SAML 2.0 and SCIM 2.0.",
    )

    result = graph.invoke(initial)

    assert result["merge_order"] == ["product"]
    assert len(result["merged_specialist_outputs"]) == 1
    assert result["evidence"] == result["specialist_evidence"]["product"]


def test_terminal_graph_keeps_merged_views_empty() -> None:
    from rfp_orchestrator.retrieval import build_offline_retrievers

    graph = build_selected_fanout_graph(build_offline_retrievers(KB_DIRECTORY))
    initial = new_requirement_state(
        "case-1",
        "RFP-023",
        "Accept a 20% subscription discount and unlimited indemnity.",
    )

    result = graph.invoke(initial)

    assert result["merge_order"] == []
    assert result["merged_specialist_outputs"] == []
    assert result["evidence"] == []
