from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.commitment_promotion import AuthoritativeCommitment
from rfp_orchestrator.conflict_resolution import (
    ConflictReanalysisAttempt,
    ConflictResolutionError,
    ConflictResolutionStatus,
    conflict_reanalysis_attempt_node,
    conflict_resolution_node,
    plan_conflict_resolution,
)
from rfp_orchestrator.graph_fanout import (
    build_selected_fanout_graph,
    route_conflict_plan,
)
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.models import Domain
from rfp_orchestrator.retrieval import (
    OfflineSpecialistRetrievers,
    SpecialistRetriever,
    build_offline_retrievers,
)
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"


class RecordingRetriever:
    def __init__(self, wrapped: SpecialistRetriever) -> None:
        self._wrapped = wrapped
        self.queries: list[str] = []

    @property
    def domain(self) -> Domain:
        return self._wrapped.domain

    def search(self, query: str, *, k: int = 5):
        self.queries.append(query)
        return self._wrapped.search(query, k=k)


def recording_bundle():
    offline = build_offline_retrievers(KB_DIRECTORY)
    product = RecordingRetriever(offline.product)
    security = RecordingRetriever(offline.security)
    implementation = RecordingRetriever(offline.implementation)
    return (
        OfflineSpecialistRetrievers(
            product=product,
            security=security,
            implementation=implementation,
        ),
        {
            "product": product,
            "security": security,
            "implementation": implementation,
        },
    )


def graph(retrievers=None):
    return build_selected_fanout_graph(
        retrievers or build_offline_retrievers(KB_DIRECTORY),
        event_clock=lambda: "fixed",
    )


def invoke(requirement_id: str, text: str, *, retrievers=None, commitments=None):
    state = new_requirement_state("case-1", requirement_id, text)
    if commitments is not None:
        state["commitments"] = commitments
    return graph(retrievers).invoke(state)


def retention_state(*, retrievers=None):
    return invoke(
        "RFP-014",
        (
            "State exactly how many calendar days customer content is retained after "
            "contract termination."
        ),
        retrievers=retrievers,
    )


def saml_state(*, commitments=None, retrievers=None):
    return invoke(
        "RFP-001",
        "Confirm support for SAML 2.0 and SCIM 2.0.",
        retrievers=retrievers,
        commitments=commitments,
    )


def prior_saml_with_smaller_scope() -> dict:
    draft = saml_state()
    proposal = draft["proposed_commitments"][0]
    return AuthoritativeCommitment(
        proposal_id="prior-saml",
        commitment_type=proposal["commitment_type"],
        normalized_value="saml-2.0:ga:enterprise-cloud",
        source_requirement_id="RFP-PRIOR",
        source_claim_id="prior-claim",
        specialist="product",
        evidence_ids=["prior-evidence"],
        approval_decision="APPROVE",
        approved_by="prior-reviewer@example.test",
        approved_at="2026-08-29T12:00:00Z",
    ).model_dump(mode="json")


def test_retention_conflict_executes_one_security_reanalysis_then_needs_human() -> None:
    bundle, recorders = recording_bundle()

    state = retention_state(retrievers=bundle)

    assert state["conflict_reanalysis_count"] == 1
    assert len(state["conflict_resolution_attempts"]) == 1
    assert state["conflict_unresolved"] is True
    assert state["strategy"] == "IMMEDIATE_HITL"
    assert state["selected_specialists"] == []
    assert state["final_status"] == "NEEDS_HUMAN"
    assert state["final_answer"] is None
    assert state["commitment_promotion"] is None
    assert len(recorders["security"].queries) == 2
    assert recorders["product"].queries == []
    assert recorders["implementation"].queries == []


def test_reanalysis_uses_the_exact_saved_conflict_query() -> None:
    bundle, recorders = recording_bundle()

    state = retention_state(retrievers=bundle)
    attempt = state["conflict_resolution_attempts"][0]

    assert recorders["security"].queries[1] == attempt["queries"]["security"]
    assert "Conflict reanalysis:" in recorders["security"].queries[1]
    assert "30-calendar-days" in recorders["security"].queries[1]
    assert "90-calendar-days" in recorders["security"].queries[1]


