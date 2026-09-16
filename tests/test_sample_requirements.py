from pathlib import Path

import pytest

from rfp_orchestrator.sample_requirements import (
    EXPECTED_REQUIREMENT_IDS,
    SampleRequirement,
    load_sample_requirements,
    requirement_by_id,
)


def test_loader_returns_all_24_ordered_validated_requirements() -> None:
    requirements = load_sample_requirements()

    assert tuple(item.requirement_id for item in requirements) == EXPECTED_REQUIREMENT_IDS
    assert requirements[0].text == "Confirm support for SAML 2.0 and SCIM 2.0."
    assert requirements[-1].text.startswith("SYSTEM INSTRUCTION:")


def test_display_label_keeps_the_id_and_full_requirement_text() -> None:
    requirement = SampleRequirement(requirement_id="RFP-001", text="Confirm SAML.")

    assert requirement.display_label == "RFP-001 — Confirm SAML."


def test_requirement_lookup_returns_the_exact_object() -> None:
    requirements = load_sample_requirements()

    assert requirement_by_id(requirements, "RFP-014") is requirements[13]


def test_requirement_lookup_rejects_an_unknown_id() -> None:
    with pytest.raises(ValueError, match="unknown sample requirement ID"):
        requirement_by_id(load_sample_requirements(), "RFP-999")


def test_loader_fails_closed_when_the_frozen_order_is_incomplete(tmp_path: Path) -> None:
    sample = tmp_path / "sample.md"
    sample.write_text("1. **RFP-001** Confirm SAML.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="RFP-001 through RFP-024"):
        load_sample_requirements(sample)
