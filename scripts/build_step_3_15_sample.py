"""Build the representative Step 3.15 DOCX used for render QA."""

from pathlib import Path

from rfp_orchestrator.docx_export import generate_basic_response_docx
from rfp_orchestrator.sample_requirements import load_sample_requirements

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "docx" / "step_3_15_rfp_001.docx"


def main() -> None:
    requirement = load_sample_requirements()[0]
    state = {
        "requirement_id": requirement.requirement_id,
        "original_text": requirement.text,
        "final_status": "FINALIZED",
        "final_answer": (
            "SAML 2.0 is generally available on Enterprise Cloud and Standard "
            "Cloud. SCIM 2.0 is generally available on Enterprise Cloud."
        ),
    }
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_bytes(generate_basic_response_docx(state))
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
