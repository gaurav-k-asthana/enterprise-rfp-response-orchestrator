"""Summary-safe Streamlit detail views derived from saved graph state."""

from __future__ import annotations

from typing import Any

import streamlit as st

ANSWER_COLUMNS = ("Specialist", "Support status", "Proposed answer")
CLAIM_COLUMNS = ("Specialist", "Claim ID", "Atomic claim", "Supported", "Citations")
CITATION_COLUMNS = (
    "Evidence ID",
    "Source",
    "Domain",
    "Version",
    "Effective date",
    "Source status",
    "Retrieval",
    "Evidence excerpt",
)
APPROVAL_COLUMNS = (
    "Decision",
    "Reviewer",
    "Timestamp",
    "Review reason",
    "Edited answer",
    "Guidance",
)
TRACE_COLUMNS = ("Step", "Node", "Status", "Timestamp", "Detail")


def _label(value: object, fallback: str = "Not recorded") -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    return value.strip().replace("_", " ").title()


def _text(value: object, fallback: str = "Not recorded") -> str:
    if not isinstance(value, str) or not value.strip():
        return fallback
    return value.strip()


def _excerpt(value: object, limit: int = 240) -> str:
    normalized = " ".join(_text(value, "").split())
    if len(normalized) <= limit:
        return normalized
    return f"{normalized[: limit - 1].rstrip()}…"


def build_proposed_answer_rows(state: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    outputs = state.get("merged_specialist_outputs", [])
    if not isinstance(outputs, list):
        return rows
    for output in outputs:
        if not isinstance(output, dict):
            continue
        rows.append(
            {
                "Specialist": _label(output.get("specialist")),
                "Support status": _label(output.get("support_status")),
                "Proposed answer": _text(output.get("proposed_answer")),
            }
        )
    return rows


def build_claim_rows(state: dict) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    outputs = state.get("merged_specialist_outputs", [])
    if not isinstance(outputs, list):
        return rows
    for output in outputs:
        if not isinstance(output, dict):
            continue
        specialist = _label(output.get("specialist"))
        claims = output.get("claims", [])
        if not isinstance(claims, list):
            continue
        for claim in claims:
            if not isinstance(claim, dict):
                continue
            evidence_ids = claim.get("evidence_ids", [])
            citations = (
                ", ".join(str(item) for item in evidence_ids)
                if isinstance(evidence_ids, list) and evidence_ids
                else "None"
            )
            supported = claim.get("supported")
            rows.append(
                {
                    "Specialist": specialist,
                    "Claim ID": _text(claim.get("claim_id")),
                    "Atomic claim": _text(claim.get("text")),
                    "Supported": (
                        "Yes" if supported is True else "No" if supported is False else "Unknown"
                    ),
                    "Citations": citations,
                }
            )
    return rows


def _cited_evidence_ids(claim_rows: list[dict[str, str]]) -> set[str]:
    return {
        citation.strip()
        for row in claim_rows
        for citation in row["Citations"].split(",")
        if citation.strip() and citation.strip() != "None"
    }


def build_citation_rows(state: dict) -> list[dict[str, str]]:
    cited_ids = _cited_evidence_ids(build_claim_rows(state))
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    evidence = state.get("evidence", [])
    if not isinstance(evidence, list):
        return rows
    for item in evidence:
        if not isinstance(item, dict):
            continue
        evidence_id = _text(item.get("chunk_id"), "")
        if not evidence_id or evidence_id not in cited_ids or evidence_id in seen:
            continue
        seen.add(evidence_id)
        rows.append(
            {
                "Evidence ID": evidence_id,
                "Source": _text(item.get("title")),
                "Domain": _label(item.get("domain")),
                "Version": _text(item.get("version")),
                "Effective date": _text(item.get("effective_date")),
                "Source status": _label(item.get("source_status")),
                "Retrieval": _label(item.get("retrieval_method")),
                "Evidence excerpt": _excerpt(item.get("text")),
            }
        )
    return rows


def build_approval_rows(state: dict) -> list[dict[str, str]]:
    history = state.get("human_decision_history", [])
    raw_records: list[Any] = history if isinstance(history, list) else []
    if not raw_records and isinstance(state.get("approval"), dict):
        raw_records = [state["approval"]]

    rows: list[dict[str, str]] = []
    for record in raw_records:
        if not isinstance(record, dict):
            continue
        rows.append(
            {
                "Decision": _label(record.get("decision")),
                "Reviewer": _text(record.get("reviewer")),
                "Timestamp": _text(record.get("timestamp")),
                "Review reason": _label(record.get("review_reason"), "Not recorded"),
                "Edited answer": _text(record.get("edited_answer"), "None"),
                "Guidance": _text(record.get("guidance"), "None"),
            }
        )
    return rows


def build_trace_rows(state: dict) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    events = state.get("execution_events", [])
    if not isinstance(events, list):
        return rows
    for step, event in enumerate(events, start=1):
        if not isinstance(event, dict):
            continue
        rows.append(
            {
                "Step": step,
                "Node": _label(event.get("node")),
                "Status": _label(event.get("status")),
                "Timestamp": _text(event.get("timestamp")),
                "Detail": _text(event.get("detail"), "None"),
            }
        )
    return rows


def _render_rows(rows: list[dict], columns: tuple[str, ...], empty_message: str) -> None:
    if not rows:
        st.caption(empty_message)
        return
    st.dataframe(
        rows,
        column_order=columns,
        hide_index=True,
        width="stretch",
    )


def render_requirement_details(state: object) -> None:
    """Render the Step 3.5 detail panel only when a saved graph result exists."""

    if not isinstance(state, dict):
        return

    with st.expander("Response, evidence, approval, and trace details", expanded=True):
        st.markdown("#### Proposed specialist answers")
        _render_rows(
            build_proposed_answer_rows(state),
            ANSWER_COLUMNS,
            "No proposed specialist answer was generated for this path.",
        )

        st.markdown("#### Atomic claims")
        _render_rows(
            build_claim_rows(state),
            CLAIM_COLUMNS,
            "No atomic claims were generated for this path.",
        )

        st.markdown("#### Cited evidence")
        _render_rows(
            build_citation_rows(state),
            CITATION_COLUMNS,
            "No cited evidence records are available for this path.",
        )

        st.markdown("#### Approvals and human decisions")
        approval_rows = build_approval_rows(state)
        if state.get("awaiting_human_review") is True and not approval_rows:
            st.warning("Awaiting human review; no decision has been recorded yet.")
        else:
            _render_rows(
                approval_rows,
                APPROVAL_COLUMNS,
                "No human approval was required or recorded for this path.",
            )

        st.markdown("#### Execution trace")
        _render_rows(
            build_trace_rows(state),
            TRACE_COLUMNS,
            "No execution events were recorded for this path.",
        )
