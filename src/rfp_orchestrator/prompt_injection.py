"""Deterministic detection of high-confidence instructions inside untrusted RFP text."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rfp_orchestrator.models import (
    InjectionSignalType,
    PromptInjectionSignal,
    Requirement,
)


@dataclass(frozen=True)
class _DetectionRule:
    signal_type: InjectionSignalType
    pattern: re.Pattern[str]


def _pattern(expression: str) -> re.Pattern[str]:
    return re.compile(expression, re.IGNORECASE)


_DETECTION_RULES = (
    _DetectionRule(
        InjectionSignalType.ROLE_MARKER,
        _pattern(r"\b(?:system|developer|assistant)\s+(?:instructions?|message|prompt)\s*:"),
    ),
    _DetectionRule(
        InjectionSignalType.POLICY_OVERRIDE,
        _pattern(
            r"\b(?:ignore|disregard|bypass|override)\s+(?:all\s+)?"
            r"(?:(?:internal|previous|prior|system)\s+)?"
            r"(?:polic(?:y|ies)|instructions?|rules?|guardrails?)\b"
        ),
    ),
    _DetectionRule(
        InjectionSignalType.FORCED_RESPONSE,
        _pattern(
            r"\b(?:answer|respond|reply)\s+(?:only\s+)?(?:yes|no)\b"
            r"(?:\s+to\s+(?:every|all)\s+(?:remaining\s+)?"
            r"(?:questions?|requirements?))?"
        ),
    ),
    _DetectionRule(
        InjectionSignalType.ROLE_REASSIGNMENT,
        _pattern(
            r"\b(?:you\s+are\s+now|act\s+as|pretend\s+to\s+be)\s+"
            r"(?:the\s+)?(?:system|developer|administrator)\b"
        ),
    ),
    _DetectionRule(
        InjectionSignalType.SENSITIVE_DISCLOSURE,
        _pattern(
            r"\b(?:reveal|show|print|expose)\s+(?:the\s+)?"
            r"(?:system\s+prompt|developer\s+message|api\s+key|credentials?|secrets?)\b"
        ),
    ),
)


def detect_prompt_injection(text: str) -> list[PromptInjectionSignal]:
    """Return stable high-confidence signals without interpreting the text as instructions."""

    signals = [
        PromptInjectionSignal(
            signal_type=rule.signal_type,
            matched_text=match.group(0),
            start_index=match.start(),
            end_index=match.end(),
        )
        for rule in _DETECTION_RULES
        for match in rule.pattern.finditer(text)
    ]
    signals.sort(key=lambda item: (item.start_index, item.end_index, item.signal_type.value))
    return signals


def assess_prompt_injection(requirement: Requirement) -> Requirement:
    """Return a validated copy with signals while preserving source text and prior analysis."""

    signals = detect_prompt_injection(requirement.original_text)
    payload = requirement.model_dump()
    payload.update(
        {
            "prompt_injection_detected": bool(signals),
            "prompt_injection_signals": [signal.model_dump() for signal in signals],
        }
    )
    return Requirement.model_validate(payload)
