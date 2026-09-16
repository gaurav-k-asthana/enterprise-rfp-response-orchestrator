"""Build the Step 3.17 download-equivalent DOCX for render verification."""

import json
from pathlib import Path

from rfp_orchestrator.docx_export import generate_basic_response_docx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
STATE_PATH = (
    PROJECT_ROOT / "outputs" / "docx" / "step_3_16_qa" / "rfp_001_state.json"
)
OUTPUT_PATH = (
    PROJECT_ROOT / "outputs" / "docx" / "northstar-rfp-response-rfp-001.docx"
)


def main() -> None:
    state = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(generate_basic_response_docx(state))
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
