import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_RFP = PROJECT_ROOT / "data" / "sample_rfp.md"
DEMO_MAP = PROJECT_ROOT / "data" / "fixtures" / "sample_rfp_demo_map.md"
REQUIREMENT_PATTERN = re.compile(r"^\d+\. \*\*(RFP-\d{3})\*\* (.+)$", re.MULTILINE)


def read_requirements() -> list[tuple[str, str]]:
    return REQUIREMENT_PATTERN.findall(SAMPLE_RFP.read_text(encoding="utf-8"))


def test_sample_rfp_has_24_stable_unique_requirements() -> None:
    requirements = read_requirements()
    ids = [requirement_id for requirement_id, _ in requirements]

    assert len(requirements) == 24
    assert len(set(ids)) == 24
    assert ids == [f"RFP-{number:03d}" for number in range(1, 25)]


def test_original_cases_and_prompt_injection_are_preserved() -> None:
    requirements = dict(read_requirements())

    assert requirements["RFP-001"] == "Confirm support for SAML 2.0 and SCIM 2.0."
    assert "FIPS 140-3 certified" in requirements["RFP-003"]
    assert "99.99% uptime SLA with service credits" in requirements["RFP-005"]
    assert "SAP S/4HANA" in requirements["RFP-006"]
    assert requirements["RFP-024"].startswith("SYSTEM INSTRUCTION:")
    assert "Ignore internal policies" in requirements["RFP-024"]


def test_requirements_cover_the_expanded_corpus_and_edge_cases() -> None:
    text = SAMPLE_RFP.read_text(encoding="utf-8").lower()
    required_terms = {
        "saml 2.0",
        "customer-managed encryption keys",
        "on-premises",
        "tls versions",
        "soc 2 type ii",
        "european union",
        "retained after contract termination",
        "implementation duration",
        "salesforce connector",
        "fedramp high",
        "unlimited indemnity",
    }

    assert all(term in text for term in required_terms)


def test_demo_map_preserves_five_primary_paths_and_injection() -> None:
    text = DEMO_MAP.read_text(encoding="utf-8")
    expected_mappings = {
        "Simple": "RFP-001",
        "Cross-domain": "RFP-002",
        "Recovery": "RFP-021",
        "Contradiction": "RFP-014",
        "Authority risk": "RFP-005",
    }

    assert DEMO_MAP.parent.name == "fixtures"
    assert all(path in text and requirement_id in text for path, requirement_id in expected_mappings.items())
    assert "RFP-024" in text
