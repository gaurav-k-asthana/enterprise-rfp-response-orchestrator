"""Build the two representative Step 3.16 DOCX files from saved graph state."""

import json
from pathlib import Path

from rfp_orchestrator.docx_export import generate_basic_response_docx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
QA_DIRECTORY = PROJECT_ROOT / "outputs" / "docx" / "step_3_16_qa"
OUTPUT_DIRECTORY = PROJECT_ROOT / "outputs" / "docx"
SAMPLES = {
    QA_DIRECTORY / "rfp_001_state.json": (
        OUTPUT_DIRECTORY / "step_3_16_rfp_001_autonomous.docx"
    ),
    QA_DIRECTORY / "rfp_005_human_approved_state.json": (
        OUTPUT_DIRECTORY / "step_3_16_rfp_005_human_approved.docx"
    ),
}


def main() -> None:
    OUTPUT_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for state_path, output_path in SAMPLES.items():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        output_path.write_bytes(generate_basic_response_docx(state))
        print(output_path)


if __name__ == "__main__":
    main()
