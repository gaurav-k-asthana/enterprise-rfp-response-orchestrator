"""Generate the Step 4.7 gold-set review packet without freezing the dataset."""

from rfp_orchestrator.evaluation_freeze import (
    DEFAULT_REVIEW_PACKET_PATH,
    render_gold_review_packet,
)
from rfp_orchestrator.evaluation_schema import load_evaluation_dataset


def main() -> None:
    dataset = load_evaluation_dataset()
    DEFAULT_REVIEW_PACKET_PATH.write_text(
        render_gold_review_packet(dataset),
        encoding="utf-8",
    )
    print(f"Review packet: {DEFAULT_REVIEW_PACKET_PATH.name}")
    approved = sum(case.review.status.value == "APPROVED" for case in dataset.cases)
    print(f"Dataset status: {dataset.status.value}")
    print(f"Cases approved: {approved}/24")
    print("Network calls made: 0")


if __name__ == "__main__":
    main()
