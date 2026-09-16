"""Deterministic Step 2.9 merge of keyed peer-specialist branch state."""

from __future__ import annotations

from rfp_orchestrator.models import Domain, SpecialistOutput
from rfp_orchestrator.retrieval import EvidenceChunk
from rfp_orchestrator.state import GraphState

SPECIALIST_MERGE_ORDER = (
    Domain.PRODUCT,
    Domain.SECURITY,
    Domain.IMPLEMENTATION,
)


class SpecialistMergeError(ValueError):
    """Raised when branch results cannot be merged without losing provenance."""


def merge_specialist_state(state: GraphState) -> GraphState:
    """Validate keyed branches and return stable output and evidence lists."""

    try:
        selected_values = (
            state.get("initial_specialists") or state.get("selected_specialists", [])
        )
        selected = [Domain(value) for value in selected_values]
    except ValueError as error:
        raise SpecialistMergeError("selected_specialists contains an unknown domain") from error
    if not selected:
        raise SpecialistMergeError("merge requires at least one selected specialist")
    if len(selected) != len(set(selected)):
        raise SpecialistMergeError("selected_specialists cannot contain duplicates")

    raw_outputs = state.get("specialist_outputs", {})
    raw_evidence = state.get("specialist_evidence", {})
    selected_keys = {domain.value for domain in selected}
    output_keys = set(raw_outputs)
    evidence_keys = set(raw_evidence)
    if output_keys != selected_keys:
        raise SpecialistMergeError(
            "specialist output keys must exactly match selected specialists"
        )
    if evidence_keys != selected_keys:
        raise SpecialistMergeError(
            "specialist evidence keys must exactly match selected specialists"
        )

    merged_outputs: list[dict] = []
    flattened_evidence: list[dict] = []
    merge_order: list[str] = []
    for domain in SPECIALIST_MERGE_ORDER:
        key = domain.value
        if key not in selected_keys:
            continue

        output = SpecialistOutput.model_validate(raw_outputs[key])
        if output.specialist is not domain:
            raise SpecialistMergeError(
                f"{key} output declares specialist '{output.specialist.value}'"
            )
        evidence = [EvidenceChunk.model_validate(item) for item in raw_evidence[key]]
        if any(item.domain is not domain for item in evidence):
            raise SpecialistMergeError(f"{key} evidence contains another domain")

        branch_evidence_ids = {item.chunk_id for item in evidence}
        if any(
            citation_id not in branch_evidence_ids
            for claim in output.claims
            for citation_id in claim.evidence_ids
        ):
            raise SpecialistMergeError(
                f"{key} output cites evidence outside its own branch"
            )

        merge_order.append(key)
        merged_outputs.append(output.model_dump(mode="json"))
        flattened_evidence.extend(item.model_dump(mode="json") for item in evidence)

    return {
        "merged_specialist_outputs": merged_outputs,
        "merge_order": merge_order,
        "evidence": flattened_evidence,
    }
