"""Generate the beginner-readable Step 1.29 offline retrieval inspection report."""

from __future__ import annotations

import argparse
import re
from dataclasses import dataclass
from pathlib import Path

from rfp_orchestrator.models import Domain
from rfp_orchestrator.retrieval import EvidenceChunk, build_offline_retrievers

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KB_DIRECTORY = PROJECT_ROOT / "data" / "kb"
DEFAULT_OUTPUT_PATH = PROJECT_ROOT / "outputs" / "retrieval_inspection_step_1_29.md"


@dataclass(frozen=True)
class InspectionCase:
    label: str
    domain: Domain
    query: str
    review_focus: str
    excerpt_phrases: tuple[str, ...]


INSPECTION_CASES = (
    InspectionCase(
        label="Product",
        domain=Domain.PRODUCT,
        query="Can employees use SAML 2.0 and be provisioned automatically with SCIM 2.0?",
        review_focus=(
            "The capability and availability sources should lead, and every result must "
            "remain in the Product domain."
        ),
        excerpt_phrases=("saml", "scim", "user provisioning", "provisioned"),
    ),
    InspectionCase(
        label="Security/Compliance",
        domain=Domain.SECURITY,
        query="What is the post-termination data retention and deletion recovery window?",
        review_focus=(
            "Both current, equal-authority 30-day and 90-day sources must remain visible; "
            "retrieval must not silently choose one."
        ),
        excerpt_phrases=(
            "30 calendar days",
            "30-calendar-day",
            "90 calendar days",
            "90-calendar-day",
            "conflict",
        ),
    ),
    InspectionCase(
        label="Implementation",
        domain=Domain.IMPLEMENTATION,
        query="How long does onboarding take and who must participate from the customer team?",
        review_focus=(
            "The implementation guide should surface the six-to-eight-week qualification "
            "and customer responsibilities."
        ),
        excerpt_phrases=(
            "six to eight weeks",
            "six-to-eight-week",
            "customer provides",
            "executive sponsor",
        ),
    ),
)


def run_inspection(
    kb_directory: str | Path = DEFAULT_KB_DIRECTORY,
) -> dict[str, list[EvidenceChunk]]:
    """Run the three frozen offline searches with the domain-locked Top-5 boundary."""

    retrievers = build_offline_retrievers(kb_directory)
    return {
        case.label: getattr(retrievers, case.domain.value).search(case.query, k=5)
        for case in INSPECTION_CASES
    }


def _excerpt(
    text: str,
    phrases: tuple[str, ...],
    max_chars: int = 420,
) -> str:
    compact = " ".join(text.split())
    sentences = re.split(r"(?<=[.!?])\s+", compact)
    selected = [
        sentence
        for sentence in sentences
        if any(phrase in sentence.lower() for phrase in phrases)
    ][:2]
    excerpt = " ".join(selected or sentences[:1]).replace("|", "\\|")
    if len(excerpt) <= max_chars:
        return excerpt
    return excerpt[: max_chars - 1].rstrip() + "…"


def render_report(results: dict[str, list[EvidenceChunk]]) -> str:
    """Render a complete Markdown report without credentials or vector values."""

    lines = [
        "# Step 1.29 — Representative Top-5 Retrieval Inspection",
        "",
        (
            "This report uses the deterministic offline retrieval path. It makes zero "
            "OpenAI or Pinecone calls. Product and Security/Compliance are labeled "
            "`hybrid`; Implementation uses the explicitly labeled `semantic_substitute` "
            "until a live provider query is separately approved."
        ),
        "",
    ]
    for case in INSPECTION_CASES:
        case_results = results[case.label]
        lines.extend(
            [
                f"## {case.label}",
                "",
                f"**Query:** {case.query}",
                "",
                f"**Review focus:** {case.review_focus}",
                "",
                (
                    "| Rank | Citation ID | Title | Method | Score | Authority | Status | "
                    "Effective date | Evidence excerpt |"
                ),
                "|---:|---|---|---|---:|---:|---|---|---|",
            ]
        )
        for rank, result in enumerate(case_results, start=1):
            lines.append(
                f"| {rank} | `{result.chunk_id}` | {result.title} v{result.version} | "
                f"`{result.retrieval_method.value}` | {result.score:.6f} | "
                f"{result.authority_rank} | `{result.source_status}` | "
                f"{result.effective_date} | "
                f"{_excerpt(result.text, case.excerpt_phrases)} |"
            )
        if not case_results:
            lines.append("| — | — | No evidence returned | — | — | — | — | — | — |")
        lines.append("")

    lines.extend(
        [
            "## Human review checklist",
            "",
            "- [ ] Product order and citations make sense.",
            "- [ ] Security/Compliance retains both conflicting retention values.",
            "- [ ] Implementation evidence includes the qualified timeline and customer roles.",
            "- [ ] Every result stays inside its requested domain.",
            "- [ ] Method, score, authority, lifecycle status, version, date, and passage are visible.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT_PATH,
        help="Markdown report path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = render_report(run_inspection())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(report)
    print(f"Saved report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
