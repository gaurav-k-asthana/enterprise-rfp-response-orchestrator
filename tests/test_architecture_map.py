from pathlib import Path
from xml.etree import ElementTree

import pytest
from streamlit.testing.v1 import AppTest

from rfp_orchestrator.architecture_map import (
    MAP_EDGES,
    NODE_LAYOUT,
    STATUS_VISUALS,
    render_architecture_html,
)
from rfp_orchestrator.edge_status import initial_edge_status
from rfp_orchestrator.graph_topology import (
    PEER_TOPOLOGY_EDGES,
    SPECIALIST_NODES,
    GraphNode,
)
from rfp_orchestrator.models import ExecutionStatus
from rfp_orchestrator.node_status import (
    NodeStatusError,
    initial_node_status,
    reduce_node_status,
)
from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.ui import run_sample_requirement

PROJECT_ROOT = Path(__file__).resolve().parents[1]
APP_PATH = PROJECT_ROOT / "app.py"


def _svg_root(fragment: str) -> ElementTree.Element:
    return ElementTree.fromstring(f"<root>{fragment}</root>").find("div/svg")


def _contrast_ratio(foreground: str, background: str) -> float:
    def luminance(color: str) -> float:
        channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
        linear = [
            channel / 12.92
            if channel <= 0.04045
            else ((channel + 0.055) / 1.055) ** 2.4
            for channel in channels
        ]
        return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]

    first, second = sorted(
        (luminance(foreground), luminance(background)), reverse=True
    )
    return (first + 0.05) / (second + 0.05)


def test_layout_contains_every_graph_node_once_at_a_unique_position() -> None:
    assert tuple(NODE_LAYOUT) == tuple(node.value for node in GraphNode)
    assert len(NODE_LAYOUT) == 21
    assert len({(box.x, box.y) for box in NODE_LAYOUT.values()}) == 21


def test_map_edges_exactly_preserve_the_locked_peer_topology() -> None:
    assert set(MAP_EDGES) == {
        (source.value, target.value) for source, target in PEER_TOPOLOGY_EDGES
    }
    assert not any(
        GraphNode(source) in SPECIALIST_NODES and GraphNode(target) in SPECIALIST_NODES
        for source, target in MAP_EDGES
    )


def test_initial_svg_is_accessible_and_contains_all_inactive_nodes() -> None:
    fragment = render_architecture_html(initial_node_status())
    svg = _svg_root(fragment)

    assert svg is not None
    assert svg.attrib["role"] == "img"
    assert svg.find("title").text == "Enterprise RFP orchestration architecture"
    nodes = svg.findall("g")
    assert len(nodes) == 21
    assert {node.attrib["data-node"] for node in nodes} == set(NODE_LAYOUT)
    assert {node.attrib["data-status"] for node in nodes} == {"inactive"}


def test_locked_status_visuals_match_all_six_execution_states() -> None:
    assert tuple(STATUS_VISUALS) == tuple(status.value for status in ExecutionStatus)
    assert {
        status: visual.color_name for status, visual in STATUS_VISUALS.items()
    } == {
        "inactive": "gray",
        "active": "blue",
        "complete": "green",
        "recovery": "orange",
        "blocked": "red",
        "state_access": "purple",
    }


def test_status_colors_have_readable_light_and_dark_text_contrast() -> None:
    for visual in STATUS_VISUALS.values():
        assert _contrast_ratio(visual.light_color, "#ffffff") >= 4.5
        assert _contrast_ratio(visual.dark_color, "#000000") >= 4.5


def test_status_legend_is_complete_accessible_and_matches_css_tokens() -> None:
    fragment = render_architecture_html(initial_node_status())
    root = ElementTree.fromstring(f"<root>{fragment}</root>")
    legend = root.find("div/div[@class='rfp-map-legend']")

    assert legend is not None
    assert legend.attrib == {
        "class": "rfp-map-legend",
        "role": "list",
        "aria-label": "Node and arrow execution status colors",
    }
    legend_items = legend.findall("span")
    assert [item.attrib["data-status"] for item in legend_items] == list(
        STATUS_VISUALS
    )
    for status, visual in STATUS_VISUALS.items():
        token = f"--rfp-status-{status.replace('_', '-')}"
        assert f"{token}: light-dark({visual.light_color}, {visual.dark_color})" in fragment
        assert f'--rfp-node-color: var({token})' in fragment
        assert f"{visual.color_name.title()} — {visual.legend_label}" in fragment