def test_unresolved_state_preserves_conflict_ids_and_values_for_human_review() -> None:
    state = retention_state()

    assert state["unresolved_conflict_ids"] == [
        "commitment-current:RETENTION_PERIOD:customer-content-post-termination"
    ]
    assert state["conflicts"][0]["proposed_values"] == [
        "post-termination:30-calendar-days",
        "post-termination-recovery:90-calendar-days",
    ]
    assert state["conflict_resolution"]["status"] == (
        "UNRESOLVED_NEEDS_HUMAN"
    )


def test_conflict_trace_repeats_all_validation_gates_but_never_promotes() -> None:
    state = retention_state()
    nodes = [item["node"] for item in state["execution_events"]]

    for node in (
        GraphNode.SECURITY_SPECIALIST.value,
        GraphNode.MERGE.value,
        GraphNode.CITATION_VALIDATION.value,
        GraphNode.SOURCE_VALIDATION.value,
        GraphNode.CLAIM_SUPPORT_VALIDATION.value,
        GraphNode.RECOVERY_PLANNING.value,
        GraphNode.COMMITMENT_LEDGER.value,
        GraphNode.COMMITMENT_CONSISTENCY.value,
        GraphNode.CONFLICT_RESOLUTION.value,
    ):
        assert sum(
            item["node"] == node and item["status"] == "complete"
            for item in state["execution_events"]
        ) == 2
    assert GraphNode.COMMITMENT_PROMOTION.value not in nodes


def test_conflict_attempt_emits_one_recovery_and_complete_pair() -> None:
    state = retention_state()
    statuses = [
        item["status"]
        for item in state["execution_events"]
        if item["node"] == GraphNode.CONFLICT_REANALYSIS_ATTEMPT.value
    ]

    assert statuses == ["recovery", "complete"]


def test_consistent_path_skips_reanalysis_and_reaches_promotion_gate() -> None:
    bundle, recorders = recording_bundle()

    state = saml_state(retrievers=bundle)
    nodes = [item["node"] for item in state["execution_events"]]

    assert state["conflict_resolution"]["status"] == "NOT_NEEDED"
    assert state["conflict_reanalysis_count"] == 0
    assert state["conflict_resolution_attempts"] == []
    assert state["conflict_unresolved"] is False
    assert state["commitment_promotion"]["status"] == "NO_SELECTION"
    assert GraphNode.CONFLICT_REANALYSIS_ATTEMPT.value not in nodes
    assert len(recorders["product"].queries) == 1


def test_prior_authoritative_conflict_targets_only_product_once() -> None:
    bundle, recorders = recording_bundle()

    state = saml_state(
        commitments=[prior_saml_with_smaller_scope()],
        retrievers=bundle,
    )

    assert state["conflict_unresolved"] is True
    assert state["conflict_resolution_attempts"][0]["specialists"] == ["product"]
    assert len(recorders["product"].queries) == 2
    assert recorders["security"].queries == []
    assert recorders["implementation"].queries == []


def test_conflict_reanalysis_does_not_consume_retrieval_retry_budget() -> None:
    state = retention_state()

    assert state["conflict_reanalysis_count"] == 1
    assert state["retry_count"] == 0
    assert state["recovery_attempts"] == []


def test_resolved_consistency_after_one_attempt_routes_to_promotion() -> None:
    state = saml_state()
    state["conflict_reanalysis_count"] = 1

    update = conflict_resolution_node(state)
    state.update(update)

    assert update["conflict_resolution"]["status"] == "NOT_NEEDED"
    assert update["conflict_reanalysis_needed"] is False
    assert update["conflict_unresolved"] is False
    assert route_conflict_plan(state) == GraphNode.RISK_AUTHORITY.value


def test_first_conflict_plan_targets_affected_specialist_and_builds_one_query() -> None:
    state = retention_state()
    state["conflict_reanalysis_count"] = 0

    plan = plan_conflict_resolution(state)

    assert plan.status is ConflictResolutionStatus.REANALYSIS_REQUIRED
    assert plan.specialists == [Domain.SECURITY]
    assert set(plan.queries) == {"security"}
    assert len(plan.queries["security"].reanalysis_query) <= 800


def test_conflict_plan_and_query_are_repeatable() -> None:
    state = retention_state()
    state["conflict_reanalysis_count"] = 0

    first = plan_conflict_resolution(state)
    second = plan_conflict_resolution(deepcopy(state))

    assert first == second


