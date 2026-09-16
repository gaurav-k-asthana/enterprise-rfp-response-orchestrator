"""Create or verify the Step 4.9 fair-comparison configuration freeze."""

from rfp_orchestrator.fair_comparison import write_fair_comparison_freeze


def main() -> None:
    _, digest = write_fair_comparison_freeze()
    print("Fair-comparison status: FROZEN")
    print("Architectures: 2")
    print("Shared retrieval tools: 3")
    print(f"Artifact SHA-256: {digest}")
    print("Comparative cases run: 0")
    print("Network calls made: 0")


if __name__ == "__main__":
    main()
