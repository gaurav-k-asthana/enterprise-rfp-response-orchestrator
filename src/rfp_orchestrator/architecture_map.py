"""Lightweight, dependency-free SVG rendering for the graph architecture."""

from __future__ import annotations

from dataclasses import dataclass
from html import escape

from rfp_orchestrator.attempt_counters import (
    ATTEMPT_COUNTER_LIMITS,
    initial_attempt_counts,
    validate_attempt_counts,
)
from rfp_orchestrator.edge_status import (
    EDGE_KEYS,
    initial_edge_status,
    validate_edge_status,
)
from rfp_orchestrator.graph_topology import GraphNode
from rfp_orchestrator.models import ExecutionStatus
from rfp_orchestrator.node_status import validate_node_status

SVG_WIDTH = 1200
SVG_HEIGHT = 1160
NODE_WIDTH = 260
NODE_HEIGHT = 68


@dataclass(frozen=True)
class NodeBox:
    x: int
    y: int
    label: str


@dataclass(frozen=True)
class StatusVisual:
    color_name: str
    legend_label: str
    light_color: str
    dark_color: str


STATUS_VISUALS: dict[str, StatusVisual] = {
    ExecutionStatus.INACTIVE.value: StatusVisual(
        "gray", "Inactive / not invoked", "#4b5563", "#d1d5db"
    ),
    ExecutionStatus.ACTIVE.value: StatusVisual(
        "blue", "Executing", "#1d4ed8", "#93c5fd"
    ),
    ExecutionStatus.COMPLETE.value: StatusVisual(
        "green", "Completed", "#15803d", "#86efac"
    ),
    ExecutionStatus.RECOVERY.value: StatusVisual(
        "orange", "Retry / recovery", "#c2410c", "#fdba74"
    ),
    ExecutionStatus.BLOCKED.value: StatusVisual(
        "red", "Blocked / human review", "#b91c1c", "#fca5a5"
    ),
    ExecutionStatus.STATE_ACCESS.value: StatusVisual(
        "purple", "State read / write", "#7e22ce", "#d8b4fe"
    ),
}


NODE_LAYOUT: dict[str, NodeBox] = {
    GraphNode.REQUIREMENT_ANALYZER.value: NodeBox(470, 30, "Requirement Analyzer"),
    GraphNode.STRATEGY_ORCHESTRATOR.value: NodeBox(470, 120, "Strategy Orchestrator"),
    GraphNode.PRODUCT_SPECIALIST.value: NodeBox(90, 230, "Product Specialist"),
    GraphNode.SECURITY_SPECIALIST.value: NodeBox(470, 230, "Security Specialist"),
    GraphNode.IMPLEMENTATION_SPECIALIST.value: NodeBox(
        850, 230, "Implementation Specialist"
    ),
    GraphNode.MERGE.value: NodeBox(470, 340, "Specialist Merge"),
    GraphNode.CITATION_VALIDATION.value: NodeBox(90, 450, "Citation Validation"),
    GraphNode.SOURCE_VALIDATION.value: NodeBox(470, 450, "Source Validation"),
    GraphNode.CLAIM_SUPPORT_VALIDATION.value: NodeBox(
        850, 450, "Claim Support Validation"
    ),
    GraphNode.RECOVERY_PLANNING.value: NodeBox(470, 560, "Recovery Planning"),
    GraphNode.RECOVERY_ATTEMPT.value: NodeBox(90, 670, "Retrieval Recovery Attempt"),
    GraphNode.COMMITMENT_LEDGER.value: NodeBox(470, 670, "Commitment Ledger"),
    GraphNode.COMMITMENT_CONSISTENCY.value: NodeBox(
        470, 760, "Commitment Consistency"
    ),
    GraphNode.CONFLICT_RESOLUTION.value: NodeBox(470, 850, "Conflict Resolution"),
    GraphNode.CONFLICT_REANALYSIS_ATTEMPT.value: NodeBox(
        90, 940, "Conflict Reanalysis Attempt"
    ),
    GraphNode.RISK_AUTHORITY.value: NodeBox(470, 940, "Risk / Authority Gate"),
    GraphNode.FINALIZATION_GUARD.value: NodeBox(470, 1030, "Finalization Guard"),
    GraphNode.COMMITMENT_PROMOTION.value: NodeBox(
        470, 1120, "Commitment Promotion"
    ),
    GraphNode.HUMAN_REVIEW_CHECKPOINT.value: NodeBox(
        850, 670, "Human Review Checkpoint"
    ),
    GraphNode.HUMAN_REVIEW_INTERRUPT.value: NodeBox(
        850, 760, "Human Review Interrupt"
    ),
    GraphNode.HUMAN_REWORK_ATTEMPT.value: NodeBox(
        850, 850, "Human-Guided Rework"
    ),
}

MAP_EDGES = EDGE_KEYS


