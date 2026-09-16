"""Validated loader for the frozen synthetic sample RFP."""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SAMPLE_RFP_PATH = PROJECT_ROOT / "data" / "sample_rfp.md"
REQUIREMENT_PATTERN = re.compile(
    r"^\d+\. \*\*(RFP-\d{3})\*\* (.+)$",
    re.MULTILINE,
)
EXPECTED_REQUIREMENT_IDS = tuple(f"RFP-{number:03d}" for number in range(1, 25))


class SampleRequirement(BaseModel):
    """One stable synthetic requirement available to the local UI."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    requirement_id: str = Field(pattern=r"^RFP-\d{3}$")
    text: str = Field(min_length=1)

    @property
    def display_label(self) -> str:
        return f"{self.requirement_id} — {self.text}"


def load_sample_requirements(
    path: str | Path = DEFAULT_SAMPLE_RFP_PATH,
) -> tuple[SampleRequirement, ...]:
    """Load the complete ordered sample set and fail closed on drift."""

    source_path = Path(path)
    matches = REQUIREMENT_PATTERN.findall(source_path.read_text(encoding="utf-8"))
    requirements = tuple(
        SampleRequirement(requirement_id=requirement_id, text=text.strip())
        for requirement_id, text in matches
    )
    observed_ids = tuple(item.requirement_id for item in requirements)
    if observed_ids != EXPECTED_REQUIREMENT_IDS:
        raise ValueError("sample RFP must contain the ordered requirements RFP-001 through RFP-024")
    if len(set(observed_ids)) != len(observed_ids):
        raise ValueError("sample RFP requirement IDs must be unique")
    return requirements


def requirement_by_id(
    requirements: tuple[SampleRequirement, ...],
    requirement_id: str,
) -> SampleRequirement:
    """Return one exact sample requirement or fail closed."""

    for requirement in requirements:
        if requirement.requirement_id == requirement_id:
            return requirement
    raise ValueError(f"unknown sample requirement ID: {requirement_id}")
