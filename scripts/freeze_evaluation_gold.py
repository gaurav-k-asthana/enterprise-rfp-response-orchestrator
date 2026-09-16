"""Apply one explicitly approved Step 4.7 gold-set freeze."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path

from rfp_orchestrator.evaluation_freeze import (
    DEFAULT_FREEZE_MANIFEST_DIGEST_PATH,
    DEFAULT_FREEZE_MANIFEST_PATH,
    DEFAULT_REVIEW_PACKET_PATH,
    build_freeze_manifest,
    file_sha256,
    freeze_gold_dataset,
    gold_content_sha256,
    render_gold_review_packet,
    serialized_dataset,
    text_sha256,
)
from rfp_orchestrator.evaluation_schema import (
    DEFAULT_EVALUATION_DATASET_PATH,
    load_evaluation_dataset,
)


def _atomic_write(path: Path, content: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(content, encoding="utf-8")
    temporary.replace(path)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Freeze an explicitly approved evaluation gold set."
    )
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--reviewed-at", required=True)
    parser.add_argument("--notes")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    reviewed_at = datetime.fromisoformat(args.reviewed_at)
    draft = load_evaluation_dataset()
    draft_file_digest = file_sha256(DEFAULT_EVALUATION_DATASET_PATH)
    before_gold_digest = gold_content_sha256(draft)

    frozen = freeze_gold_dataset(
        draft,
        reviewer=args.reviewer,
        reviewed_at=reviewed_at,
        notes=args.notes,
    )
    frozen_text = serialized_dataset(frozen)
    frozen_file_digest = text_sha256(frozen_text)
    review_packet = render_gold_review_packet(
        frozen,
        dataset_file_digest=frozen_file_digest,
    )
    review_packet_digest = text_sha256(review_packet)
    manifest = build_freeze_manifest(
        frozen,
        draft_dataset_digest=draft_file_digest,
        frozen_dataset_digest=frozen_file_digest,
        review_packet_digest=review_packet_digest,
    )
    manifest_text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    manifest_digest = text_sha256(manifest_text)

    _atomic_write(DEFAULT_EVALUATION_DATASET_PATH, frozen_text)
    _atomic_write(DEFAULT_REVIEW_PACKET_PATH, review_packet)
    _atomic_write(DEFAULT_FREEZE_MANIFEST_PATH, manifest_text)
    _atomic_write(
        DEFAULT_FREEZE_MANIFEST_DIGEST_PATH,
        f"{manifest_digest}  {DEFAULT_FREEZE_MANIFEST_PATH.name}\n",
    )

    reloaded = load_evaluation_dataset()
    if gold_content_sha256(reloaded) != before_gold_digest:
        raise RuntimeError("gold content changed during the checked-in freeze")
    if file_sha256(DEFAULT_EVALUATION_DATASET_PATH) != frozen_file_digest:
        raise RuntimeError("frozen dataset checksum does not match the manifest")

    print(f"Dataset status: {reloaded.status.value}")
    print(f"Reviewer: {reloaded.cases[0].review.reviewer}")
    print(f"Approved cases: {len(reloaded.cases)}/24")
    print(f"Gold-content SHA-256: {before_gold_digest}")
    print(f"Frozen dataset SHA-256: {frozen_file_digest}")
    print(f"Freeze manifest SHA-256: {manifest_digest}")
    print("Network calls made: 0")


if __name__ == "__main__":
    main()
