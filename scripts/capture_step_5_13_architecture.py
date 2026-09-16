"""Prepare and verify the static map capture and approved metrics table."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image

from rfp_orchestrator.architecture_map import STATUS_VISUALS, render_architecture_html
from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.ui import stream_sample_requirement

ROOT = Path(__file__).resolve().parents[1]
APPROVAL = ROOT / "data/evaluation/provider_evaluation_final_approval_step_4_g8.json"
ANALYSIS_JSON = ROOT / "outputs/evaluation/provider_evaluation_final_step_4_g8.json"
ANALYSIS_MD = ROOT / "outputs/evaluation/provider_evaluation_final_step_4_g8.md"
METRICS_MD = ROOT / "docs/evaluation_metrics_v1.md"
SCREENSHOT = ROOT / "docs/architecture_execution_rfp002.png"
SCREENSHOT_NOTES = ROOT / "docs/architecture_execution_rfp002.md"
SVG_SOURCE = ROOT / "outputs/demo/architecture_execution_rfp002.svg"
SCREENSHOT_SIZE = (1800, 1800)


def _approved_summaries() -> tuple[dict, dict, dict]:
    approval = json.loads(APPROVAL.read_text(encoding="utf-8"))
    if approval["decision"] != "APPROVED" or not approval["phase_4_exit_gate_passed"]:
        raise ValueError("final evaluation does not have recorded human approval")
    for path, key in (
        (ANALYSIS_JSON, "analysis_json_sha256"),
        (ANALYSIS_MD, "analysis_markdown_sha256"),
    ):
        if hashlib.sha256(path.read_bytes()).hexdigest() != approval[key]:
            raise ValueError(f"approved analysis checksum mismatch: {path.name}")
    analysis = json.loads(ANALYSIS_JSON.read_text(encoding="utf-8"))
    summaries = {item["architecture"]: item for item in analysis["primary_architecture_headlines"]}
    return analysis, summaries["single_generalist"], summaries[
        "orchestrated_peer_specialists"
    ]


def _verify_metrics_table(analysis: dict, generalist: dict, peers: dict) -> None:
    text = METRICS_MD.read_text(encoding="utf-8")

    def safe(row: dict) -> str:
        numerator = row["safe_completion_numerator"]
        denominator = row["safe_completion_denominator"]
        return f"{numerator}/{denominator} ({numerator / denominator:.1%})"

    def execution(row: dict) -> str:
        return f"{row['execution_success_numerator']}/{row['execution_success_denominator']}"

    fields = (
        ("Safe Completion Rate", safe),
        ("Execution success", execution),
        ("Routing macro F1", lambda row: f"{row['routing_macro_f1']:.3f}"),
        ("Evidence Recall@5", lambda row: f"{row['evidence_recall_at_5']:.3f}"),
        ("Unsupported-claim rate", lambda row: f"{row['unsupported_claim_rate']:.1%}"),
        ("Groundedness", lambda row: f"{row['groundedness']:.1%}"),
        ("HITL F1", lambda row: f"{row['hitl_f1']:.3f}"),
        ("Conflict-detection F1", lambda row: f"{row['conflict_detection_f1']:.3f}"),
        ("Recovery-detection F1", lambda row: f"{row['recovery_detection_f1']:.3f}"),
        ("Observed mean latency", lambda row: f"{row['observed_mean_latency_ms']:,.0f} ms"),
        (
            "Observed estimated generation cost",
            lambda row: f"${row['observed_estimated_cost_usd']:.6f}",
        ),
        ("Preserved primary failures", lambda row: str(row["preserved_primary_failures"])),
    )
    for label, formatter in fields:
        expected = f"| {label} | {formatter(generalist)} | {formatter(peers)} |"
        if expected not in text:
            raise ValueError(f"metrics table differs from approved analysis: {label}")
    if analysis["bounded_preference"] != "single_generalist_for_frozen_v1":
        raise ValueError("unexpected bounded architecture preference")
    if analysis["cumulative_generation_calls"] != 128:
        raise ValueError("unexpected frozen call ceiling")


def _map_fragment() -> str:
    requirement = next(
        item for item in load_sample_requirements() if item.requirement_id == "RFP-002"
    )
    run = stream_sample_requirement(requirement, 1, "step-5-13-static-capture")
    if run.state["final_status"] != "FINALIZED":
        raise ValueError("RFP-002 did not finalize")
    if run.state["selected_specialists"] != ["product", "security"]:
        raise ValueError("RFP-002 did not use the approved peer route")
    for node, expected in (
        ("product_specialist", "complete"),
        ("security_specialist", "complete"),
        ("implementation_specialist", "inactive"),
    ):
        if run.node_status[node] != expected:
            raise ValueError(f"unexpected map state for {node}")
    for edge, expected in (
        (("strategy_orchestrator", "product_specialist"), "complete"),
        (("strategy_orchestrator", "security_specialist"), "complete"),
        (("strategy_orchestrator", "implementation_specialist"), "inactive"),
        (("product_specialist", "merge"), "complete"),
        (("security_specialist", "merge"), "complete"),
        (("implementation_specialist", "merge"), "inactive"),
    ):
        if run.edge_status[edge] != expected:
            raise ValueError(f"unexpected map edge state for {edge}")
    return render_architecture_html(
        run.node_status,
        edge_status=run.edge_status,
        attempt_counts=run.attempt_counts,
    )


def _verify_screenshot() -> None:
    with Image.open(SCREENSHOT) as image:
        if image.size != SCREENSHOT_SIZE or image.format != "PNG":
            raise ValueError("architecture screenshot has unexpected format or dimensions")
        image.verify()
    digest = hashlib.sha256(SCREENSHOT.read_bytes()).hexdigest()
    if digest not in SCREENSHOT_NOTES.read_text(encoding="utf-8"):
        raise ValueError("architecture screenshot checksum differs from its provenance note")


def _standalone_svg(fragment: str) -> str:
    """Flatten the implemented map's CSS colors for local vector rendering."""

    match = re.search(r"<svg\b.*?</svg>", fragment, flags=re.DOTALL)
    if match is None:
        raise ValueError("implemented map HTML has no SVG")
    svg = ElementTree.fromstring(match.group(0))
    svg.set("xmlns", "http://www.w3.org/2000/svg")
    svg.set("width", "1200")
    svg.set("height", "1248")
    background = ElementTree.Element("rect", {"width": "1200", "height": "1248", "fill": "#ffffff"})
    svg.insert(0, background)
    for path in svg.findall(".//path"):
        status = path.attrib.get("data-status", "inactive")
        color = STATUS_VISUALS[status].light_color
        if "data-edge" in path.attrib:
            opacity = "0.42" if status == "complete" else "0.08" if status == "inactive" else "0.95"
            width = "1.8" if status == "complete" else "1" if status == "inactive" else "3"
            path.set("style", f"fill:none;stroke:{color};stroke-opacity:{opacity};stroke-width:{width}")
        else:
            opacity = "0.55" if status == "complete" else "0.12" if status == "inactive" else "1"
            path.set("style", f"fill:{color};fill-opacity:{opacity}")
    for group in svg.findall(".//g"):
        status = group.attrib["data-status"]
        color = STATUS_VISUALS[status].light_color
        rect = group.find("rect")
        if rect is None:
            raise ValueError("map node has no rectangle")
        rect.set("style", f"fill:{color};fill-opacity:0.12;stroke:{color};stroke-width:2")
        for label in group.findall("text"):
            text_color = color if label.attrib.get("class") == "rfp-map-status" else "#111827"
            label.set("style", f"fill:{text_color};font-family:Arial,sans-serif")
    return ElementTree.tostring(svg, encoding="unicode")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-svg", action="store_true", help="write ignored SVG source")
    args = parser.parse_args()
    analysis, generalist, peers = _approved_summaries()
    _verify_metrics_table(analysis, generalist, peers)
    fragment = _map_fragment()

    if args.prepare_svg:
        svg = _standalone_svg(fragment)
        SVG_SOURCE.parent.mkdir(parents=True, exist_ok=True)
        if SVG_SOURCE.exists():
            if SVG_SOURCE.read_text(encoding="utf-8") != svg:
                raise FileExistsError("existing map SVG differs; inspect before replacing")
        else:
            SVG_SOURCE.write_text(svg, encoding="utf-8")
        print(f"Prepared local, synthetic map SVG: {SVG_SOURCE}")
        return

    _verify_screenshot()
    print("Approved metrics table and RFP-002 architecture screenshot verified.")
    print(f"Screenshot SHA-256: {hashlib.sha256(SCREENSHOT.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
