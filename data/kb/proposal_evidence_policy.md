---
doc_id: POLICY-EVID-001
domain: security
title: Proposal Evidence and Qualification Policy
version: 1.0
effective_date: 2026-07-28
authority_rank: 5
status: current
---

## Evidence standard

Every material proposal claim must be supported by one or more approved knowledge-base passages. Citations must retain document ID, title, version, effective date, authority rank, lifecycle status, and the exact supporting passage. Similar controls, certifications, products, or customer examples are not substitutes for direct evidence.

## Availability language

Generally available capabilities may be described as supported only within the documented tier, hosting, regional, and configuration boundaries. Roadmap items must be labeled as not currently generally available. A roadmap date or delivery promise requires human approval even when an internal plan exists. Unsupported items must not receive a categorical yes answer.

## Insufficient evidence

When no approved source directly supports a material claim, the response must say that the requirement cannot be confirmed from the available evidence. The system may retry retrieval with a reformulated query up to the locked retry limit, but it must not fill the gap from model memory or inference. Unresolved material gaps route to human review with the attempted queries and evidence summary.

## Conflicting evidence

When two applicable current sources of equal or unresolved authority state incompatible values, both sources must be retained and cited in the review payload. The system must mark conflicting evidence, avoid selecting either value automatically, and request an authorized human decision.

## Archived sources

Archived material may remain searchable for diagnosis. A relevant current, higher-authority source ordinarily outranks archived evidence, but the archived passage remains visible when it explains a mismatch or stale answer.
