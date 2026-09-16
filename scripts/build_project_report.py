"""Build the submission-draft RFP project report as a self-contained PDF.

This intentionally uses only the standard library and Pillow because the
local Mac lacks reportlab/Poppler and package-network access. It makes no
provider call, reads no .env file, and does not run the application graph.
"""

from __future__ import annotations

import io
import unicodedata
import zlib
from dataclasses import dataclass, field
from pathlib import Path

from PIL import Image, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "Enterprise_RFP_Response_Orchestrator_Project_Report.pdf"
MAP_IMAGE = ROOT / "docs" / "architecture_execution_rfp002.png"

PAGE_W, PAGE_H = 612, 792
LEFT, RIGHT, TOP, BOTTOM = 62, 550, 731, 66
BODY_W = RIGHT - LEFT
NAVY = (0.10, 0.20, 0.34)
BLUE = (0.17, 0.38, 0.64)
TEAL = (0.08, 0.53, 0.51)
PALE = (0.92, 0.95, 0.98)
LIGHT = (0.97, 0.98, 0.99)
GRAY = (0.35, 0.39, 0.44)
BLACK = (0.06, 0.08, 0.10)


def ascii_text(value: object) -> str:
    text = str(value)
    for src, dst in {
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
        "\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"',
        "\u2022": "-", "\u00d7": "x", "\u2265": ">=", "\u2264": "<=",
    }.items():
        text = text.replace(src, dst)
    return unicodedata.normalize("NFKD", text).encode("ascii", "replace").decode("ascii")


def pdf_string(value: object) -> str:
    text = ascii_text(value)
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def rgb(color: tuple[float, float, float]) -> str:
    return " ".join(f"{part:.3f}" for part in color)


FONT_PATHS = {
    "regular": Path("/System/Library/Fonts/Supplemental/Arial.ttf"),
    "bold": Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf"),
    "italic": Path("/System/Library/Fonts/Supplemental/Arial Italic.ttf"),
}


def text_width(text: str, size: float, font: str = "regular") -> float:
    path = FONT_PATHS.get(font, FONT_PATHS["regular"])
    if path.exists():
        face = ImageFont.truetype(str(path), max(8, round(size * 4)))
        return face.getlength(ascii_text(text)) / 4
    return len(ascii_text(text)) * size * (0.54 if font == "regular" else 0.59)


def wrap(text: str, width: float, size: float, font: str = "regular") -> list[str]:
    words = ascii_text(text).split()
    if not words:
        return [""]
    lines: list[str] = []
    current = ""
    for raw in words:
        pieces = [raw]
        while pieces and text_width(pieces[0], size, font) > width:
            word = pieces.pop(0)
            split = max(1, len(word) - 1)
            while split > 1 and text_width(word[:split] + "-", size, font) > width:
                split -= 1
            pieces.insert(0, word[split:])
            pieces.insert(0, word[:split] + "-")
        for word in pieces:
            trial = f"{current} {word}" if current else word
            if current and text_width(trial, size, font) > width:
                lines.append(current)
                current = word
            else:
                current = trial
    if current:
        lines.append(current)
    return lines


@dataclass
class Page:
    commands: list[str] = field(default_factory=list)
    y: float = TOP

    def text(
        self,
        x: float,
        y: float,
        value: str,
        size: float = 9.3,
        font: str = "regular",
        color: tuple[float, float, float] = BLACK,
    ) -> None:
        font_key = {"regular": "F1", "bold": "F2", "italic": "F3"}[font]
        self.commands.append(
            f"{rgb(color)} rg BT /{font_key} {size:.2f} Tf 1 0 0 1 "
            f"{x:.2f} {y:.2f} Tm ({pdf_string(value)}) Tj ET"
        )

    def line(
        self,
        x1: float,
        y1: float,
        x2: float,
        y2: float,
        color: tuple[float, float, float] = GRAY,
        width: float = 0.6,
    ) -> None:
        self.commands.append(
            f"{rgb(color)} RG {width:.2f} w {x1:.2f} {y1:.2f} m "
            f"{x2:.2f} {y2:.2f} l S"
        )

    def rect(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        fill: tuple[float, float, float] = (1, 1, 1),
        stroke: tuple[float, float, float] = (0.78, 0.81, 0.84),
    ) -> None:
        self.commands.append(
            f"{rgb(fill)} rg {rgb(stroke)} RG 0.55 w "
            f"{x:.2f} {y:.2f} {w:.2f} {h:.2f} re B"
        )