def test_each_status_remains_visible_as_text_in_addition_to_color() -> None:
    status = initial_node_status()
    sample_nodes = tuple(status)[: len(STATUS_VISUALS)]
    for node, execution_status in zip(sample_nodes, STATUS_VISUALS, strict=True):
        status[node] = execution_status

    svg = _svg_root(render_architecture_html(status))
    rendered = {
        item.attrib["data-node"]: (
            item.attrib["data-status"], item.find("text[@class='rfp-map-status']").text
        )
        for item in svg.findall("g")
    }

    for node, execution_status in zip(sample_nodes, STATUS_VISUALS, strict=True):
        assert rendered[node] == (
            execution_status,
            execution_status.replace("_", " ").title(),
        )


def test_live_event_marks_one_node_and_updates_the_accessible_status_line() -> None:
    status = initial_node_status()
    status["product_specialist"] = "active"
    fragment = render_architecture_html(status, live_node="product_specialist")
    root = ElementTree.fromstring(f"<root>{fragment}</root>")
    map_root = root.find("div")
    live_line = root.find("div/div[@class='rfp-map-live']")
    svg = _svg_root(fragment)

    assert map_root.attrib["id"] == "rfp-architecture-map"
    assert map_root.attrib["aria-busy"] == "true"
    assert live_line.attrib["role"] == "status"
    assert live_line.attrib["aria-live"] == "polite"
    assert live_line.attrib["data-live-node"] == "product_specialist"
    assert live_line.attrib["data-status"] == "active"
    assert live_line.text == "Now: Product Specialist — Active"
    current = [
        node
        for node in svg.findall("g")
        if node.attrib["data-current-event"] == "true"
    ]
    assert [node.attrib["data-node"] for node in current] == ["product_specialist"]


def test_snapshot_and_reduced_motion_styles_are_explicit() -> None:
    fragment = render_architecture_html(initial_node_status())
    root = ElementTree.fromstring(f"<root>{fragment}</root>")
    map_root = root.find("div")
    live_line = root.find("div/div[@class='rfp-map-live']")

    assert map_root.attrib["aria-busy"] == "false"
    assert live_line.text == "Current snapshot"
    assert '@media (prefers-reduced-motion: reduce)' in fragment
    assert "transition: fill 180ms ease" in fragment
    assert "transition: none" in fragment


def test_renderer_rejects_an_unknown_live_node() -> None:
    with pytest.raises(ValueError, match="canonical architecture node"):
        render_architecture_html(initial_node_status(), live_node="unknown_node")


def test_svg_contains_every_topology_edge_once() -> None:
    svg = _svg_root(render_architecture_html(initial_node_status()))
    edges = [path.attrib["data-edge"] for path in svg.findall("path") if "data-edge" in path.attrib]

    assert len(edges) == len(MAP_EDGES)
    assert set(edges) == {f"{source}--{target}" for source, target in MAP_EDGES}


def test_edge_flow_status_controls_line_and_arrowhead_treatment() -> None:
    edge_status = initial_edge_status()
    edge = ("requirement_analyzer", "strategy_orchestrator")
    edge_status[edge] = "active"
    fragment = render_architecture_html(
        initial_node_status(),
        edge_status=edge_status,
    )
    svg = _svg_root(fragment)
    rendered_edge = next(
        path
        for path in svg.findall("path")
        if path.attrib.get("data-edge") == "--".join(edge)
    )

    assert rendered_edge.attrib["data-status"] == "active"
    assert rendered_edge.attrib["marker-end"] == "url(#rfp-map-arrow-active)"
    assert '.rfp-map-edge[data-status="active"]' in fragment
    assert "stroke-opacity: 0.95" in fragment
    assert '.rfp-map-edge[data-status="complete"]' in fragment
    assert "stroke-opacity: 0.42" in fragment


def test_real_run_statuses_are_written_into_the_rendered_nodes() -> None:
    state, _ = run_sample_requirement(load_sample_requirements()[0], 1)
    status = reduce_node_status(state["execution_events"])
    svg = _svg_root(render_architecture_html(status))
    by_node = {item.attrib["data-node"]: item.attrib["data-status"] for item in svg.findall("g")}

    assert by_node["product_specialist"] == "complete"
    assert by_node["security_specialist"] == "inactive"
    assert by_node["implementation_specialist"] == "inactive"


def test_renderer_rejects_noncanonical_status_input() -> None:
    invalid = initial_node_status()
    invalid.pop("merge")

    with pytest.raises(NodeStatusError, match="canonical architecture order"):
        render_architecture_html(invalid)


def test_streamlit_page_renders_map_before_and_after_a_run() -> None:
    app = AppTest.from_file(str(APP_PATH)).run(timeout=10)

    assert not app.exception
    assert "Architecture execution map" in [item.value for item in app.subheader]
    assert len(app.get("iframe")) == 1

    app.sidebar.button[0].click().run(timeout=10)

    assert not app.exception
    assert len(app.get("iframe")) == 1
