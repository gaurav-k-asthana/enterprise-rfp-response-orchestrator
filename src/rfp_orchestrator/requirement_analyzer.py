"""Deterministic Step 2.1 decomposition of untrusted RFP text into atomic requirements."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from rfp_orchestrator.models import Requirement

MAX_ATOMIC_REQUIREMENTS = 12


class RequirementDecompositionError(ValueError):
    """Raised when requirement text cannot be decomposed safely."""


_LEADING_LABEL = re.compile(
    r"^\s*(?:\d+\.\s*)?(?:\*\*[A-Z][A-Z0-9]*-\d+\*\*\s*)?",
    re.IGNORECASE,
)
_ACTION_WORDS = (
    "accept",
    "commit",
    "compare",
    "confirm",
    "describe",
    "explain",
    "guarantee",
    "identify",
    "list",
    "provide",
    "state",
)
_EXPLICIT_ACTION_BOUNDARY = re.compile(
    rf"\s+and\s+(?=(?:{'|'.join(_ACTION_WORDS)})\b)",
    re.IGNORECASE,
)


def _normalize_source_text(text: str) -> str:
    normalized = " ".join(text.split())
    normalized = _LEADING_LABEL.sub("", normalized).strip()
    normalized = normalized.rstrip(".?!; ")
    if not normalized:
        raise RequirementDecompositionError("requirement text cannot be blank")
    return normalized


def _finish(text: str) -> str:
    value = " ".join(text.split()).strip(" ,.;")
    if not value:
        raise RequirementDecompositionError("atomic requirement cannot be blank")
    return value[0].upper() + value[1:] + "."


def _split_oxford_list(text: str) -> list[str]:
    """Split a clear comma list while leaving ordinary prose unchanged."""

    normalized = re.sub(r",?\s+and\s+", ", ", text, flags=re.IGNORECASE)
    items = [item.strip(" ,") for item in normalized.split(",") if item.strip(" ,")]
    return items if len(items) >= 2 else [text.strip()]


def _split_compare_dimensions(text: str) -> list[str] | None:
    match = re.fullmatch(r"(?P<prefix>Compare .+? for) (?P<items>.+)", text, re.IGNORECASE)
    if match is None or "," not in match.group("items"):
        return None
    return [f"{match.group('prefix')} {item}" for item in _split_oxford_list(match.group("items"))]


def _split_affected_dimensions(text: str) -> list[str] | None:
    match = re.fullmatch(
        r"(?P<prefix>Explain .+? would affect) (?P<items>.+)",
        text,
        re.IGNORECASE,
    )
    if match is None or "," not in match.group("items"):
        return None
    return [f"{match.group('prefix')} {item}" for item in _split_oxford_list(match.group("items"))]


def _split_shared_action_list(text: str) -> list[str] | None:
    match = re.fullmatch(
        r"(?P<action>Describe|Identify|State) (?P<items>.+)",
        text,
        re.IGNORECASE,
    )
    if match is None or "," not in match.group("items"):
        return None

    items = _split_oxford_list(match.group("items"))
    if len(items) < 3:
        return None

    shared_suffix = ""
    suffix_match = re.fullmatch(
        r"(?P<item>.+?) (?P<suffix>required during implementation)",
        items[-1],
        re.IGNORECASE,
    )
    if suffix_match is not None:
        items[-1] = suffix_match.group("item")
        shared_suffix = f" {suffix_match.group('suffix')}"

    action = match.group("action")
    return [f"{action} {item}{shared_suffix}" for item in items]


def _split_support_pair(text: str) -> list[str] | None:
    match = re.fullmatch(
        r"(?P<prefix>Confirm support for) (?P<first>.+?) and (?P<second>.+)",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return [
        f"{match.group('prefix')} {match.group('first')}",
        f"{match.group('prefix')} {match.group('second')}",
    ]


def _split_encryption_pair(text: str) -> list[str] | None:
    match = re.fullmatch(
        r"(?P<prefix>Describe how .+? is encrypted) (?P<first>in transit) and "
        r"(?P<second>at rest)",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return [
        f"{match.group('prefix')} {match.group('first')}",
        f"{match.group('prefix')} {match.group('second')}",
    ]


def _split_residency_pair(text: str) -> list[str] | None:
    match = re.fullmatch(
        r"(?P<prefix>Confirm that .+?) (?P<first>customer content) and "
        r"(?P<second>production backups) (?P<suffix>can reside .+)",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return [
        f"{match.group('prefix')} {match.group('first')} {match.group('suffix')}",
        f"{match.group('prefix')} {match.group('second')} {match.group('suffix')}",
    ]


def _split_assurance_pair(text: str) -> list[str] | None:
    match = re.fullmatch(
        r"(?P<prefix>Confirm whether current) (?P<first>SOC 2 Type II) and "
        r"(?P<second>ISO 27001) (?P<suffix>assurance evidence is available for review)",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    return [
        f"{match.group('prefix')} {match.group('first')} {match.group('suffix')}",
        f"{match.group('prefix')} {match.group('second')} {match.group('suffix')}",
    ]


def _split_commercial_pair(text: str) -> list[str] | None:
    match = re.fullmatch(
        r"(?P<prefix>Accept) (?P<first>.+? discount) and "
        r"(?P<second>unlimited indemnity)(?P<suffix> as part of this response)?",
        text,
        re.IGNORECASE,
    )
    if match is None:
        return None
    suffix = match.group("suffix") or ""
    return [
        f"{match.group('prefix')} {match.group('first')}{suffix}",
        f"{match.group('prefix')} {match.group('second')}{suffix}",
    ]


@dataclass(frozen=True)
class _Rule:
    name: str
    split: Callable[[str], list[str] | None]


_DECOMPOSITION_RULES = (
    _Rule("compare_dimensions", _split_compare_dimensions),
    _Rule("affected_dimensions", _split_affected_dimensions),
    _Rule("shared_action_list", _split_shared_action_list),
    _Rule("support_pair", _split_support_pair),
    _Rule("encryption_pair", _split_encryption_pair),
    _Rule("residency_pair", _split_residency_pair),
    _Rule("assurance_pair", _split_assurance_pair),
    _Rule("commercial_pair", _split_commercial_pair),
)


def _decompose_clause(clause: str) -> list[str]:
    for rule in _DECOMPOSITION_RULES:
        pieces = rule.split(clause)
        if pieces is not None:
            return pieces
    return [clause]


def decompose_requirement(text: str) -> list[str]:
    """Return stable, de-duplicated atomic statements without using a model.

    Only explicit, high-confidence patterns are split. Ambiguous prose is kept intact
    so later analysis can request clarification instead of changing customer meaning.
    """

    source = _normalize_source_text(text)
    top_level_clauses = _EXPLICIT_ACTION_BOUNDARY.split(source)
    atoms = [
        _finish(piece)
        for clause in top_level_clauses
        for piece in _decompose_clause(clause.strip())
    ]
    if len(atoms) > MAX_ATOMIC_REQUIREMENTS:
        raise RequirementDecompositionError(
            f"requirement produced {len(atoms)} atomic items; "
            f"the safe maximum is {MAX_ATOMIC_REQUIREMENTS}"
        )

    unique_atoms: list[str] = []
    seen: set[str] = set()
    for atom in atoms:
        key = atom.casefold()
        if key not in seen:
            seen.add(key)
            unique_atoms.append(atom)
    atoms = unique_atoms
    return atoms


def analyze_requirement(requirement: Requirement) -> Requirement:
    """Return a copy with atomic requirements populated and all other fields preserved."""

    return requirement.model_copy(
        update={"atomic_requirements": decompose_requirement(requirement.original_text)}
    )
