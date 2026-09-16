"""Lightweight Streamlit application shell and local run controls."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import sleep
from typing import Any
from uuid import uuid4

import streamlit as st
from langgraph.types import Command

from rfp_orchestrator.architecture_map import render_architecture_html
from rfp_orchestrator.attempt_counters import (
    apply_attempt_event,
    initial_attempt_counts,
    validate_attempt_counts,
)
from rfp_orchestrator.docx_export import (
    DocxExportError,
    generate_basic_response_docx,
)
from rfp_orchestrator.edge_status import (
    initial_edge_status,
    reduce_edge_status,
    validate_edge_status,
)
from rfp_orchestrator.graph_fanout import build_checkpointed_fanout_graph
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.human_review import HumanReviewDecision
from rfp_orchestrator.human_review_ui import (
    REVIEW_SESSION_KEYS,
    SESSION_REVIEW_DECISION_DRAFT,
    clear_review_draft,
    render_human_review_controls,
)
from rfp_orchestrator.node_status import (
    SPECIALIST_NODE_BY_DOMAIN,
    apply_node_event,
    initial_node_status,
    validate_node_status,
    validate_unselected_specialists_inactive,
)
from rfp_orchestrator.retrieval import build_offline_retrievers
from rfp_orchestrator.safety import SAFETY_NOTICE_BODY, SAFETY_NOTICE_TITLE
from rfp_orchestrator.sample_requirements import (
    DEFAULT_SAMPLE_RFP_PATH,
    SampleRequirement,
    load_sample_requirements,
    requirement_by_id,
)
from rfp_orchestrator.state import new_requirement_state
from rfp_orchestrator.ui_details import render_requirement_details
from rfp_orchestrator.ui_feedback import (
    UiFailureKind,
    failure_markdown,
    render_ui_failure,
)

APP_TITLE = "Enterprise RFP Response Orchestrator"
APP_ICON = "📄"
APP_SUBTITLE = "Evidence-grounded, risk-aware response workflow"
KB_DIRECTORY = DEFAULT_SAMPLE_RFP_PATH.parent / "kb"
SESSION_RUN_COUNT = "run_count"
SESSION_LATEST_STATE = "latest_run_state"
SESSION_LATEST_THREAD = "latest_thread_id"
SESSION_LATEST_REQUIREMENT = "latest_requirement_id"
SESSION_INSTANCE_ID = "ui_session_id"
SESSION_NODE_STATUS = "node_status"
SESSION_EDGE_STATUS = "edge_status"
SESSION_ATTEMPT_COUNTS = "attempt_counts"
SESSION_EVENT_COUNT = "event_count"
SESSION_VISUALIZATION_FAILED = "visualization_failed"
SESSION_RESUME_NOTICE = "resume_notice"
LIVE_EVENT_DWELL_SECONDS = 0.08
MAP_ERROR_MESSAGE = failure_markdown(UiFailureKind.MAP)
DOCX_MIME_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
RUN_SESSION_KEYS = (
    SESSION_LATEST_STATE,
    SESSION_LATEST_THREAD,
    SESSION_LATEST_REQUIREMENT,
    SESSION_NODE_STATUS,
    SESSION_EDGE_STATUS,
    SESSION_ATTEMPT_COUNTS,
    SESSION_EVENT_COUNT,
    SESSION_VISUALIZATION_FAILED,
    SESSION_RESUME_NOTICE,
    *REVIEW_SESSION_KEYS,
)

StreamEventCallback = Callable[
    [
        dict[str, str],
        dict[tuple[str, str], str],
        dict[str, int],
        dict[str, Any],
    ],
    None,
]


@dataclass(frozen=True)
class StreamedRun:
    state: dict[str, Any]
    thread_id: str
    node_status: dict[str, str]
    edge_status: dict[tuple[str, str], str]
    attempt_counts: dict[str, int]
    event_count: int
    visualization_failed: bool


@dataclass(frozen=True)
class DocxDownloadArtifact:
    """One validated in-memory document offered by the local Streamlit page."""

    data: bytes
    file_name: str
    mime_type: str = DOCX_MIME_TYPE


class HumanReviewResumeError(ValueError):
    """Raised when the UI cannot safely bind a draft to one saved checkpoint."""


RESULT_COLUMNS = (
    "Requirement",
    "Strategy",
    "Selected specialists",
    "Evidence state",
    "Risk",
    "Final status",
)


def configure_page() -> None:
    """Apply the one-time browser-tab and layout configuration."""

    st.set_page_config(
        page_title=APP_TITLE,
        page_icon=APP_ICON,
        layout="wide",
        initial_sidebar_state="expanded",
    )


@st.cache_data
def get_sample_requirements() -> tuple[SampleRequirement, ...]:
    """Load the validated synthetic selector options once per app process."""

    return load_sample_requirements()


@st.cache_resource
def get_ui_graph():
    """Build one process-local checkpointed graph without provider clients."""

    retrievers = build_offline_retrievers(KB_DIRECTORY)
    return build_checkpointed_fanout_graph(retrievers)


def run_sample_requirement(
    requirement: SampleRequirement,
    run_number: int,
    session_id: str | None = None,
) -> tuple[dict, str]:
    """Run one selected requirement and return its saved graph state and thread ID."""

    streamed = stream_sample_requirement(requirement, run_number, session_id)
    return streamed.state, streamed.thread_id


def stream_sample_requirement(
    requirement: SampleRequirement,
    run_number: int,
    session_id: str | None = None,
    *,
    on_event: StreamEventCallback | None = None,
) -> StreamedRun:
    """Stream one graph run, reducing each custom event for the live map."""

    session_id = session_id or uuid4().hex[:12]
    thread_id = f"ui-{session_id}-{run_number:04d}-{requirement.requirement_id.lower()}"
    node_status = initial_node_status()
    edge_status = initial_edge_status()
    attempt_counts = initial_attempt_counts()
    streamed_events: list[dict[str, Any]] = []
    selected_specialists_seen: list[object] = []
    final_state: dict[str, Any] | None = None
    event_count = 0
    callback_enabled = on_event is not None
    visualization_failed = False
    stream = get_ui_graph().stream(
        new_requirement_state(
            "ui-sample-rfp",
            requirement.requirement_id,
            requirement.text,
        ),
        {"configurable": {"thread_id": thread_id}},
        stream_mode=["custom", "values"],
    )
    for mode, chunk in stream:
        if mode == "custom":
            if not isinstance(chunk, Mapping):
                raise TypeError("graph custom stream must contain mapping events")
            event = dict(chunk)
            node_status = apply_node_event(node_status, event)
            attempt_counts = apply_attempt_event(attempt_counts, event)
            validate_unselected_specialists_inactive(
                node_status,
                selected_specialists_seen,
            )
            streamed_events.append(dict(event))
            edge_status = reduce_edge_status(streamed_events)
            event_count += 1
            if callback_enabled and on_event is not None:
                try:
                    on_event(
                        dict(node_status),
                        dict(edge_status),
                        dict(attempt_counts),
                        dict(event),
                    )
                except Exception:  # noqa: BLE001 - visualization isolation boundary
                    visualization_failed = True
                    callback_enabled = False
        elif mode == "values":
            if not isinstance(chunk, Mapping):
                raise TypeError("graph values stream must contain mapping chunks")
            final_state = dict(chunk)
            selected_specialists = chunk.get("selected_specialists", [])
            if not isinstance(selected_specialists, list):
                raise TypeError("graph selected specialists must be a list")
            for specialist in selected_specialists:
                if specialist not in selected_specialists_seen:
                    selected_specialists_seen.append(specialist)
            validate_unselected_specialists_inactive(
                node_status,
                selected_specialists_seen,
            )

    if final_state is None:
        raise RuntimeError("graph stream ended without a final state")
    return StreamedRun(
        state=final_state,
        thread_id=thread_id,
        node_status=node_status,
        edge_status=edge_status,
        attempt_counts=attempt_counts,
        event_count=event_count,
        visualization_failed=visualization_failed,
    )


def _selected_specialists_from_status(
    node_status: Mapping[str, str],
) -> list[str]:
    return [
        domain
        for domain, node in SPECIALIST_NODE_BY_DOMAIN.items()
        if node_status[node] != "inactive"
    ]


def stream_human_review_decision(
    previous: StreamedRun,
    raw_decision: object,
    *,
    on_event: StreamEventCallback | None = None,
) -> StreamedRun:
    """Resume exactly one saved checkpoint and reduce only its real graph events."""

    try:
        decision = HumanReviewDecision.model_validate(raw_decision)
    except (TypeError, ValueError) as error:
        raise HumanReviewResumeError("saved human-review decision is invalid") from error
    if not previous.thread_id.strip():
        raise HumanReviewResumeError("saved checkpoint thread is missing")
    if previous.state.get("awaiting_human_review") is not True:
        raise HumanReviewResumeError("saved requirement is not awaiting human review")
    if previous.state.get("requirement_id") != decision.requirement_id:
        raise HumanReviewResumeError(
            "saved decision does not belong to the current requirement"
        )

    validate_node_status(previous.node_status)
    validate_edge_status(previous.edge_status)
    validate_attempt_counts(previous.attempt_counts)
    selected_specialists_seen = _selected_specialists_from_status(
        previous.node_status
    )
    validate_unselected_specialists_inactive(
        previous.node_status,
        selected_specialists_seen,
    )

    raw_events = previous.state.get("execution_events", [])
    if not isinstance(raw_events, list) or any(
        not isinstance(event, Mapping) for event in raw_events
    ):
        raise HumanReviewResumeError("saved execution history is malformed")
    streamed_events = [dict(event) for event in raw_events]

    graph = get_ui_graph()
    config = {"configurable": {"thread_id": previous.thread_id}}
    snapshot = graph.get_state(config)
    checkpoint = dict(snapshot.values)
    if snapshot.next != (GraphNode.HUMAN_REVIEW_INTERRUPT.value,):
        raise HumanReviewResumeError("saved checkpoint is not at human review")
    for field in (
        "requirement_id",
        "human_review_request",
        "human_decision_history",
    ):
        if checkpoint.get(field) != previous.state.get(field):
            raise HumanReviewResumeError("saved checkpoint changed after this draft")

    node_status = dict(previous.node_status)
    edge_status = dict(previous.edge_status)
    attempt_counts = dict(previous.attempt_counts)
    final_state: dict[str, Any] | None = None
    resumed_event_count = 0
    callback_enabled = on_event is not None
    visualization_failed = False
    stream = graph.stream(
        Command(resume=decision.model_dump(mode="json", exclude_none=True)),
        config,
        stream_mode=["custom", "values"],
    )
    for mode, chunk in stream:
        if mode == "custom":
            if not isinstance(chunk, Mapping):
                raise TypeError("graph custom stream must contain mapping events")
            event = dict(chunk)
            node_status = apply_node_event(node_status, event)
            attempt_counts = apply_attempt_event(attempt_counts, event)
            streamed_events.append(dict(event))
            edge_status = reduce_edge_status(streamed_events)
            resumed_event_count += 1
            validate_unselected_specialists_inactive(
                node_status,
                selected_specialists_seen,
            )
            if callback_enabled and on_event is not None:
                try:
                    on_event(
                        dict(node_status),
                        dict(edge_status),
                        dict(attempt_counts),
                        dict(event),
                    )
                except Exception:  # noqa: BLE001 - visualization isolation boundary
                    visualization_failed = True
                    callback_enabled = False
        elif mode == "values":
            if not isinstance(chunk, Mapping):
                raise TypeError("graph values stream must contain mapping chunks")
            final_state = dict(chunk)
            selected_specialists = chunk.get("selected_specialists", [])
            if not isinstance(selected_specialists, list):
                raise TypeError("graph selected specialists must be a list")
            for specialist in selected_specialists:
                if specialist not in selected_specialists_seen:
                    selected_specialists_seen.append(specialist)
            validate_unselected_specialists_inactive(
                node_status,
                selected_specialists_seen,
            )

    if final_state is None:
        raise RuntimeError("graph resume stream ended without a final state")
    return StreamedRun(
        state=final_state,
        thread_id=previous.thread_id,
        node_status=node_status,
        edge_status=edge_status,
        attempt_counts=attempt_counts,
        event_count=previous.event_count + resumed_event_count,
        visualization_failed=visualization_failed,
    )


def clear_current_run(session_state: Any) -> None:
    """Clear only the latest UI run pointers, preserving the run counter."""

    for key in RUN_SESSION_KEYS:
        session_state.pop(key, None)


def render_safety_notice() -> None:
    """Render the persistent Step 3.3 demonstration and authority warning."""

    st.warning(
        f"**{SAFETY_NOTICE_TITLE}**\n\n{SAFETY_NOTICE_BODY}",
        icon="⚠️",
    )


def _display_label(value: object, fallback: str) -> str:
    """Convert an internal enum-style value into a compact UI label."""

    if not isinstance(value, str) or not value.strip():
        return fallback
    return value.strip().replace("_", " ").title()


def evidence_state_label(state: dict) -> str:
    """Summarize evidence support and validation without exposing claim details."""

    if state.get("recovery_exhausted") is True:
        return "Recovery exhausted"
    if state.get("recovery_needed") is True:
        return "Recovery required"

    validation_flags = (
        state.get("citation_valid"),
        state.get("source_metadata_valid"),
        state.get("claim_support_valid"),
    )
    if any(flag is False for flag in validation_flags):
        return "Validation failed"

    outputs = state.get("merged_specialist_outputs", [])
    if not isinstance(outputs, list) or not outputs:
        return "Not evaluated"
    statuses = [
        output.get("support_status")
        for output in outputs
        if isinstance(output, dict)
    ]
    if len(statuses) != len(outputs):
        return "Unknown"
    if all(status == "SUPPORTED" for status in statuses):
        if all(flag is True for flag in validation_flags):
            return "Supported / Validated"
        return "Supported / Checks pending"
    if all(status == "UNSUPPORTED" for status in statuses):
        return "Unsupported"
    if all(status in {"SUPPORTED", "PARTIAL", "UNSUPPORTED"} for status in statuses):
        return "Partial"
    return "Unknown"


def build_requirement_result_row(state: dict) -> dict[str, str]:
    """Create the stable, summary-only Step 3.4 row from saved graph state."""

    requirement_id = state.get("requirement_id")
    requirement_text = state.get("original_text")
    if isinstance(requirement_id, str) and isinstance(requirement_text, str):
        requirement = f"{requirement_id} — {requirement_text}"
    else:
        requirement = "Unknown requirement"

    raw_specialists = state.get("selected_specialists", [])
    if isinstance(raw_specialists, list) and raw_specialists:
        specialists = ", ".join(
            _display_label(specialist, "Unknown") for specialist in raw_specialists
        )
    else:
        specialists = "None"

    raw_risks = state.get("risk_classes", [])
    if isinstance(raw_risks, list) and raw_risks:
        risks = ", ".join(_display_label(risk, "Unknown") for risk in raw_risks)
    else:
        risks = "None detected"

    return {
        "Requirement": requirement,
        "Strategy": _display_label(state.get("strategy"), "Not selected"),
        "Selected specialists": specialists,
        "Evidence state": evidence_state_label(state),
        "Risk": risks,
        "Final status": _display_label(state.get("final_status"), "In progress"),
    }


def render_requirement_table() -> None:
    """Render one summary row for the current saved requirement, when present."""

    st.subheader("Requirement result")
    state = st.session_state.get(SESSION_LATEST_STATE)
    if not isinstance(state, dict):
        st.info("Run a sample requirement to see its result summary.")
        return

    st.dataframe(
        [build_requirement_result_row(state)],
        column_order=RESULT_COLUMNS,
        hide_index=True,
        width="stretch",
    )


def build_docx_download(state: object) -> DocxDownloadArtifact:
    """Build deterministic download bytes and a safe requirement-specific name."""

    if not isinstance(state, Mapping):
        raise DocxExportError("DOCX download requires saved requirement state")
    raw_requirement_id = state.get("requirement_id")
    if not isinstance(raw_requirement_id, str) or not raw_requirement_id.strip():
        raise DocxExportError("DOCX download requires a requirement ID")
    safe_requirement_id = re.sub(
        r"[^a-z0-9]+",
        "-",
        raw_requirement_id.strip().lower(),
    ).strip("-")
    if not safe_requirement_id:
        raise DocxExportError("DOCX download requires a filename-safe requirement ID")
    return DocxDownloadArtifact(
        data=generate_basic_response_docx(state),
        file_name=f"northstar-rfp-response-{safe_requirement_id}.docx",
    )


def render_docx_download(state: object) -> None:
    """Render the Step 3.17 download control without mutating saved state."""

    st.subheader("Download response")
    if not isinstance(state, Mapping):
        st.info("Run a sample requirement to prepare its DOCX response.")
        return
    try:
        artifact = build_docx_download(state)
    except Exception:  # noqa: BLE001 - hide saved-state internals at the UI boundary
        render_ui_failure(UiFailureKind.DOCX_EXPORT, target=st)
        return
    st.download_button(
        "Download DOCX response",
        data=artifact.data,
        file_name=artifact.file_name,
        mime=artifact.mime_type,
        type="primary",
        width="stretch",
    )
    st.caption(
        "Built locally from the current saved result. Downloading does not rerun "
        "the workflow or call an external service."
    )


def _render_architecture_frame(
    target: Any,
    status: dict[str, str],
    *,
    edge_status: dict[tuple[str, str], str] | None = None,
    attempt_counts: dict[str, int] | None = None,
    live_node: str | None = None,
) -> bool:
    """Render one frame; replace failures with a safe, graph-independent notice."""

    try:
        target.iframe(
            render_architecture_html(
                status,
                edge_status=edge_status,
                attempt_counts=attempt_counts,
                live_node=live_node,
            ),
            height="content",
        )
    except Exception:  # noqa: BLE001 - visualization isolation boundary
        target.warning(MAP_ERROR_MESSAGE, icon="⚠️")
        return False
    return True


def render_architecture_map() -> Any:
    """Render the map shell and return its replaceable live-event target."""

    st.subheader("Architecture execution map")
    st.caption(
        "Colors update from LangGraph events as each node runs. Devices requesting "
        "reduced motion receive the same status changes without transitions."
    )
    status = st.session_state.get(SESSION_NODE_STATUS)
    if not isinstance(status, dict):
        status = initial_node_status()
    edge_status = st.session_state.get(SESSION_EDGE_STATUS)
    if not isinstance(edge_status, dict):
        edge_status = initial_edge_status()
    attempt_counts = st.session_state.get(SESSION_ATTEMPT_COUNTS)
    if not isinstance(attempt_counts, dict):
        attempt_counts = initial_attempt_counts()
    target = st.empty()
    _render_architecture_frame(
        target,
        status,
        edge_status=edge_status,
        attempt_counts=attempt_counts,
    )
    return target


def _restore_saved_architecture_frame(target: Any, session_state: Any) -> None:
    """Replace a partial failed-run frame with the last saved safe snapshot."""

    status = session_state.get(SESSION_NODE_STATUS)
    if not isinstance(status, dict):
        status = initial_node_status()
    edge_status = session_state.get(SESSION_EDGE_STATUS)
    if not isinstance(edge_status, dict):
        edge_status = initial_edge_status()
    attempt_counts = session_state.get(SESSION_ATTEMPT_COUNTS)
    if not isinstance(attempt_counts, dict):
        attempt_counts = initial_attempt_counts()
    _render_architecture_frame(
        target,
        status,
        edge_status=edge_status,
        attempt_counts=attempt_counts,
    )


def _save_streamed_run(session_state: Any, streamed: StreamedRun) -> None:
    """Save one authoritative graph result and its presentation telemetry."""

    session_state[SESSION_LATEST_STATE] = streamed.state
    session_state[SESSION_LATEST_THREAD] = streamed.thread_id
    session_state[SESSION_NODE_STATUS] = streamed.node_status
    session_state[SESSION_EDGE_STATUS] = streamed.edge_status
    session_state[SESSION_ATTEMPT_COUNTS] = streamed.attempt_counts
    session_state[SESSION_EVENT_COUNT] = streamed.event_count
    session_state[SESSION_VISUALIZATION_FAILED] = streamed.visualization_failed


def _saved_streamed_run(session_state: Any) -> StreamedRun:
    """Rebuild the current run record without inventing checkpoint state."""

    state = session_state.get(SESSION_LATEST_STATE)
    thread_id = session_state.get(SESSION_LATEST_THREAD)
    node_status = session_state.get(SESSION_NODE_STATUS)
    edge_status = session_state.get(SESSION_EDGE_STATUS)
    attempt_counts = session_state.get(SESSION_ATTEMPT_COUNTS)
    if not isinstance(state, dict) or not isinstance(thread_id, str):
        raise HumanReviewResumeError("saved requirement checkpoint is unavailable")
    if not isinstance(node_status, dict):
        raise HumanReviewResumeError("saved node telemetry is unavailable")
    if not isinstance(edge_status, dict):
        raise HumanReviewResumeError("saved edge telemetry is unavailable")
    if not isinstance(attempt_counts, dict):
        raise HumanReviewResumeError("saved attempt telemetry is unavailable")

    event_count = session_state.get(SESSION_EVENT_COUNT)
    if not isinstance(event_count, int) or isinstance(event_count, bool):
        raw_events = state.get("execution_events", [])
        event_count = len(raw_events) if isinstance(raw_events, list) else 0
    visualization_failed = session_state.get(SESSION_VISUALIZATION_FAILED, False)
    if not isinstance(visualization_failed, bool):
        visualization_failed = False
    return StreamedRun(
        state=dict(state),
        thread_id=thread_id,
        node_status=dict(node_status),
        edge_status=dict(edge_status),
        attempt_counts=dict(attempt_counts),
        event_count=event_count,
        visualization_failed=visualization_failed,
    )


def _resume_notice(state: Mapping[str, Any]) -> str:
    if state.get("awaiting_human_review") is True:
        return (
            "Human decision applied. The selected rework path ran and the workflow "
            "paused again for review."
        )
    if state.get("final_status") == "REJECTED":
        return (
            "Human decision applied. The requirement was rejected without a final "
            "answer or commitment."
        )
    if state.get("final_status") == "FINALIZED":
        return "Human decision applied. The guarded workflow finalized successfully."
    return "Human decision applied and the saved workflow advanced."


def render_resume_notice() -> None:
    """Display one completion message after Streamlit rerenders the saved result."""

    notice = st.session_state.pop(SESSION_RESUME_NOTICE, None)
    if isinstance(notice, str) and notice:
        st.success(notice)


def resume_saved_human_review(map_target: Any) -> None:
    """Apply the saved draft to its checkpoint while preserving failure isolation."""

    draft = st.session_state.get(SESSION_REVIEW_DECISION_DRAFT)
    if not isinstance(draft, dict):
        render_ui_failure(UiFailureKind.REVIEW_DRAFT, target=st)
        return
    try:
        previous = _saved_streamed_run(st.session_state)
        map_available = True

        def render_event(
            status: dict[str, str],
            edge_status: dict[tuple[str, str], str],
            attempt_counts: dict[str, int],
            event: dict[str, Any],
        ) -> None:
            nonlocal map_available
            if map_available:
                map_available = _render_architecture_frame(
                    map_target,
                    status,
                    edge_status=edge_status,
                    attempt_counts=attempt_counts,
                    live_node=str(event["node"]),
                )
                if map_available:
                    sleep(LIVE_EVENT_DWELL_SECONDS)

        resumed = stream_human_review_decision(
            previous,
            draft,
            on_event=render_event,
        )
    except HumanReviewResumeError:
        render_ui_failure(UiFailureKind.CHECKPOINT_STALE, target=st)
        return
    except Exception:  # noqa: BLE001 - retain paused checkpoint and hide internals
        render_ui_failure(UiFailureKind.RESUME, target=st)
        return

    _save_streamed_run(st.session_state, resumed)
    clear_review_draft(st.session_state)
    st.session_state[SESSION_RESUME_NOTICE] = _resume_notice(resumed.state)
    if resumed.visualization_failed:
        map_target.warning(MAP_ERROR_MESSAGE, icon="⚠️")
    elif map_available:
        _render_architecture_frame(
            map_target,
            resumed.node_status,
            edge_status=resumed.edge_status,
            attempt_counts=resumed.attempt_counts,
        )
    st.rerun()


def render_run_controls(map_target: Any) -> None:
    """Render the Step 3.2 selector and local graph-run controls."""

    try:
        requirements = get_sample_requirements()
    except Exception:  # noqa: BLE001 - sanitize the Streamlit catalog boundary
        st.sidebar.header("Run a sample requirement")
        render_ui_failure(UiFailureKind.SAMPLE_CATALOG, target=st.sidebar)
        return
    requirement_ids = [item.requirement_id for item in requirements]
    by_id = {item.requirement_id: item for item in requirements}

    st.sidebar.header("Run a sample requirement")
    selected_id = st.sidebar.selectbox(
        "Sample requirement",
        options=requirement_ids,
        format_func=lambda requirement_id: by_id[requirement_id].display_label,
    )
    selected = requirement_by_id(requirements, selected_id)
    st.sidebar.text_area(
        "Selected requirement text",
        value=selected.text,
        height=120,
        disabled=True,
    )

    if st.sidebar.button("Run selected requirement", type="primary", width="stretch"):
        run_number = int(st.session_state.get(SESSION_RUN_COUNT, 0)) + 1
        session_id = st.session_state.get(SESSION_INSTANCE_ID)
        if not isinstance(session_id, str) or not session_id:
            session_id = uuid4().hex[:12]
            st.session_state[SESSION_INSTANCE_ID] = session_id
        st.session_state[SESSION_RUN_COUNT] = run_number
        map_available = True

        def render_event(
            status: dict[str, str],
            edge_status: dict[tuple[str, str], str],
            attempt_counts: dict[str, int],
            event: dict[str, Any],
        ) -> None:
            nonlocal map_available
            if map_available:
                map_available = _render_architecture_frame(
                    map_target,
                    status,
                    edge_status=edge_status,
                    attempt_counts=attempt_counts,
                    live_node=str(event["node"]),
                )
                if map_available:
                    sleep(LIVE_EVENT_DWELL_SECONDS)

        try:
            streamed = stream_sample_requirement(
                selected,
                run_number,
                session_id,
                on_event=render_event,
            )
        except Exception:  # noqa: BLE001 - sanitize the Streamlit run boundary
            _restore_saved_architecture_frame(map_target, st.session_state)
            render_ui_failure(UiFailureKind.RUN, target=st.sidebar)
        else:
            clear_review_draft(st.session_state)
            st.session_state.pop(SESSION_RESUME_NOTICE, None)
            _save_streamed_run(st.session_state, streamed)
            st.session_state[SESSION_LATEST_REQUIREMENT] = selected.requirement_id
            if streamed.visualization_failed:
                map_target.warning(MAP_ERROR_MESSAGE, icon="⚠️")
            elif map_available:
                _render_architecture_frame(
                    map_target,
                    streamed.node_status,
                    edge_status=streamed.edge_status,
                    attempt_counts=streamed.attempt_counts,
                )
            st.sidebar.success(f"Saved run for {selected.requirement_id}.")

    if st.sidebar.button("Clear current run", width="stretch"):
        clear_current_run(st.session_state)
        st.sidebar.info("Current run cleared.")

    latest_requirement = st.session_state.get(SESSION_LATEST_REQUIREMENT)
    if latest_requirement:
        st.sidebar.caption(f"Current saved run: {latest_requirement}")


def render_app() -> None:
    """Render the Phase 3 application shell."""

    configure_page()
    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)
    render_safety_notice()
    render_resume_notice()
    map_target = render_architecture_map()
    render_run_controls(map_target)
    try:
        render_requirement_table()
    except Exception:  # noqa: BLE001 - sanitize the Streamlit result boundary
        render_ui_failure(UiFailureKind.RESULT_DISPLAY, target=st)
    try:
        resume_requested = render_human_review_controls(
            st.session_state.get(SESSION_LATEST_STATE),
            st.session_state,
        )
    except Exception:  # noqa: BLE001 - sanitize the Streamlit review boundary
        render_ui_failure(UiFailureKind.REVIEW_CONTROLS, target=st)
        resume_requested = False
    if resume_requested:
        resume_saved_human_review(map_target)
    try:
        render_requirement_details(st.session_state.get(SESSION_LATEST_STATE))
    except Exception:  # noqa: BLE001 - sanitize the Streamlit detail boundary
        render_ui_failure(UiFailureKind.DETAIL_DISPLAY, target=st)
    render_docx_download(st.session_state.get(SESSION_LATEST_STATE))
