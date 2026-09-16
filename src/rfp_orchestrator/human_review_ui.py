"""Streamlit controls for preparing and explicitly applying HITL decisions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import streamlit as st
from pydantic import ValidationError

from rfp_orchestrator.human_review import (
    HumanReviewDecision,
    HumanReviewReason,
    HumanReviewRequest,
)
from rfp_orchestrator.models import ApprovalDecision, Domain
from rfp_orchestrator.ui_feedback import UiFailureKind, render_ui_failure

SESSION_REVIEW_ACTION = "review_action"
SESSION_REVIEW_DECISION_DRAFT = "review_decision_draft"
SESSION_REVIEW_REVIEWER = "review_reviewer"
SESSION_REVIEW_EDITED_ANSWER = "review_edited_answer"
SESSION_REVIEW_GUIDANCE = "review_guidance"
SESSION_REVIEW_PROPOSALS = "review_proposals"
SESSION_REVIEW_SPECIALISTS = "review_specialists"
SESSION_REVIEW_RESUME_BUTTON = "apply_human_review_decision"
REVIEW_SESSION_KEYS = (
    SESSION_REVIEW_ACTION,
    SESSION_REVIEW_DECISION_DRAFT,
    SESSION_REVIEW_REVIEWER,
    SESSION_REVIEW_EDITED_ANSWER,
    SESSION_REVIEW_GUIDANCE,
    SESSION_REVIEW_PROPOSALS,
    SESSION_REVIEW_SPECIALISTS,
    SESSION_REVIEW_RESUME_BUTTON,
)

DECISION_LABELS = {
    ApprovalDecision.APPROVE: "Approve",
    ApprovalDecision.EDIT_AND_APPROVE: "Edit and approve",
    ApprovalDecision.REJECT: "Reject",
    ApprovalDecision.ADD_GUIDANCE: "Add guidance",
    ApprovalDecision.REQUEST_RETRY: "Request retry",
}


class HumanReviewControlError(ValueError):
    """Raised when a UI decision draft is incomplete or unsafe."""


@dataclass(frozen=True)
class ReviewActionOption:
    decision: ApprovalDecision
    label: str
    enabled: bool
    disabled_reason: str | None = None


def clear_review_draft(session_state: Any) -> None:
    """Remove only human-review form and draft values from session state."""

    for key in REVIEW_SESSION_KEYS:
        session_state.pop(key, None)


def _review_request(state: dict) -> HumanReviewRequest:
    raw_request = state.get("human_review_request")
    if state.get("awaiting_human_review") is not True or not isinstance(
        raw_request, dict
    ):
        raise HumanReviewControlError("no paused human-review checkpoint is available")
    try:
        return HumanReviewRequest.model_validate(raw_request)
    except (TypeError, ValueError) as error:
        raise HumanReviewControlError("saved human-review request is malformed") from error


def available_review_specialists(state: dict) -> tuple[Domain, ...]:
    """Return relevant peers in stable domain order without expanding scope."""

    available: list[Domain] = []
    for field in (
        "initial_specialists",
        "recovery_specialists",
        "conflict_specialists",
        "assigned_domains",
    ):
        values = state.get(field, [])
        if not isinstance(values, list):
            raise HumanReviewControlError("saved specialist scope is malformed")
        for value in values:
            try:
                specialist = Domain(value)
            except (TypeError, ValueError) as error:
                raise HumanReviewControlError(
                    "saved specialist scope contains an unknown domain"
                ) from error
            if specialist not in available:
                available.append(specialist)
    return tuple(available)


def review_action_options(state: dict) -> tuple[ReviewActionOption, ...]:
    """Expose all five locked decisions with checkpoint-aware availability."""

    request = _review_request(state)
    available = available_review_specialists(state)
    unresolved_conflict = request.reason is HumanReviewReason.UNRESOLVED_CONFLICT
    options: list[ReviewActionOption] = []
    for decision in request.allowed_decisions:
        enabled = True
        reason: str | None = None
        if unresolved_conflict and decision in {
            ApprovalDecision.APPROVE,
            ApprovalDecision.EDIT_AND_APPROVE,
        }:
            enabled = False
            reason = (
                "Resolve the evidence conflict before approving this response. "
                "Use Add guidance, Request retry, or Reject."
            )
        elif decision is ApprovalDecision.APPROVE and not request.proposed_answers:
            enabled = False
            reason = "No checkpointed proposed answer is available; use Edit and approve."
        elif decision is ApprovalDecision.ADD_GUIDANCE and not available:
            enabled = False
            reason = "No relevant specialist is available for guided rework."
        elif decision is ApprovalDecision.REQUEST_RETRY:
            if request.retry_count >= 2:
                enabled = False
                reason = "The locked two-retry retrieval budget is exhausted."
            elif not available:
                enabled = False
                reason = "No relevant specialist is available for a retry."
        options.append(
            ReviewActionOption(
                decision=decision,
                label=DECISION_LABELS[decision],
                enabled=enabled,
                disabled_reason=reason,
            )
        )
    return tuple(options)


def review_proposal_ids(state: dict) -> tuple[str, ...]:
    """Return only well-formed proposal IDs belonging to this requirement."""

    requirement_id = str(state.get("requirement_id", "")).strip()
    raw_proposals = state.get("proposed_commitments", [])
    if not isinstance(raw_proposals, list):
        raise HumanReviewControlError("saved proposal state is malformed")
    proposal_ids: list[str] = []
    for proposal in raw_proposals:
        if not isinstance(proposal, dict):
            raise HumanReviewControlError("saved proposal state is malformed")
        proposal_id = str(proposal.get("proposal_id", "")).strip()
        source_requirement_id = str(
            proposal.get("source_requirement_id", "")
        ).strip()
        if not proposal_id or source_requirement_id != requirement_id:
            raise HumanReviewControlError("saved proposal provenance is invalid")
        if proposal_id in proposal_ids:
            raise HumanReviewControlError("saved proposal IDs cannot repeat")
        proposal_ids.append(proposal_id)
    return tuple(proposal_ids)


def build_decision_draft(
    state: dict,
    *,
    decision: ApprovalDecision | str,
    reviewer: str,
    edited_answer: str | None = None,
    guidance: str | None = None,
    approved_proposal_ids: list[str] | None = None,
    target_specialists: list[str] | None = None,
    timestamp: str | None = None,
) -> dict:
    """Validate one auditable decision draft without resuming the graph."""

    request = _review_request(state)
    try:
        selected_decision = ApprovalDecision(decision)
    except (TypeError, ValueError) as error:
        raise HumanReviewControlError("unknown human-review decision") from error
    option = next(
        item for item in review_action_options(state) if item.decision is selected_decision
    )
    if not option.enabled:
        raise HumanReviewControlError(option.disabled_reason or "decision is unavailable")

    allowed_proposals = set(review_proposal_ids(state))
    selected_proposals = approved_proposal_ids or []
    if any(proposal_id not in allowed_proposals for proposal_id in selected_proposals):
        raise HumanReviewControlError(
            "selected proposal is outside the saved requirement"
        )
    available_specialists = set(available_review_specialists(state))
    try:
        selected_specialists = [Domain(value) for value in (target_specialists or [])]
    except (TypeError, ValueError) as error:
        raise HumanReviewControlError("selected specialist is unknown") from error
    if any(specialist not in available_specialists for specialist in selected_specialists):
        raise HumanReviewControlError(
            "selected specialist is outside the saved requirement scope"
        )

    try:
        draft = HumanReviewDecision(
            requirement_id=request.requirement_id,
            decision=selected_decision,
            reviewer=reviewer,
            timestamp=timestamp
            or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            edited_answer=edited_answer,
            guidance=guidance,
            approved_proposal_ids=selected_proposals,
            target_specialists=selected_specialists,
        )
    except ValidationError as error:
        raise HumanReviewControlError(
            "Complete the required fields for this decision."
        ) from error
    return draft.model_dump(mode="json", exclude_none=True)


def _format_review_reason(value: str) -> str:
    return value.replace("_", " ").title()


def render_human_review_controls(state: object, session_state: Any) -> bool:
    """Render HITL controls and report an explicit checkpoint-resume request."""

    if not isinstance(state, dict) or state.get("awaiting_human_review") is not True:
        return False
    try:
        request = _review_request(state)
        options = review_action_options(state)
        specialists = available_review_specialists(state)
        proposal_ids = review_proposal_ids(state)
    except HumanReviewControlError:
        render_ui_failure(UiFailureKind.REVIEW_CONTROLS, target=st)
        return False

    st.subheader("Human review")
    st.warning(
        "The graph is paused at a saved checkpoint. Prepare and save a decision, "
        "then apply it explicitly to resume this requirement."
    )
    st.markdown(f"**Reason:** {_format_review_reason(request.reason.value)}")
    st.caption(request.rationale)

    columns = st.columns(len(options))
    for column, option in zip(columns, options, strict=True):
        if column.button(
            option.label,
            key=f"review_action_{option.decision.value.lower()}",
            disabled=not option.enabled,
            help=option.disabled_reason,
            width="stretch",
        ):
            session_state[SESSION_REVIEW_ACTION] = option.decision.value
            session_state.pop(SESSION_REVIEW_DECISION_DRAFT, None)

    selected_raw = session_state.get(SESSION_REVIEW_ACTION)
    if not isinstance(selected_raw, str):
        st.caption("Choose one review action to prepare its decision fields.")
        return False
    try:
        selected = ApprovalDecision(selected_raw)
    except ValueError:
        session_state.pop(SESSION_REVIEW_ACTION, None)
        st.error(
            "The selected review action is no longer valid.\n\n"
            "**What to do next:** Choose one of the five review actions again."
        )
        return False

    st.markdown(f"#### Prepare: {DECISION_LABELS[selected]}")
    with st.form("human_review_decision_form", clear_on_submit=False):
        reviewer = st.text_input(
            "Reviewer name or email",
            key=SESSION_REVIEW_REVIEWER,
            help="Required for the decision audit trail.",
        )
        edited_answer: str | None = None
        guidance: str | None = None
        selected_proposals: list[str] = []
        selected_specialists: list[str] = []

        if selected in {
            ApprovalDecision.APPROVE,
            ApprovalDecision.EDIT_AND_APPROVE,
        } and proposal_ids:
            selected_proposals = st.multiselect(
                "Commitment proposals to approve",
                options=list(proposal_ids),
                key=SESSION_REVIEW_PROPOSALS,
                help="Leave empty to approve the answer without promoting commitments.",
            )
        if selected is ApprovalDecision.EDIT_AND_APPROVE:
            edited_answer = st.text_area(
                "Edited final answer",
                value="\n\n".join(request.proposed_answers),
                key=SESSION_REVIEW_EDITED_ANSWER,
                height=180,
            )
        if selected in {
            ApprovalDecision.ADD_GUIDANCE,
            ApprovalDecision.REQUEST_RETRY,
        }:
            guidance = st.text_area(
                (
                    "Reviewer guidance"
                    if selected is ApprovalDecision.ADD_GUIDANCE
                    else "Retry guidance (optional)"
                ),
                key=SESSION_REVIEW_GUIDANCE,
                height=120,
            )
            selected_specialists = st.multiselect(
                "Specialists to involve",
                options=[item.value for item in specialists],
                default=[item.value for item in specialists],
                key=SESSION_REVIEW_SPECIALISTS,
                format_func=lambda value: value.title(),
            )

        submitted = st.form_submit_button(
            "Save decision draft",
            type="primary",
            width="stretch",
        )

    if submitted:
        try:
            draft = build_decision_draft(
                state,
                decision=selected,
                reviewer=reviewer,
                edited_answer=edited_answer,
                guidance=guidance or None,
                approved_proposal_ids=selected_proposals,
                target_specialists=selected_specialists,
            )
        except HumanReviewControlError as error:
            st.error(
                f"{error}\n\n"
                "**What to do next:** Review the visible fields, correct the "
                "highlighted decision information, and select **Save decision "
                "draft** again."
            )
        else:
            session_state[SESSION_REVIEW_DECISION_DRAFT] = draft
            st.success(
                "Decision draft validated and saved. The graph remains paused until "
                "you apply this saved decision."
            )

    saved = session_state.get(SESSION_REVIEW_DECISION_DRAFT)
    if isinstance(saved, dict):
        decision_label = _format_review_reason(str(saved.get("decision", "")))
        reviewer_label = str(saved.get("reviewer", "")).strip()
        st.caption(f"Saved draft: {decision_label} — {reviewer_label}")
        return st.button(
            "Apply decision and resume workflow",
            key=SESSION_REVIEW_RESUME_BUTTON,
            type="primary",
            width="stretch",
            help=(
                "Applies this validated draft to the saved checkpoint for the current "
                "requirement."
            ),
        )
    return False