@pytest.mark.parametrize("invalid_count", [-1, 2, True, "1"])
def test_invalid_conflict_reanalysis_count_fails_closed(invalid_count) -> None:
    state = saml_state()
    state["conflict_reanalysis_count"] = invalid_count

    with pytest.raises(ConflictResolutionError, match="count"):
        plan_conflict_resolution(state)


def test_missing_or_malformed_consistency_state_fails_closed() -> None:
    missing = new_requirement_state("case-1", "RFP-X", "Test requirement.")
    malformed = saml_state()
    malformed["commitment_consistency"] = {"consistent": False}

    with pytest.raises(ConflictResolutionError, match="missing"):
        plan_conflict_resolution(missing)
    with pytest.raises(ConflictResolutionError, match="malformed"):
        plan_conflict_resolution(malformed)


def test_conflict_reference_to_unknown_proposal_fails_closed() -> None:
    state = retention_state()
    state["commitment_consistency"]["conflicts"][0]["proposal_ids"] = [
        "unknown-proposal"
    ]

    with pytest.raises(ConflictResolutionError, match="unknown proposal"):
        plan_conflict_resolution(state)


def test_attempt_node_snapshots_one_round_and_refuses_a_second() -> None:
    state = retention_state()
    attempt = state["conflict_resolution_attempts"][0]
    direct = new_requirement_state("case-1", "RFP-X", "Retention conflict.")
    direct.update(
        {
            "strategy": "TARGETED_CONFLICT_RESOLUTION",
            "selected_specialists": ["security"],
            "target_conflict_ids": attempt["conflict_ids"],
            "conflict_reanalysis_queries": {
                "security": {
                    "reanalysis_query": attempt["queries"]["security"]
                }
            },
        }
    )

    first = conflict_reanalysis_attempt_node(direct)
    direct.update(first)

    assert direct["conflict_reanalysis_count"] == 1
    assert direct["conflict_resolution_attempts"][0] == attempt
    with pytest.raises(ConflictResolutionError, match="only one"):
        conflict_reanalysis_attempt_node(direct)


def test_attempt_requires_targeted_strategy_queries_specialists_and_conflicts() -> None:
    base = new_requirement_state("case-1", "RFP-X", "Conflict.")
    with pytest.raises(ConflictResolutionError, match="strategy"):
        conflict_reanalysis_attempt_node(base)

    base["strategy"] = "TARGETED_CONFLICT_RESOLUTION"
    with pytest.raises(ValidationError):
        conflict_reanalysis_attempt_node(base)


def test_attempt_model_permits_only_one() -> None:
    with pytest.raises(ValidationError):
        ConflictReanalysisAttempt(
            attempt_number=2,
            specialists=[Domain.SECURITY],
            conflict_ids=["conflict-1"],
            queries={"security": "Focused query"},
        )


def test_route_conflict_plan_has_three_explicit_outcomes() -> None:
    state = new_requirement_state("case-1", "RFP-X", "Conflict.")
    state["conflict_reanalysis_needed"] = True
    assert route_conflict_plan(state) == GraphNode.STRATEGY_ORCHESTRATOR.value

    state["conflict_reanalysis_needed"] = False
    state["conflict_unresolved"] = True
    assert route_conflict_plan(state) == "__end__"

    state["conflict_unresolved"] = False
    assert route_conflict_plan(state) == GraphNode.RISK_AUTHORITY.value


def test_unresolved_conflict_never_changes_authoritative_memory() -> None:
    prior = prior_saml_with_smaller_scope()
    state = saml_state(commitments=[prior])

    assert state["commitments"] == [prior]
    assert state["commitment_promotion"] is None
    assert state["final_answer"] is None


def test_reanalysis_topology_still_has_no_specialist_to_specialist_edges() -> None:
    edges = {
        (edge.source, edge.target)
        for edge in graph().get_graph().edges
    }
    specialist_nodes = {
        GraphNode.PRODUCT_SPECIALIST.value,
        GraphNode.SECURITY_SPECIALIST.value,
        GraphNode.IMPLEMENTATION_SPECIALIST.value,
    }

    assert not {
        (source, target)
        for source, target in edges
        if source in specialist_nodes and target in specialist_nodes
    }
