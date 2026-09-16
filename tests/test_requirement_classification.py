import re
from pathlib import Path

import pytest
from pydantic import ValidationError

from rfp_orchestrator.models import (
    AmbiguitySignal,
    AmbiguitySignalType,
    Domain,
    Requirement,
    RequirementAttribute,
    RiskClass,
)
from rfp_orchestrator.requirement_classification import (
    analyze_requirement_input,
    assign_domains,
    detect_ambiguity,
)
from rfp_orchestrator.state import new_requirement_state

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RFP_PATH = PROJECT_ROOT / "data" / "sample_rfp.md"


def sample_requirements() -> dict[str, str]:
    source = SAMPLE_RFP_PATH.read_text(encoding="utf-8")
    return dict(
        re.findall(r"^\d+\. \*\*(RFP-\d+)\*\* (.+)$", source, flags=re.MULTILINE)
    )


@pytest.mark.parametrize(
    ("requirement_id", "expected_domains"),
    [
        ("RFP-001", [Domain.PRODUCT]),
        ("RFP-002", [Domain.PRODUCT, Domain.SECURITY]),
        ("RFP-003", [Domain.SECURITY]),
        ("RFP-004", [Domain.IMPLEMENTATION]),
        ("RFP-005", [Domain.PRODUCT]),
        ("RFP-006", [Domain.PRODUCT]),
        ("RFP-007", [Domain.PRODUCT]),
        ("RFP-008", [Domain.SECURITY]),
        ("RFP-009", [Domain.SECURITY]),
        ("RFP-010", [Domain.SECURITY]),
        ("RFP-011", [Domain.PRODUCT, Domain.SECURITY]),
        ("RFP-012", [Domain.PRODUCT, Domain.SECURITY]),
        ("RFP-013", [Domain.SECURITY]),
        ("RFP-014", [Domain.SECURITY]),
        ("RFP-015", [Domain.SECURITY]),
        ("RFP-016", [Domain.IMPLEMENTATION]),
        ("RFP-017", [Domain.IMPLEMENTATION]),
        ("RFP-018", [Domain.PRODUCT]),
        ("RFP-019", [Domain.IMPLEMENTATION]),
        ("RFP-020", [Domain.PRODUCT, Domain.SECURITY]),
        ("RFP-021", [Domain.SECURITY]),
        ("RFP-022", [Domain.PRODUCT]),
        ("RFP-023", []),
        ("RFP-024", []),
    ],
)
def test_all_sample_requirements_receive_expected_domains(
    requirement_id: str,
    expected_domains: list[Domain],
) -> None:
    text = sample_requirements()[requirement_id]

    analyzed = analyze_requirement_input(
        Requirement(requirement_id=requirement_id, original_text=text)
    )

    assert analyzed.assigned_domains == expected_domains


def test_cross_domain_and_implementation_examples_have_structured_attributes() -> None:
    requirements = sample_requirements()

    cross_domain = analyze_requirement_input(
        Requirement(requirement_id="RFP-002", original_text=requirements["RFP-002"])
    )
    implementation = analyze_requirement_input(
        Requirement(requirement_id="RFP-016", original_text=requirements["RFP-016"])
    )

    assert cross_domain.attributes == [
        RequirementAttribute.INFORMATION_REQUEST,
    ]
    assert implementation.attributes == [RequirementAttribute.INFORMATION_REQUEST]
    assert len(cross_domain.atomic_requirements) == 2
    assert len(implementation.atomic_requirements) == 3


def test_request_types_cover_confirmation_commitment_comparison_and_deliverable() -> None:
    requirements = sample_requirements()

    roadmap = analyze_requirement_input(
        Requirement(requirement_id="RFP-006", original_text=requirements["RFP-006"])
    )
    comparison = analyze_requirement_input(
        Requirement(requirement_id="RFP-020", original_text=requirements["RFP-020"])
    )
    deliverable = analyze_requirement_input(
        Requirement(requirement_id="RFP-022", original_text=requirements["RFP-022"])
    )

    assert roadmap.attributes == [
        RequirementAttribute.CONFIRMATION_REQUEST,
        RequirementAttribute.COMMITMENT_REQUEST,
        RequirementAttribute.TIME_BOUND_REQUEST,
    ]
    assert comparison.attributes == [RequirementAttribute.COMPARISON_REQUEST]
    assert deliverable.attributes == [RequirementAttribute.DELIVERABLE_REQUEST]