def _edge_path(source: NodeBox, target: NodeBox) -> str:
    source_cx = source.x + NODE_WIDTH / 2
    source_cy = source.y + NODE_HEIGHT / 2
    target_cx = target.x + NODE_WIDTH / 2
    target_cy = target.y + NODE_HEIGHT / 2

    if target.y >= source.y + NODE_HEIGHT:
        start_x, start_y = source_cx, source.y + NODE_HEIGHT
        end_x, end_y = target_cx, target.y
        bend_y = (start_y + end_y) / 2
        return (
            f"M {start_x:.1f} {start_y:.1f} "
            f"C {start_x:.1f} {bend_y:.1f}, {end_x:.1f} {bend_y:.1f}, "
            f"{end_x:.1f} {end_y:.1f}"
        )

    direction = -1 if target_cx < source_cx else 1
    start_x = source.x if direction < 0 else source.x + NODE_WIDTH
    end_x = target.x + NODE_WIDTH if direction < 0 else target.x
    offset = 70 * direction
    return (
        f"M {start_x:.1f} {source_cy:.1f} "
        f"C {start_x + offset:.1f} {source_cy:.1f}, "
        f"{end_x - offset:.1f} {target_cy:.1f}, {end_x:.1f} {target_cy:.1f}"
    )


def render_architecture_html(
    node_status: dict[str, str],
    *,
    edge_status: dict[tuple[str, str], str] | None = None,
    attempt_counts: dict[str, int] | None = None,
    live_node: str | None = None,
) -> str:
    """Return one accessible, responsive HTML/SVG architecture fragment."""

    validate_node_status(node_status)
    if edge_status is None:
        edge_status = initial_edge_status()
    validate_edge_status(edge_status)
    if attempt_counts is None:
        attempt_counts = initial_attempt_counts()
    validate_attempt_counts(attempt_counts)
    if live_node is not None and live_node not in NODE_LAYOUT:
        raise ValueError("live node must be a canonical architecture node")

    if live_node is None:
        live_text = "Current snapshot"
        live_status = ""
    else:
        live_status = node_status[live_node]
        live_text = (
            f"Now: {NODE_LAYOUT[live_node].label} — "
            f"{live_status.replace('_', ' ').title()}"
        )
    status_variables = "\n".join(
        (
            f"    --rfp-status-{status.replace('_', '-')}: "
            f"light-dark({visual.light_color}, {visual.dark_color});"
        )
        for status, visual in STATUS_VISUALS.items()
    )
    status_selectors = "\n".join(
        (
            f'      [data-status="{status}"] {{ '
            f"--rfp-node-color: var(--rfp-status-{status.replace('_', '-')}); }}"
        )
        for status in STATUS_VISUALS
    )
    legend_markup = "\n".join(
        (
            f'<span class="rfp-map-legend-item" role="listitem" '
            f'data-status="{escape(status)}">'
            f'<span class="rfp-map-legend-swatch" aria-hidden="true"></span>'
            f'{escape(visual.color_name.title())} — {escape(visual.legend_label)}</span>'
        )
        for status, visual in STATUS_VISUALS.items()
    )
    marker_markup = "\n".join(
        (
            f'<marker id="rfp-map-arrow-{status.replace("_", "-")}" '
            f'markerWidth="8" markerHeight="8" refX="7" refY="4" '
            f'orient="auto" markerUnits="strokeWidth">'
            f'<path class="rfp-map-arrowhead" data-status="{status}" '
            f'd="M 0 0 L 8 4 L 0 8 z" /></marker>'
        )
        for status in STATUS_VISUALS
    )
    edge_markup = "\n".join(
        (
            f'<path class="rfp-map-edge" data-edge="{source}--{target}" '
            f'data-status="{edge_status[(source, target)]}" '
            f'marker-end="url(#rfp-map-arrow-'
            f'{edge_status[(source, target)].replace("_", "-")})" '
            f'd="{_edge_path(NODE_LAYOUT[source], NODE_LAYOUT[target])}" />'
        )
        for source, target in MAP_EDGES
    )
    node_markup_parts: list[str] = []
    for node, box in NODE_LAYOUT.items():
        attempt_count = attempt_counts.get(node)
        attempt_limit = ATTEMPT_COUNTER_LIMITS.get(node)
        attempt_label = (
            f"; attempts: {attempt_count} of {attempt_limit}"
            if attempt_count is not None and attempt_limit is not None
            else ""
        )
        attempt_markup = (
            f'<text class="rfp-map-attempt" '
            f'x="{box.x + NODE_WIDTH / 2:.1f}" y="{box.y + 58}" '
            f'text-anchor="middle">Attempts: {attempt_count}/{attempt_limit}</text>'
            if attempt_count is not None and attempt_limit is not None
            else ""
        )
        node_markup_parts.append(
            f'<g class="rfp-map-node" data-node="{escape(node)}" '
            f'data-status="{escape(node_status[node])}" '
            f'data-current-event="{str(node == live_node).lower()}" '
            f'aria-label="{escape(box.label)}: {escape(node_status[node])}'
            f'{escape(attempt_label)}">'
            f'<rect x="{box.x}" y="{box.y}" width="{NODE_WIDTH}" '
            f'height="{NODE_HEIGHT}" rx="8" />'
            f'<text x="{box.x + NODE_WIDTH / 2:.1f}" y="{box.y + 24}" '
            f'text-anchor="middle">{escape(box.label)}</text>'
            f'<text class="rfp-map-status" x="{box.x + NODE_WIDTH / 2:.1f}" '
            f'y="{box.y + 43}" text-anchor="middle">'
            f'{escape(node_status[node].replace("_", " ").title())}</text>'
            f'{attempt_markup}'
            f'</g>'
        )
    node_markup = "\n".join(node_markup_parts)
    return f"""
<style>
  :root {{
    color-scheme: light dark;
{status_variables}
  }}
  body {{
    margin: 0;
    color: CanvasText;
    background: transparent;
    font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
  }}
</style>
<div id="rfp-architecture-map" class="rfp-architecture-map"
     aria-busy="{str(live_node is not None).lower()}">
  <div class="rfp-map-live" role="status" aria-live="polite" aria-atomic="true"
       data-live-node="{escape(live_node or '')}"
       data-status="{escape(live_status)}">{escape(live_text)}</div>
  <div class="rfp-map-legend" role="list"
       aria-label="Node and arrow execution status colors">
    {legend_markup}
  </div>
  <svg viewBox="0 0 {SVG_WIDTH} {SVG_HEIGHT + NODE_HEIGHT + 20}"
       role="img" aria-labelledby="rfp-map-title rfp-map-description"
       preserveAspectRatio="xMidYMin meet">
    <title id="rfp-map-title">Enterprise RFP orchestration architecture</title>
    <desc id="rfp-map-description">Twenty-one orchestration nodes with peer Product,
    Security, and Implementation specialists, recovery paths, human review, and
    finalization. Each node includes its current execution status as text.</desc>
    <defs>
      {marker_markup}
    </defs>
    <style>
{status_selectors}
      .rfp-map-edge {{
        fill: none;
        stroke: var(--rfp-node-color);
        stroke-opacity: 0.08;
        stroke-width: 1;
        transition: stroke 180ms ease, stroke-opacity 180ms ease,
          stroke-width 180ms ease;
      }}
      .rfp-map-edge[data-status="complete"] {{
        stroke-opacity: 0.42;
        stroke-width: 1.8;
      }}
      .rfp-map-edge[data-status="active"],
      .rfp-map-edge[data-status="recovery"],
      .rfp-map-edge[data-status="blocked"],
      .rfp-map-edge[data-status="state_access"] {{
        stroke-opacity: 0.95;
        stroke-width: 3;
      }}
      .rfp-map-arrowhead {{
        fill: var(--rfp-node-color);
        fill-opacity: 0.12;
        transition: fill 180ms ease, fill-opacity 180ms ease;
      }}
      .rfp-map-arrowhead[data-status="complete"] {{ fill-opacity: 0.55; }}
      .rfp-map-arrowhead[data-status="active"],
      .rfp-map-arrowhead[data-status="recovery"],
      .rfp-map-arrowhead[data-status="blocked"],
      .rfp-map-arrowhead[data-status="state_access"] {{ fill-opacity: 1; }}
      .rfp-map-node rect {{
        fill: var(--rfp-node-color);
        fill-opacity: 0.12;
        stroke: var(--rfp-node-color);
        stroke-opacity: 0.9;
        stroke-width: 2;
        transition: fill 180ms ease, stroke 180ms ease, stroke-width 180ms ease;
      }}
      .rfp-map-node[data-current-event="true"] rect {{ stroke-width: 3; }}
      .rfp-map-node text {{
        fill: CanvasText;
        font-family: inherit;
        font-size: 14px;
        font-weight: 500;
      }}
      .rfp-map-node .rfp-map-status {{
        fill: var(--rfp-node-color);
        font-size: 11px;
        font-weight: 500;
        transition: fill 180ms ease;
      }}
      .rfp-map-node .rfp-map-attempt {{
        fill: CanvasText;
        font-size: 10px;
        font-weight: 400;
      }}
      .rfp-architecture-map svg {{
        display: block;
        width: 100%;
        max-width: {SVG_WIDTH}px;
        height: auto;
        margin: 0 auto;
        color: inherit;
      }}
      @media (prefers-reduced-motion: reduce) {{
        .rfp-map-node rect,
        .rfp-map-node .rfp-map-status,
        .rfp-map-edge,
        .rfp-map-arrowhead {{ transition: none; }}
      }}
    </style>
    {edge_markup}
    {node_markup}
  </svg>
</div>
<style>
  .rfp-map-live {{
    min-height: 20px;
    margin: 0 0 8px;
    color: CanvasText;
    font-size: 12px;
    font-weight: 500;
  }}
  .rfp-map-live[data-live-node]:not([data-live-node=""]) {{
    color: var(--rfp-node-color);
  }}
  .rfp-map-legend {{
    display: flex;
    flex-wrap: wrap;
    gap: 8px 18px;
    align-items: center;
    margin: 0 0 10px;
    color: CanvasText;
    font-size: 12px;
  }}
  .rfp-map-legend-item {{
    display: inline-flex;
    gap: 6px;
    align-items: center;
  }}
  .rfp-map-legend-swatch {{
    display: inline-block;
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--rfp-node-color);
  }}
</style>
""".strip()
