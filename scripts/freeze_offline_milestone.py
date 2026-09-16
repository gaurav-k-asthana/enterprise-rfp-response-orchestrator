"""Create the secret-safe Phase 2 offline graph milestone artifact."""

from pathlib import Path

from rfp_orchestrator.offline_milestone import write_offline_milestone

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "outputs" / "offline_graph_milestone_v1.json"
DIGEST_PATH = PROJECT_ROOT / "outputs" / "offline_graph_milestone_v1.sha256"


def main() -> None:
    _, digest = write_offline_milestone(PROJECT_ROOT, OUTPUT_PATH)
    DIGEST_PATH.write_text(f"{digest}  {OUTPUT_PATH.name}\n", encoding="utf-8")
    print(f"Offline milestone: {OUTPUT_PATH.name}")
    print(f"Artifact SHA-256: {digest}")
    print("Provider graph calls enabled: false")
    print("Network calls made: 0")


if __name__ == "__main__":
    main()
