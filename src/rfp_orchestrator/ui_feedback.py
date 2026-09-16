"""Sanitized, actionable Streamlit failure messages."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any


class UiFailureKind(str, Enum):
    """Stable categories for recoverable presentation-boundary failures."""

    SAMPLE_CATALOG = "sample_catalog"
    RUN = "run"
    MAP = "map"
    REVIEW_CONTROLS = "review_controls"
    REVIEW_DRAFT = "review_draft"
    CHECKPOINT_STALE = "checkpoint_stale"
    RESUME = "resume"
    RESULT_DISPLAY = "result_display"
    DETAIL_DISPLAY = "detail_display"
    DOCX_EXPORT = "docx_export"


@dataclass(frozen=True)
class UiFailureMessage:
    """User-safe explanation that never accepts provider exception text."""

    reference: str
    title: str
    impact: str
    next_action: str

    def markdown(self) -> str:
        return (
            f"**{self.title}**\n\n"
            f"{self.impact}\n\n"
            f"**What to do next:** {self.next_action}\n\n"
            f"Reference: `{self.reference}`"
        )


UI_FAILURE_MESSAGES: dict[UiFailureKind, UiFailureMessage] = {
    UiFailureKind.SAMPLE_CATALOG: UiFailureMessage(
        reference="RFP-UI-001",
        title="The sample requirements could not be loaded.",
        impact="No requirement was run and any previously saved result is unchanged.",
        next_action=(
            "Restart Streamlit in the VS Code terminal. If this message returns, "
            "confirm that `data/sample_rfp.md` is still present, then ask Codex to "
            "check the sample file."
        ),
    ),
    UiFailureKind.RUN: UiFailureMessage(
        reference="RFP-UI-002",
        title="The requirement run did not complete.",
        impact=(
            "No incomplete result was saved; the previous saved result, if any, "
            "remains available."
        ),
        next_action=(
            "Choose **Run selected requirement** once more. If it fails again, "
            "restart Streamlit in the VS Code terminal and retry the same sample."
        ),
    ),
    UiFailureKind.MAP: UiFailureMessage(
        reference="RFP-UI-003",
        title="The architecture map is temporarily unavailable.",
        impact="The requirement run and saved result are unaffected.",
        next_action=(
            "Continue reviewing the result below. Refresh the page to restore the "
            "map; you do not need to rerun the requirement."
        ),
    ),
    UiFailureKind.REVIEW_CONTROLS: UiFailureMessage(
        reference="RFP-UI-004",
        title="The human-review controls could not be prepared.",
        impact="No decision was applied and the saved workflow remains paused.",
        next_action=(
            "Choose **Clear current run**, run the same requirement again, and "
            "prepare a new decision."
        ),
    ),
    UiFailureKind.REVIEW_DRAFT: UiFailureMessage(
        reference="RFP-UI-005",
        title="A valid saved decision is required.",
        impact="The workflow remains paused and no decision was applied.",
        next_action=(
            "Choose a review action, complete its required fields, select "
            "**Save decision draft**, and then apply it."
        ),
    ),
    UiFailureKind.CHECKPOINT_STALE: UiFailureMessage(
        reference="RFP-UI-006",
        title="This review checkpoint is no longer current.",
        impact=(
            "The decision was not applied; the saved result and decision draft "
            "were retained."
        ),
        next_action=(
            "Choose **Clear current run**, run the same requirement again, and "
            "prepare a new decision for its new checkpoint."
        ),
    ),
    UiFailureKind.RESUME: UiFailureMessage(
        reference="RFP-UI-007",
        title="The saved decision could not be applied.",
        impact=(
            "The checkpoint and decision draft were retained, and the workflow "
            "remains paused."
        ),
        next_action=(
            "Select **Apply decision and resume workflow** once more. If it fails "
            "again, clear the current run and rerun the same requirement."
        ),
    ),
    UiFailureKind.RESULT_DISPLAY: UiFailureMessage(
        reference="RFP-UI-008",
        title="The saved result summary could not be displayed.",
        impact="The underlying saved graph result was not changed.",
        next_action=(
            "Refresh the page. If this message returns, clear the current run and "
            "run the same requirement again."
        ),
    ),
    UiFailureKind.DETAIL_DISPLAY: UiFailureMessage(
        reference="RFP-UI-009",
        title="The response details could not be displayed.",
        impact="The underlying saved graph result was not changed.",
        next_action=(
            "Use the result summary above, then refresh the page. If this message "
            "returns, clear the current run and rerun the requirement."
        ),
    ),
    UiFailureKind.DOCX_EXPORT: UiFailureMessage(
        reference="RFP-UI-010",
        title="The DOCX response could not be prepared.",
        impact=(
            "The saved graph result and any human-review decision are unchanged. "
            "No incomplete document was offered for download."
        ),
        next_action=(
            "Clear the current run and run the same requirement again. If this "
            "message returns, ask Codex to check the saved response state."
        ),
    ),
}


def failure_markdown(kind: UiFailureKind) -> str:
    """Return only fixed copy; exception details cannot enter this function."""

    return UI_FAILURE_MESSAGES[kind].markdown()


def render_ui_failure(kind: UiFailureKind, *, target: Any) -> None:
    """Render one sanitized failure with an exact recovery action."""

    target.error(failure_markdown(kind), icon="🚫")
