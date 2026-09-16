"""Write the generated Step 4.8 single-generalist review contract."""

from pathlib import Path

from rfp_orchestrator.generalist_baseline import render_generalist_baseline_contract

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "data" / "evaluation" / "generalist_baseline_contract_v1.md"


def main() -> None:
    OUTPUT_PATH.write_text(render_generalist_baseline_contract(), encoding="utf-8")
    print(f"Baseline contract: {OUTPUT_PATH.name}")
    print("Reasoning identities: 1")
    print("Available retrieval tools: 3")
    print("Comparative cases run: 0")
    print("Network calls made: 0")


if __name__ == "__main__":
    main()