class Report:
    def __init__(self) -> None:
        self.pages: list[Page] = []
        self.page = self.new_page(cover=True)

    def new_page(self, cover: bool = False) -> Page:
        page = Page()
        page.rect(0, 0, PAGE_W, PAGE_H, (1, 1, 1), (1, 1, 1))
        self.pages.append(page)
        self.page = page
        if not cover:
            page.text(LEFT, 760, "ENTERPRISE RFP RESPONSE ORCHESTRATOR  /  PROJECT REPORT", 7.4, "bold", GRAY)
            page.line(LEFT, 750, RIGHT, 750, (0.77, 0.82, 0.87))
        return page

    def ensure(self, height: float) -> None:
        if self.page.y - height < BOTTOM:
            self.new_page()

    def section(self, number: str, title: str) -> None:
        self.ensure(57)
        self.page.y -= 10
        self.page.text(LEFT, self.page.y, f"{number}. {title}", 15.0, "bold", NAVY)
        self.page.y -= 25

    def sub(self, number: str, title: str) -> None:
        self.ensure(39)
        self.page.y -= 4
        self.page.text(LEFT, self.page.y, f"{number} {title}", 10.9, "bold", BLACK)
        self.page.y -= 17

    def para(self, text: str, *, size: float = 9.2, leading: float = 13.0, after: float = 8.0) -> None:
        lines = wrap(text, BODY_W, size)
        for line in lines:
            self.ensure(leading)
            self.page.text(LEFT, self.page.y, line, size)
            self.page.y -= leading
        self.page.y -= after

    def bullet(self, text: str, *, size: float = 9.0) -> None:
        lines = wrap(text, BODY_W - 17, size)
        self.ensure(len(lines) * 12.5 + 6)
        self.page.text(LEFT + 1, self.page.y, "-", size, "bold")
        for line in lines:
            self.page.text(LEFT + 17, self.page.y, line, size)
            self.page.y -= 12.5
        self.page.y -= 5

    def note(self, text: str, *, fill: tuple[float, float, float] = PALE) -> None:
        lines = wrap(text, BODY_W - 22, 8.8)
        height = len(lines) * 12.4 + 18
        self.ensure(height + 7)
        self.page.rect(LEFT, self.page.y - height + 6, BODY_W, height, fill, (0.74, 0.82, 0.90))
        for line in lines:
            self.page.text(LEFT + 11, self.page.y - 9, line, 8.8, "regular", NAVY)
            self.page.y -= 12.4
        self.page.y -= 15

    def table(
        self,
        headers: list[str],
        rows: list[list[str]],
        widths: list[float],
        *,
        size: float = 8.0,
    ) -> None:
        assert abs(sum(widths) - BODY_W) < 0.01
        line_h = size + 3.2

        def draw_row(values: list[str], is_header: bool, alternate: bool) -> None:
            wrapped = [wrap(v, width - 12, size, "bold" if is_header else "regular") for v, width in zip(values, widths)]
            height = max(23, max(len(lines) for lines in wrapped) * line_h + 11)
            if self.page.y - height < BOTTOM:
                self.new_page()
                draw_row(headers, True, False)
            x = LEFT
            fill = PALE if is_header else (LIGHT if alternate else (1, 1, 1))
            for lines, width in zip(wrapped, widths):
                self.page.rect(x, self.page.y - height, width, height, fill)
                yy = self.page.y - 10 - size
                for line in lines:
                    self.page.text(x + 6, yy, line, size, "bold" if is_header else "regular")
                    yy -= line_h
                x += width
            self.page.y -= height

        self.ensure(46)
        draw_row(headers, True, False)
        for index, row in enumerate(rows):
            draw_row(row, False, index % 2 == 1)
        self.page.y -= 13

    def caption(self, text: str) -> None:
        lines = wrap(text, BODY_W, 8.0, "italic")
        self.ensure(len(lines) * 11 + 10)
        for line in lines:
            self.page.text(LEFT, self.page.y, line, 8.0, "italic", GRAY)
            self.page.y -= 11
        self.page.y -= 8

    def box(self, x: float, y: float, w: float, h: float, label: str, fill: tuple[float, float, float]) -> None:
        self.page.rect(x, y, w, h, fill, (0.56, 0.68, 0.78))
        lines = wrap(label, w - 12, 8.0, "bold")
        top = y + h / 2 + (len(lines) - 1) * 5
        for line in lines:
            tx = x + (w - text_width(line, 8.0, "bold")) / 2
            self.page.text(tx, top, line, 8.0, "bold", NAVY)
            top -= 10

    def arrow(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.page.line(x1, y1, x2, y2, BLUE, 1.2)
        if abs(x2 - x1) > abs(y2 - y1):
            sign = 1 if x2 > x1 else -1
            self.page.line(x2 - 5 * sign, y2 + 3, x2, y2, BLUE, 1.2)
            self.page.line(x2 - 5 * sign, y2 - 3, x2, y2, BLUE, 1.2)
        else:
            sign = 1 if y2 > y1 else -1
            self.page.line(x2 - 3, y2 - 5 * sign, x2, y2, BLUE, 1.2)
            self.page.line(x2 + 3, y2 - 5 * sign, x2, y2, BLUE, 1.2)

    def architecture_figure(self) -> None:
        self.ensure(326)
        top = self.page.y
        self.box(LEFT + 4, top - 52, 105, 40, "Untrusted RFP", PALE)
        self.box(LEFT + 137, top - 52, 101, 40, "Analyze + route", PALE)
        self.box(LEFT + 269, top - 52, 136, 40, "Strategy orchestrator", PALE)
        self.arrow(LEFT + 109, top - 32, LEFT + 137, top - 32)
        self.arrow(LEFT + 238, top - 32, LEFT + 269, top - 32)
        for x, label, fill in (
            (LEFT + 17, "Product", (0.88, 0.94, 0.99)),
            (LEFT + 178, "Security / Compliance", (0.88, 0.97, 0.95)),
            (LEFT + 339, "Implementation", (0.95, 0.91, 0.99)),
        ):
            self.box(x, top - 132, 133, 43, label, fill)
        for x in (LEFT + 84, LEFT + 245, LEFT + 405):
            self.page.line(LEFT + 337, top - 52, LEFT + 337, top - 75, BLUE, 1.0)
            self.page.line(x, top - 75, LEFT + 337, top - 75, BLUE, 1.0)
            self.arrow(x, top - 75, x, top - 89)
        self.box(LEFT + 172, top - 196, 145, 39, "Merge selected peers", PALE)
        for x in (LEFT + 84, LEFT + 245, LEFT + 405):
            self.page.line(x, top - 132, x, top - 145, BLUE, 1.0)
            self.page.line(x, top - 145, LEFT + 245, top - 145, BLUE, 1.0)
        self.arrow(LEFT + 245, top - 145, LEFT + 245, top - 157)
        self.box(LEFT + 28, top - 267, 203, 43, "Citation, source, claim, and consistency checks", LIGHT)
        self.box(LEFT + 259, top - 267, 201, 43, "Risk / authority gate", LIGHT)
        self.arrow(LEFT + 245, top - 196, LEFT + 245, top - 210)
        self.page.line(LEFT + 245, top - 210, LEFT + 129, top - 210, BLUE, 1.0)
        self.arrow(LEFT + 129, top - 210, LEFT + 129, top - 224)
        self.arrow(LEFT + 231, top - 245, LEFT + 259, top - 245)
        self.page.text(LEFT + 16, top - 296, "Bounded recovery (2), conflict reanalysis (1), then guarded finalization or HITL.", 8.0, "italic", GRAY)
        self.page.y = top - 317
        self.caption("Figure 1. V1 peer-specialist topology and hard gates. The selected specialists fan out and merge; there are no specialist-to-specialist edges. [1, 8]")

    def image(self, path: Path, *, width: float, caption: str) -> None:
        height = width
        self.ensure(height + 38)
        x = LEFT + (BODY_W - width) / 2
        y = self.page.y - height
        self.page.commands.append(f"q {width:.2f} 0 0 {height:.2f} {x:.2f} {y:.2f} cm /Im1 Do Q")
        self.page.y = y - 9
        self.caption(caption)

    def comparison_bars(self) -> None:
        self.ensure(196)
        data = [
            ("Safe completion", 83.3, 41.7),
            ("Execution success", 100.0, 83.3),
            ("Evidence Recall@5", 94.4, 78.6),
            ("Groundedness", 98.5, 69.8),
        ]
        self.page.text(LEFT, self.page.y, "Single generalist", 8.0, "bold", BLUE)
        self.page.text(LEFT + 140, self.page.y, "Orchestrated peers", 8.0, "bold", TEAL)
        self.page.y -= 17
        for label, single, peers in data:
            self.page.text(LEFT, self.page.y, label, 8.0, "bold")
            self.page.y -= 10
            self.page.rect(LEFT, self.page.y - 7, 380 * single / 100, 7, BLUE, BLUE)
            self.page.text(LEFT + 390, self.page.y - 6, f"{single:.1f}%", 7.8, "bold", BLUE)
            self.page.y -= 12
            self.page.rect(LEFT, self.page.y - 7, 380 * peers / 100, 7, TEAL, TEAL)
            self.page.text(LEFT + 390, self.page.y - 6, f"{peers:.1f}%", 7.8, "bold", TEAL)
            self.page.y -= 23
        self.caption("Figure 3. Primary frozen 24-case comparison. Percentages are shown only for higher-is-better measures; see Table 4 for unsupported-claim rate and caveats. [5, 6]")


def write_pdf(report: Report) -> None:
    for page_number, page in enumerate(report.pages, start=1):
        page.line(LEFT, 49, RIGHT, 49, (0.80, 0.83, 0.87))
        page.text(LEFT, 35, "Synthetic portfolio prototype  |  Gaurav Asthana  |  September 2026", 7.0, "regular", GRAY)
        page.text(RIGHT - 63, 35, f"Page {page_number} / {len(report.pages)}", 7.0, "regular", GRAY)

    image = Image.open(MAP_IMAGE).convert("RGB")
    image_data = zlib.compress(image.tobytes(), 8)
    objects: list[bytes] = [b""] * 6
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objects[3] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>"
    objects[4] = b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Oblique >>"
    objects[5] = (
        f"<< /Type /XObject /Subtype /Image /Width {image.width} /Height {image.height} "
        f"/ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /FlateDecode /Length {len(image_data)} >>\n"
        .encode("ascii") + b"stream\n" + image_data + b"\nendstream"
    )
    page_numbers = []
    for page in report.pages:
        content = ("\n".join(page.commands) + "\n").encode("ascii")
        stream = (
            f"<< /Length {len(content)} >>\nstream\n".encode("ascii")
            + content + b"endstream"
        )
        content_num = len(objects) + 1
        objects.append(stream)
        page_num = len(objects) + 1
        page_numbers.append(page_num)
        objects.append(
            (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
             f"/Resources << /Font << /F1 3 0 R /F2 4 0 R /F3 5 0 R >> "
             f"/XObject << /Im1 6 0 R >> >> /Contents {content_num} 0 R >>").encode("ascii")
        )
    kids = " ".join(f"{number} 0 R" for number in page_numbers)
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(report.pages)} >>".encode("ascii")

    output = io.BytesIO()
    output.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(output.tell())
        output.write(f"{number} 0 obj\n".encode("ascii"))
        output.write(body)
        output.write(b"\nendobj\n")
    xref = output.tell()
    output.write(f"xref\n0 {len(objects)+1}\n0000000000 65535 f \n".encode("ascii"))
    for offset in offsets[1:]:
        output.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.write(
        f"trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode("ascii")
    )
    OUTPUT.write_bytes(output.getvalue())