def test_initial_risks_are_textual_candidates_not_evidence_judgments() -> None:
    requirements = sample_requirements()

    expected = {
        "RFP-005": [RiskClass.SLA_OR_SERVICE_CREDIT],
        "RFP-006": [RiskClass.ROADMAP_COMMITMENT],
        "RFP-013": [
            RiskClass.SECURITY_EXCEPTION,
            RiskClass.DATA_RESIDENCY_AMBIGUITY,
        ],
        "RFP-015": [RiskClass.SECURITY_EXCEPTION],
        "RFP-023": [
            RiskClass.PRICING_OR_DISCOUNT,
            RiskClass.WARRANTY_OR_INDEMNITY,
        ],
    }
    for requirement_id, risks in expected.items():
        analyzed = analyze_requirement_input(
            Requirement(
                requirement_id=requirement_id,
                original_text=requirements[requirement_id],
            )
        )
        assert analyzed.initial_risk_flags == risks

    evidence_dependent = analyze_requirement_input(
        Requirement(requirement_id="RFP-021", original_text=requirements["RFP-021"])
    )
    assert evidence_dependent.initial_risk_flags == []


def test_ambiguity_signals_preserve_exact_source_spans() -> None:
    requirements = sample_requirements()

    roadmap = analyze_requirement_input(
        Requirement(requirement_id="RFP-006", original_text=requirements["RFP-006"])
    )
    absolute = analyze_requirement_input(
        Requirement(requirement_id="RFP-013", original_text=requirements["RFP-013"])
    )

    assert [signal.signal_type for signal in roadmap.ambiguity_signals] == [
        AmbiguitySignalType.RELATIVE_TIMEFRAME
    ]
    assert roadmap.ambiguity_signals[0].matched_text == "this quarter"
    assert [signal.signal_type for signal in absolute.ambiguity_signals] == [
        AmbiguitySignalType.ABSOLUTE_LANGUAGE
    ]
    assert absolute.ambiguity_signals[0].matched_text == "ever"
    for requirement in (roadmap, absolute):
        assert all(
            requirement.original_text[signal.start_index : signal.end_index]
            == signal.matched_text
            for signal in requirement.ambiguity_signals
        )


def test_synthetic_undefined_time_and_scope_are_explainable() -> None:
    text = "Provide the required integration promptly in all environments."

    signals = detect_ambiguity(text)

    assert [signal.signal_type for signal in signals] == [
        AmbiguitySignalType.UNDEFINED_TIMEFRAME,
        AmbiguitySignalType.UNBOUNDED_SCOPE,
    ]
    assert all(signal.reason for signal in signals)


def test_injection_attribute_and_prior_analysis_are_preserved() -> None:
    text = sample_requirements()["RFP-024"]
    original = Requirement(requirement_id="RFP-024", original_text=text)

    analyzed = analyze_requirement_input(original)

    assert analyzed.original_text == text
    assert analyzed.prompt_injection_detected is True
    assert analyzed.attributes == [RequirementAttribute.UNTRUSTED_INSTRUCTION]
    assert analyzed.assigned_domains == []
    assert analyzed.atomic_requirements
    assert original.atomic_requirements == []
    assert original.prompt_injection_detected is False


def test_classifier_rejects_duplicate_fields_and_tampered_ambiguity_span() -> None:
    with pytest.raises(ValidationError, match="assigned_domains cannot contain duplicates"):
        Requirement(
            requirement_id="RFP-X",
            original_text="Confirm SAML support.",
            assigned_domains=[Domain.PRODUCT, Domain.PRODUCT],
        )

    with pytest.raises(ValidationError, match="ambiguity signal span must match"):
        Requirement(
            requirement_id="RFP-X",
            original_text="Deliver this quarter.",
            ambiguity_signals=[
                AmbiguitySignal(
                    signal_type=AmbiguitySignalType.RELATIVE_TIMEFRAME,
                    matched_text="wrong text",
                    start_index=8,
                    end_index=20,
                    reason="Relative timeframe.",
                )
            ],
        )


def test_new_graph_state_exposes_empty_step_2_3_fields() -> None:
    state = new_requirement_state("case-1", "RFP-001", "Confirm SAML support.")

    assert state["assigned_domains"] == []
    assert state["requirement_attributes"] == []
    assert state["ambiguity_signals"] == []
    assert state["initial_risk_flags"] == []


def test_domain_assignment_does_not_use_generic_data_or_integration_words() -> None:
    assert assign_domains("Identify data required during implementation.") == [
        Domain.IMPLEMENTATION
    ]
    assert assign_domains("Explain a complex custom integration timeline.") == [
        Domain.IMPLEMENTATION
    ]
