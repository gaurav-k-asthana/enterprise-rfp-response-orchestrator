---
doc_id: SEC-RET-OPS-001
domain: security
title: Data Retention Operations Addendum
version: 1.0
effective_date: 2026-07-25
authority_rank: 5
status: current
---

## Operational deletion window

After contract termination, the operations runbook provides a 90-calendar-day recovery window before customer content is scheduled for deletion from production systems. The window is described as necessary for restoration requests, billing closeout, and controlled deprovisioning.

## Backup expiration

Backup copies may remain until the applicable encrypted backup set expires through normal rotation. They are isolated from active customer use and are not restored without an approved operational request.

## Commitment boundary

The operational runbook must not be converted into proposal language without checking the approved Customer Data Retention Standard and the Proposal Commitment Authority Matrix. A customer-specific deletion date requires human approval.

## Evaluation fixture notice

This source intentionally conflicts with `SEC-RET-001`, which states a 30-calendar-day post-termination period. Both documents are current and have equal authority so lifecycle or rank sorting cannot legitimately hide the disagreement. The system must surface both values rather than select one automatically.