def build_report() -> Report:
    r = Report()
    p = r.page
    p.text(LEFT, 708, "Enterprise RFP Response", 22, "bold", NAVY)
    p.text(LEFT, 682, "Orchestrator", 22, "bold", NAVY)
    p.text(LEFT, 653, "Agentic AI project report  |  Week 3 enterprise RFP use case", 9.2, "bold")
    p.text(LEFT, 633, "Prepared by Gaurav Asthana  |  September 16, 2026", 8.9)
    p.text(LEFT, 617, "Status: submission draft; final Step 5.17-5.19 checks are pending", 8.7, "italic", GRAY)
    p.y = 595
    r.note("Safety notice: This is a synthetic Northstar Cloud Systems prototype. It produces reviewable draft responses, not authorized legal, commercial, security-exception, roadmap, SLA, or customer-specific contractual commitments.")
    r.sub("", "Executive summary")
    r.para("This project built a LangGraph RFP-response workflow that routes each requirement to the minimum safe reasoning path: one specialist, selected independent peers, bounded recovery, targeted conflict reanalysis, guarded finalization, or a checkpointed human review. The Streamlit interface animates the actual node and arrow states and exports a simple DOCX. The data and customer-style requirements are entirely fictitious. [1, 2]")
    r.para("The evaluation used a frozen, human-approved 24-case synthetic gold set and compared the orchestrated peers with one generalist under shared provider, retrieval, safety, and scoring contracts. In the primary trial, the generalist achieved 20/24 Safe Completion (83.3%) versus 10/24 (41.7%) for the peers. It also completed 24/24 executions versus 20/24. The bounded preference is the generalist for this V1 experiment, not a claim that single-agent designs are always better. [4-6]")
    r.para("The result is deliberately not polished into a win for orchestration: all 19 full-run failures remain visible, the 128-generation-call ceiling censored the repeat set, and both arms had zero conflict-detection F1. Known RFP-006, RFP-015, and reviewer-action gaps remain open. The working offline demo proves dynamic control flow and safe stops; it is not the same as a live provider-backed proposal assistant. [1, 5, 6]")

    r.section("1", "Project overview")
    r.sub("1.1", "Application and intended user")
    r.para("The intended user is a proposal or solutions professional who needs a defensible first draft for a complex enterprise RFP. The prototype decomposes an untrusted requirement, chooses relevant Product, Security/Compliance, or Implementation expertise, retrieves domain-locked evidence, validates claims and citations, and exposes the reason for finalization or human escalation. The goal is decision traceability and safe drafting, not autonomous customer commitment. [1, 8]")
    r.sub("1.2", "Scope boundaries")
    r.bullet("In scope: synthetic requirement routing, Top-5 evidence search, independent specialist reasoning, bounded recovery and conflict checks, HITL checkpoints, live map, DOCX export, and a fair generalist baseline.")
    r.bullet("Out of scope: real customer data, live enterprise systems, autonomous pricing or SLA exceptions, production identity and governance, and post-submission architecture simplification.")
    r.bullet("The Streamlit demonstration is deterministic and offline; the separately approved evaluation used OpenAI generation and Pinecone retrieval. Their outcomes must not be conflated. [1]")

    r.section("2", "Synthetic dataset and evidence corpus")
    r.sub("2.1", "Trusted sources and untrusted input")
    r.para("The trusted Northstar knowledge base has 12 Markdown sources: four Product, seven Security/Compliance or policy, and one Implementation. Eleven are current; one archived TLS source tests lifecycle handling. The 24 customer-style RFP requirements are outside the trusted corpus and must be treated as untrusted input. Gold labels and fixture descriptions are also kept outside retrieval. [2, 3]")
    r.table(
        ["Corpus property", "V1 value", "Why it matters"],
        [
            ["Trusted sources", "12 synthetic Markdown documents", "Small enough to audit; multiple evidence domains"],
            ["Lifecycle", "11 current, 1 archived", "Stale evidence remains visible but cannot outrank current authority"],
            ["Customer-style input", "24 stable RFP IDs", "Untrusted text cannot rewrite agent policy"],
            ["Seeded conditions", "Missing FedRAMP High; 30/90-day conflict; archived TLS; roadmap; SLA exception", "Exercises evidence gaps, contradictions, and authority stops"],
            ["Source metadata", "ID, domain, lifecycle, authority", "Supports citation and source-validation gates"],
        ],
        [105, 153, 230],
        size=7.8,
    )
    r.sub("2.2", "Retrieval contract")
    r.para("Product and Security/Compliance use hybrid dense plus BM25/sparse retrieval, each returning at most five results. Implementation uses dense semantic Top 5 in the provider path; the offline UI substitutes a deterministic semantic scorer for repeatable tests. All searches are domain-locked. The OpenAI text-embedding-3-small and Pinecone dense index were configured in V1; provider calls were authorized only for bounded smoke, ingestion, and evaluation steps. [1, 8]")
    r.note("The small corpus demonstrates failure modes rather than large-scale throughput. It is not evidence that retrieval quality or latency will hold on a changing enterprise document estate.")

    r.new_page()
    r.section("3", "System architecture")
    r.architecture_figure()
    r.para("The Requirement Analyzer preserves the original input, extracts atomic needs, and flags prompt-injection signals. The Strategy Orchestrator selects a specialist subset; Product, Security/Compliance, and Implementation are peers with no direct specialist-to-specialist edges. A merge joins only invoked peers. Citation, source-authority, atomic-claim support, commitment consistency, risk, and authority checks determine whether a response can be finalized. [1, 8]")
    r.para("Claim.supported is a Boolean on each atomic claim. SpecialistOutput.support_status summarizes all claims as SUPPORTED, PARTIAL, or UNSUPPORTED. A narrow commitment ledger stores only selected human-approved finalized commitments, not broad conversation memory. Retrieval recovery is capped at two attempts; conflict reanalysis at one. Checkpointed human review prevents unsafe final answers until a valid decision resumes the exact saved state. [1, 8]")

    r.new_page()
    r.section("3", "Architecture execution in the app")
    r.image(MAP_IMAGE, width=455, caption="Figure 2. Actual offline RFP-002 execution-map capture: Product and Security completed as independent peers, Implementation inactive; observed arrows lead through merge and guarded finalization. Unused recovery and HITL routes stay gray. [9]")
    r.para("The live Streamlit map is driven by LangGraph execution events, not by a decorative animation. Colors distinguish inactive, active, complete, recovery, blocked/review, and state-access nodes; traversed arrows illuminate. The static image above records one finished cross-domain path, not every route and not a model-provider call. [1, 9]")

    r.section("4", "Build sequence and stack")
    r.table(
        ["Stage", "Purpose", "Principal tools"],
        [
            ["Foundation + data", "Local project, synthetic company, stable evidence fixtures", "Python, Markdown, pytest"],
            ["Retrieval", "Domain-locked hybrid/dense Top-5 contracts and Pinecone adapter", "OpenAI embeddings, Pinecone, BM25"],
            ["Orchestration", "Peer graph, validators, bounded recovery, commitments, HITL", "LangGraph, LangChain, Pydantic"],
            ["Interface", "Animated map, review controls, response export", "Streamlit, python-docx"],
            ["Evaluation", "24-case gold set, baseline, metrics, failure retention", "Provider runs, scripts, LangSmith"],
            ["Submission prep", "README, visuals, demo script, version and hygiene records", "VS Code, Codex, local QA"],
        ],
        [113, 224, 151],
        size=7.7,
    )
    r.para("The preferred V1 stack is Python, LangChain, LangGraph, OpenAI API, Pinecone, LangSmith, Streamlit, and python-docx. Mem0 and ElevenLabs were intentionally excluded, while Nebius remained optional. The local demo uses an in-memory checkpoint store, so review state is not durable across process restarts. [1, 8]")

    r.section("5", "Agent instructions and output contract")
    r.sub("5.1", "Instruction pattern")
    r.bullet("Preserve customer requirement text for audit but never treat embedded customer instructions as system policy.")
    r.bullet("Select only needed domain peers; do not let one specialist delegate to another.")
    r.bullet("Cite relevant trusted evidence at the atomic-claim level; a syntactically valid citation must still support the claim.")
    r.bullet("Keep missing, stale, roadmap, unsupported, and contradictory evidence distinct; never silently turn any into a commitment.")
    r.bullet("Stop at bounded retry/reanalysis limits, then send unresolved risk or organizational authority to human review.")
    r.sub("5.2", "Structured state and export")
    r.para("Typed graph state carries requirement IDs, selected specialists, evidence IDs, atomic claims, counters, conflict and authority outcomes, review decisions, and finalization status. The DOCX export is intentionally simple: a reviewable draft with status, citations, and approval notes. Paused cases state that no final response is authorized. [1, 8]")

    r.section("6", "Evaluation strategy")
    r.sub("6.1", "Frozen case design and fairness")
    r.para("Gaurav Asthana approved a frozen 24-case synthetic gold set before the provider comparison. It includes direct, cross-domain, missing-evidence, stale-source, conflict, prompt-injection, roadmap, and authority-sensitive cases. The single generalist and peer arm used the same synthetic corpus, retrieval contracts, model configuration, safety policy, and scoring rubric; gold labels were excluded from generation. Four cases were preselected for two further repeat trials. [3, 4, 6]")
    r.sub("6.2", "Primary metric")
    r.note("Safe Completion Rate = (safely finalized cases + correctly escalated cases) / all requested cases. Execution failures remain in the denominator. A correct human-review stop counts only when it withholds an unsafe final answer. [5]")
    r.table(
        ["Measure", "What it checks"],
        [
            ["Routing macro F1", "Whether the observed specialist/strategy route matches frozen labels"],
            ["Evidence Recall@5", "Whether required gold evidence appears in domain Top 5"],
            ["Unsupported-claim rate / groundedness", "Atomic-claim support and evidence alignment"],
            ["HITL, conflict, recovery F1", "Whether the right governance and repair paths were detected"],
            ["Execution, latency, estimated cost", "Operational success and observed tradeoffs"],
        ],
        [173, 315],
        size=7.9,
    )
    r.sub("6.3", "Anti-overclaim controls")
    r.para("The run preserved failures, original raw archives, approved hashes, and the price snapshot. A first provider attempt exposed local integration defects; it was retained but not presented as a valid architecture comparison. A reviewed recovery used new immutable run IDs and carried prior usage into the same 128-call budget. The approved final analysis is bound by a separate human approval record, even though the immutable source Markdown still bears its original draft label. [4, 6, 8]")

    r.new_page()
    r.section("7", "Single-generalist baseline comparison")
    r.comparison_bars()
    r.table(
        ["Primary 24-case metric", "Single generalist", "Orchestrated peers"],
        [
            ["Safe Completion Rate", "20/24 (83.3%)", "10/24 (41.7%)"],
            ["Execution success", "24/24", "20/24"],
            ["Routing macro F1", "0.972", "0.833"],
            ["Evidence Recall@5", "0.944", "0.786"],
            ["Unsupported-claim rate", "1.5%", "28.6%"],
            ["Groundedness", "98.5%", "69.8%"],
            ["HITL F1", "0.857", "0.889"],
            ["Conflict-detection F1", "0.000", "0.000"],
            ["Recovery-detection F1", "0.000", "0.222"],
            ["Observed mean latency", "7,192 ms", "9,734 ms"],
            ["Observed estimated generation cost", "$0.195032", "$0.250952"],
            ["Preserved primary failures", "0", "4"],
        ],
        [213, 137, 138],
        size=7.65,
    )
    r.caption("Table 4. Approved primary result for the frozen synthetic V1 set. Cost and latency are observed records, not a full invoice; retrieval-provider use and failed-attempt usage are excluded from the estimate. [4-6]")
    r.para("The single generalist is the bounded V1 preference because it completed and safely handled more of these particular cases. The peer architecture did demonstrate selected fan-out, HITL, and bounded recovery, but extra orchestration did not translate into better end-to-end safety here. Shared-budget censoring especially limits what the repeat study can say about variance. [5, 6]")

    r.section("8", "Iterations and recovery")
    r.table(
        ["Iteration", "Observation", "Disposition"],
        [
            ["Deterministic offline graph", "Enabled repeatable routing, state, validator, and UI tests before provider calls", "Retained as demo/testing mode"],
            ["Controlled fault injection", "Empty retrieval, tool exception, invalid output, and timeout paths were reproducible", "Retained bounded failure handling"],
            ["Provider attempt 1", "Local constructor, claim-ID, and elapsed-time defects invalidated comparison", "Preserved raw attempt; fixed offline; new approved run IDs"],
            ["Provider recovery + repeats", "Primary data recovered; 128-call ceiling censored 16/24 repeat observations", "Retained primary analysis; repeat variability inconclusive"],
        ],
        [109, 241, 138],
        size=7.5,
    )
    r.para("The fixed integration defects did not recur in the accepted primary comparison. Negative evidence was not hidden: four peer primary failures and all 19 failures across the full 64-execution plan remain in the reports. No post-hoc architecture winner is claimed from the censored repeats. [6, 8]")

    r.section("9", "Final results and interpretation")
    r.para("The approved primary result is descriptive, not a production acceptance test. Safe Completion favors the generalist by ten cases. Evidence Recall@5 and groundedness were also higher for the generalist, while its unsupported-claim rate was much lower. Both architectures achieved zero conflict-detection F1; peers had a slightly higher HITL F1 but still failed important safety paths. The peer arm was slower and costlier on observed successful records. [5, 6]")
    r.note("The full run accounted for 64 planned architecture executions and preserved 19 failures. Only 8 of 24 repeat-set observations succeeded; 16 failed at the shared budget boundary. The cumulative generation estimate was $0.814364 under the frozen pricing snapshot, excluding retrieval-provider usage. This is not total operating cost. [1, 5, 6]")

    r.section("10", "Failure analysis and representative cases")
    r.sub("10.1", "RFP-021 - missing certification evidence")
    r.para("The synthetic corpus has no direct FedRAMP High authorization evidence. The offline Security path performs two bounded retrieval attempts and then pauses for human review without a final answer. Adjacent certifications or general controls cannot be promoted into the missing authorization. This is a safe stop, not proof of certification. [2, 7]")
    r.sub("10.2", "RFP-014 - conflicting current retention sources")
    r.para("Two equally current, high-authority synthetic sources state 30-day and 90-day post-termination windows. One targeted reanalysis leaves the conflict unresolved; the graph pauses instead of choosing the more convenient passage. A reviewer cannot approve away the factual contradiction in the first-run UI state. [2, 7]")
    r.sub("10.3", "RFP-005 - authority beyond evidence")
    r.para("A source supports the qualified 99.9% standard, but the customer asks for 99.99% and service credits. The response must not infer that a documented standard authorizes a nonstandard commercial term. The workflow stops for organizational review; the frozen first-run result is NEEDS_HUMAN, not approval. [2, 7]")
    r.sub("10.4", "Open quality gaps")
    r.para("RFP-006 exhausts retrieval before the expected roadmap-authority gate. RFP-015 surfaces a security exception but misses the second expected retention conflict. Some evidence-gap and pre-retrieval checkpoints offer more reviewer actions than the gold contract permits. These gaps and zero conflict-detection F1 materially limit the system's Safe Completion result. They are disclosed, not repaired in this report. [1, 6]")
    r.sub("10.5", "Diagnosis method")
    for item in (
        "Confirm whether required evidence exists and is current, authoritative, and indexed.",
        "Inspect the domain Top-5 results and exact cited evidence for each atomic claim.",
        "Trace the chosen route, retry/reanalysis counters, authority gate, and checkpoint state.",
        "Classify retrieval, generation, validation, UI-action, budget, or evaluation-data failure.",
        "Preserve the original failure and rerun only under a separately reviewed configuration.",
    ):
        r.bullet(item)

    r.section("11", "Use of AI coding tools and human decisions")
    r.para("Codex helped plan and build the Python modules, tests, failure controls, UI, evaluation scripts, and documentation one numbered step at a time in VS Code. Gaurav Asthana retained the key judgments: corpus and gold-set review, model/provider budget approval, exact guarded run approvals, interpretation of failed and censored results, and acceptance of the bounded single-generalist preference. The project journal records those decisions and troubleshooting steps. [4, 8]")
    r.para("This division matters because an agentic proposal system cannot infer organizational authority from model confidence. Likewise, an AI coding assistant cannot make an experiment valid by merely producing working code; human review of evidence, metrics, and claims remains essential.")

    r.section("12", "Limitations and safety")
    for item in (
        "The synthetic corpus has only 12 trusted sources and no live document refresh, real customer material, or enterprise permission model.",
        "The offline specialist behavior and Implementation semantic scorer are deterministic substitutes, not production model judgments.",
        "The app's InMemorySaver checkpointing is process-local; it is not durable or appropriate for concurrent enterprise reviewers.",
        "Only one provider/model configuration and one 24-case primary trial were measured; the repeat set was heavily budget-censored.",
        "Neither architecture detected conflicts well in the primary scoring, and reviewer-action controls have known over-permissive gaps.",
        "DOCX structure and five first pages were checked; every page was not visually inspected after the Word UI stopped responding.",
        "Observed generation-cost figures exclude retrieval-provider charges and some failed-attempt usage; they are not a deployment cost estimate.",
        "No authentication, role-based reviewer authorization, tenant isolation, large-corpus scaling, or production security/privacy review has been completed.",
    ):
        r.bullet(item)
    r.note("Do not submit actual customer RFPs or confidential source documents to this prototype. Any real-data deployment would need governance, durable audit storage, security review, and independent evaluation. [1, 5, 6]")

    r.section("13", "Reproducibility and audit trail")
    r.para("The repository separates synthetic knowledge-base files, untrusted requirements, frozen gold labels, source modules, tests, planning decisions, and local raw evaluation artifacts. The final human approval record binds exact analysis hashes. The architecture capture and metrics page point back to verified sources. Direct runtime versions are recorded, but a full transitive lockfile is not yet present. [4, 5, 8, 9]")
    r.table(
        ["Artifact", "Location / role"],
        [
            ["Project guide", "README.md - architecture, setup, demo, evaluation, limitations"],
            ["Build evidence", "planning/BUILD_PLAN.md; PROJECT_JOURNAL.md"],
            ["Synthetic data", "data/kb/; data/sample_rfp.md; data/corpus_inventory.md"],
            ["Frozen gold set", "data/evaluation/evaluation_cases_v1.json"],
            ["Approved result", "data/evaluation/provider_evaluation_final_approval_step_4_g8.json"],
            ["Detailed local result", "outputs/evaluation/provider_evaluation_final_step_4_g8.md (Git-ignored)"],
            ["Visual + metrics", "docs/architecture_execution_rfp002.png; docs/evaluation_metrics_v1.md"],
            ["Demo guide", "docs/demo_script_and_recording_checklist_v1.md"],
        ],
        [134, 354],
        size=7.75,
    )
    r.para("At report time, Build Plan Steps 5.17-5.19 remain open: final full regression/regeneration/startup checks, public-claim audit, and a reviewed local release freeze. The Git CLI is blocked by this Mac's Xcode-license/tool mismatch, so the real staged-file check and release identifier are also pending. This PDF is a submission draft until those gates and the user-owned demo recording are completed. [1, 8]")

    r.section("14", "Conclusion and next actions")
    r.para("The project demonstrates an inspectable agentic control-flow system: selective peer specialists, evidence gates, bounded recovery, consistency and authority checks, checkpointed human review, a live execution map, and DOCX export. Its strongest portfolio lesson is disciplined measurement rather than an asserted multi-agent win. The single generalist was safer on the frozen synthetic primary set; the orchestrated design exposed important implementation and budget costs. [1, 5, 6]")
    r.para("Before submission, complete the planned offline Step 5.17 verification, Step 5.18 evidence-to-claim audit, and Step 5.19 local release review; then record the credential-safe five-minute demo and submit only reviewed artifacts. Future technical work should address the known RFP-006/RFP-015 and reviewer-action gaps, durable and authorized review, larger synthetic or permissioned corpora, and an independently budgeted evaluation. The excluded post-submission simplification exercise is not part of this project. [1, 7, 8]")

    r.section("Appendix A", "Assignment requirement map")
    r.table(
        ["Week 3 theme", "Where demonstrated"],
        [
            ["Dynamic agentic control flow", "Sections 3-5; actual RFP-002 map and five-case offline paths"],
            ["State, tools, failure/recovery", "Sections 2-3, 8, 10; Top-5 retrieval, counters, validators"],
            ["Human-in-the-loop authority", "Sections 3, 5, 10; checkpointed stop and guarded continuation"],
            ["Evaluation and baseline", "Sections 6-9; frozen 24-case generalist/peer comparison"],
            ["Application and live demo", "Sections 3-4; Streamlit map, simple DOCX, prepared recording guide"],
            ["AI tool use, learnings, limits", "Sections 10-14; journal and approved final analysis"],
        ],
        [180, 308],
        size=8.0,
    )

    r.section("Appendix B", "Source and reporting conventions")
    for label, location in (
        ("[1]", "README.md - current product and limitations narrative"),
        ("[2]", "data/corpus_inventory.md - source inventory and seeded fixtures"),
        ("[3]", "data/evaluation/evaluation_cases_v1.json - frozen 24-case labels"),
        ("[4]", "data/evaluation/provider_evaluation_final_approval_step_4_g8.json - Gaurav Asthana's final analysis approval"),
        ("[5]", "docs/evaluation_metrics_v1.md - verified primary metrics and definitions"),
        ("[6]", "outputs/evaluation/provider_evaluation_final_step_4_g8.md - detailed local, Git-ignored analysis"),
        ("[7]", "data/fixtures/demo_cases_v1.md - first-run demo expectations"),
        ("[8]", "planning/BUILD_PLAN.md and PROJECT_JOURNAL.md - decisions, approvals, and status"),
        ("[9]", "docs/architecture_execution_rfp002.md - actual map capture provenance"),
    ):
        r.bullet(f"{label} {location}", size=8.2)
    r.para("All reported comparison numbers refer to the approved primary 24-case synthetic set unless labeled otherwise. Failed executions remain in denominators. Repeat-set variability is inconclusive. Observed cost and latency are not complete operating-cost estimates. The immutable final-analysis Markdown retains its pre-approval status line; the separate approval record is authoritative for the human decision. [4-6]", size=8.6)
    return r


if __name__ == "__main__":
    report = build_report()
    write_pdf(report)
    print(f"Created {OUTPUT.name}: {len(report.pages)} pages, {OUTPUT.stat().st_size} bytes")
