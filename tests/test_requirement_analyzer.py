import re
from pathlib import Path

import pytest

from rfp_orchestrator.models import Requirement
from rfp_orchestrator.requirement_analyzer import (
    MAX_ATOMIC_REQUIREMENTS,
    RequirementDecompositionError,
    analyze_requirement,
    decompose_requirement,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RFP_PATH = PROJECT_ROOT / "data" / "sample_rfp.md"


def test_simple_requirement_remains_one_atomic_statement() -> None:
    assert decompose_requirement(
        "Confirm whether your platform is FIPS 140-3 certified."
    ) == ["Confirm whether your platform is FIPS 140-3 certified."]


def test_support_pair_becomes_two_atomic_requirements() -> None:
    assert decompose_requirement("Confirm support for SAML 2.0 and SCIM 2.0.") == [
        "Confirm support for SAML 2.0.",
        "Confirm support for SCIM 2.0.",
    ]


def test_explicit_action_clauses_split_without_losing_their_verbs() -> None:
    assert decompose_requirement(
        "Describe customer-managed encryption keys and identify supported deployment "
        "environments."
    ) == [
        "Describe customer-managed encryption keys.",
        "Identify supported deployment environments.",
    ]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        (
            (
                "Describe the typical implementation plan, prerequisites, and customer "
                "responsibilities."
            ),
            [
                "Describe the typical implementation plan.",
                "Describe prerequisites.",
                "Describe customer responsibilities.",
            ],
        ),
        (
            (
                "State the expected implementation duration, when the timeline begins, "
                "and the conditions that can change it."
            ),
            [
                "State the expected implementation duration.",
                "State when the timeline begins.",
                "State the conditions that can change it.",
            ],
        ),
        (
            (
                "Explain how a complex custom integration would affect scope, timeline, "
                "and implementation approval."
            ),
            [
                "Explain how a complex custom integration would affect scope.",
                "Explain how a complex custom integration would affect timeline.",
                (
                    "Explain how a complex custom integration would affect implementation "
                    "approval."
                ),
            ],
        ),
        (
            (
                "Compare Standard Cloud and Enterprise Cloud for identity provisioning, "
                "deployment, and customer-managed encryption keys."
            ),
            [
                "Compare Standard Cloud and Enterprise Cloud for identity provisioning.",
                "Compare Standard Cloud and Enterprise Cloud for deployment.",
                (
                    "Compare Standard Cloud and Enterprise Cloud for customer-managed "
                    "encryption keys."
                ),
            ],
        ),
    ],
)
def test_clear_material_lists_are_decomposed(text: str, expected: list[str]) -> None:
    assert decompose_requirement(text) == expected


def test_shared_qualifier_is_preserved_for_every_customer_resource() -> None:
    atoms = decompose_requirement(
        "Identify the customer roles, access, data, and test resources required during "
        "implementation."
    )

    assert atoms == [
        "Identify the customer roles required during implementation.",
        "Identify access required during implementation.",
        "Identify data required during implementation.",
        "Identify test resources required during implementation.",
    ]


def test_coordinated_evidence_and_commitment_pairs_keep_shared_context() -> None:
    assert decompose_requirement(
        "Confirm whether current SOC 2 Type II and ISO 27001 assurance evidence is "
        "available for review."
    ) == [
        "Confirm whether current SOC 2 Type II assurance evidence is available for review.",
        "Confirm whether current ISO 27001 assurance evidence is available for review.",
    ]
    assert decompose_requirement(
        "Accept a 20% subscription discount and unlimited indemnity as part of this response."
    ) == [
        "Accept a 20% subscription discount as part of this response.",
        "Accept unlimited indemnity as part of this response.",
    ]


def test_analyzer_preserves_original_requirement_and_unrelated_fields() -> None:
    original = Requirement(
        requirement_id="RFP-001",
        original_text="Confirm support for SAML 2.0 and SCIM 2.0.",
    )

    analyzed = analyze_requirement(original)

    assert original.atomic_requirements == []
    assert analyzed.requirement_id == "RFP-001"
    assert analyzed.original_text == original.original_text
    assert analyzed.atomic_requirements == [
        "Confirm support for SAML 2.0.",
        "Confirm support for SCIM 2.0.",
    ]
    assert analyzed.assigned_domains == []
    assert analyzed.prompt_injection_detected is False


def test_decomposition_is_repeatable_and_strips_display_label_only_from_atoms() -> None:
    source = "1. **RFP-001** Confirm support for SAML 2.0 and SCIM 2.0."

    assert decompose_requirement(source) == decompose_requirement(source)
    assert decompose_requirement(source)[0] == "Confirm support for SAML 2.0."


def test_blank_and_excessive_decomposition_fail_closed() -> None:
    with pytest.raises(RequirementDecompositionError, match="cannot be blank"):
        decompose_requirement("   ")

    items = ", ".join(f"item {index}" for index in range(MAX_ATOMIC_REQUIREMENTS))
    with pytest.raises(RequirementDecompositionError, match="safe maximum"):
        decompose_requirement(f"Describe {items}, and final item.")


def test_all_sample_rfp_requirements_decompose_repeatably() -> None:
    source = SAMPLE_RFP_PATH.read_text(encoding="utf-8")
    requirements = dict(
        re.findall(r"^\d+\. \*\*(RFP-\d+)\*\* (.+)$", source, flags=re.MULTILINE)
    )

    first = {
        requirement_id: decompose_requirement(text)
        for requirement_id, text in requirements.items()
    }
    second = {
        requirement_id: decompose_requirement(text)
        for requirement_id, text in requirements.items()
    }

    assert len(requirements) == 24
    assert first == second
    assert all(1 <= len(atoms) <= MAX_ATOMIC_REQUIREMENTS for atoms in first.values())
    assert len(first["RFP-001"]) == 2
    assert len(first["RFP-004"]) == 3
    assert len(first["RFP-016"]) == 3
    assert len(first["RFP-019"]) == 3
    assert len(first["RFP-020"]) == 3
    assert len(first["RFP-024"]) == 1
