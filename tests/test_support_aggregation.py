import pytest
from pydantic import ValidationError

from rfp_orchestrator.models import Claim, SpecialistOutput, SupportStatus, aggregate_support


def claim(claim_id: str, supported: bool) -> Claim:
    return Claim(claim_id=claim_id, text=claim_id, supported=supported)


@pytest.mark.parametrize(
    ("claims", "expected"),
    [
        ([], SupportStatus.UNSUPPORTED),
        ([claim("a", True)], SupportStatus.SUPPORTED),
        ([claim("a", True), claim("b", False)], SupportStatus.PARTIAL),
        ([claim("a", False), claim("b", False)], SupportStatus.UNSUPPORTED),
    ],
)
def test_aggregate_support(claims: list[Claim], expected: SupportStatus) -> None:
    assert aggregate_support(claims) is expected


def test_specialist_output_rejects_inconsistent_aggregate() -> None:
    with pytest.raises(ValidationError):
        SpecialistOutput(
            specialist="security",
            claims=[claim("a", True), claim("b", False)],
            proposed_answer="Qualified response",
            support_status=SupportStatus.SUPPORTED,
        )

