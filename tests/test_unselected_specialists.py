from xml.etree import ElementTree

import pytest

from rfp_orchestrator.architecture_map import STATUS_VISUALS, render_architecture_html
from rfp_orchestrator.node_status import (
    NodeStatusError,
    initial_node_status,
    validate_unselected_specialists_inactive,
)
from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.ui import stream_sample_requirement


def _rendered_specialist_statuses(fragment: str) -> dict[str, str]:
    root = ElementTree.fromstring(f"<root>{fragment}</root>")
    svg = root.find("div/svg")
    return {
        node.attrib["data-node"]: node.attrib["data-status"]
        for node in svg.findall("g")
        if node.attrib["data-node"].endswith("_specialist")
    }


def test_visibility_contract_accepts_only_selected_noninactive_specialists() -> None:
    status = initial_node_status()
    status["product_specialist"] = "active"

    validate_unselected_specialists_inactive(status, ["product"])


@pytest.mark.parametrize("unexpected_status", ["active", "complete", "blocked"])
def test_visibility_contract_rejects_an_unselected_noninactive_specialist(
    unexpected_status: str,
) -> None:
    status = initial_node_status()
    status["security_specialist"] = unexpected_status

    with pytest.raises(
        NodeStatusError,
        match="unselected security specialist must remain inactive",
    ):
        validate_unselected_specialists_inactive(status, ["product"])


@pytest.mark.parametrize(
    "selected, message",
    [
        ("product", "domain collection"),
        (["unknown"], "unknown domain"),
        (["product", "product"], "duplicates"),
    ],
)
def test_visibility_contract_rejects_invalid_selection_metadata(
    selected: object,
    message: str,
) -> None:
    with pytest.raises(NodeStatusError, match=message):
        validate_unselected_specialists_inactive(initial_node_status(), selected)


def test_single_domain_stream_keeps_both_unselected_peers_inactive_in_every_frame() -> None:
    frames: list[dict[str, str]] = []

    def capture(
        status: dict[str, str], _edges: dict, _counts: dict, _event: dict
    ) -> None:
        frames.append(status)

    result = stream_sample_requirement(
        load_sample_requirements()[0],
        1,
        "unselected-single",
        on_event=capture,
    )

    assert frames
    assert all(frame["security_specialist"] == "inactive" for frame in frames)
    assert all(frame["implementation_specialist"] == "inactive" for frame in frames)
    assert result.node_status["product_specialist"] == "complete"


def test_cross_domain_stream_keeps_only_the_unused_peer_inactive_in_every_frame() -> None:
    frames: list[dict[str, str]] = []

    def capture(
        status: dict[str, str], _edges: dict, _counts: dict, _event: dict
    ) -> None:
        frames.append(status)

    result = stream_sample_requirement(
        load_sample_requirements()[1],
        1,
        "unselected-cross",
        on_event=capture,
    )

    assert frames
    assert all(frame["implementation_specialist"] == "inactive" for frame in frames)
    assert result.node_status["product_specialist"] == "complete"
    assert result.node_status["security_specialist"] == "complete"


def test_new_run_does_not_inherit_specialist_colors_from_the_previous_run() -> None:
    requirements = load_sample_requirements()
    first = stream_sample_requirement(requirements[1], 1, "fresh-run")
    second_frames: list[dict[str, str]] = []

    def capture(
        status: dict[str, str], _edges: dict, _counts: dict, _event: dict
    ) -> None:
        second_frames.append(status)

    second = stream_sample_requirement(
        requirements[3],
        2,
        "fresh-run",
        on_event=capture,
    )

    assert first.node_status["product_specialist"] == "complete"
    assert first.node_status["security_specialist"] == "complete"
    assert second_frames
    assert all(frame["product_specialist"] == "inactive" for frame in second_frames)
    assert all(frame["security_specialist"] == "inactive" for frame in second_frames)
    assert second.node_status["implementation_specialist"] == "complete"


def test_unselected_peers_render_with_inactive_text_and_gray_status_token() -> None:
    result = stream_sample_requirement(
        load_sample_requirements()[0],
        1,
        "unselected-render",
    )
    fragment = render_architecture_html(result.node_status)
    rendered = _rendered_specialist_statuses(fragment)

    assert rendered == {
        "product_specialist": "complete",
        "security_specialist": "inactive",
        "implementation_specialist": "inactive",
    }
    assert STATUS_VISUALS["inactive"].color_name == "gray"
    assert "Security Specialist: inactive" in fragment
    assert "Implementation Specialist: inactive" in fragment
