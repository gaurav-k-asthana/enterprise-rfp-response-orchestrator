"""Build five synthetic, ignored DOCX files for Step 5.11 visual QA."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rfp_orchestrator.sample_requirements import load_sample_requirements
from rfp_orchestrator.ui import build_docx_download, run_sample_requirement

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "data" / "fixtures" / "demo_cases_v1.json"
OUTPUT_DIR = ROOT / "outputs" / "docx" / "step_5_11_qa"


def main() -> None:
    cases = json.loads(MANIFEST.read_text(encoding="utf-8"))["cases"]
    requirements = {
        item.requirement_id: item for item in load_sample_requirements()
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for number, case in enumerate(cases, start=1):
        requirement = requirements[case["requirement_id"]]
        if requirement.text != case["requirement_text"]:
            raise ValueError("frozen demo text differs from the sample RFP")
        state, _ = run_sample_requirement(requirement, number, "step-5-11")
        if state["final_status"] != case["expected_status"]:
            raise ValueError("frozen demo status differs from the offline graph")

        artifact = build_docx_download(state)
        destination = OUTPUT_DIR / artifact.file_name
        if destination.exists():
            if destination.read_bytes() != artifact.data:
                raise FileExistsError(
                    "an existing QA document differs; inspect it before replacement"
                )
        else:
            destination.write_bytes(artifact.data)
        digest = hashlib.sha256(artifact.data).hexdigest()
        print(
            f"{case['requirement_id']} {state['final_status']} "
            f"{len(artifact.data)} bytes sha256={digest}"
        )


if __name__ == "__main__":
    main()
