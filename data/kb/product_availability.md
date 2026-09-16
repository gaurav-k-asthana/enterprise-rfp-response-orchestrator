---
doc_id: PROD-AVAIL-001
domain: product
title: Product Availability Matrix
version: 1.0
effective_date: 2026-07-15
authority_rank: 5
status: current
---

## Availability definitions

`GA` means the capability is generally available for the named tier and deployment boundary. `ROADMAP` means the capability is not generally available and has no customer-committable delivery date unless separately approved through the Proposal Commitment Authority Matrix. `UNSUPPORTED` means the capability must not be represented as currently available.

## Current availability

- SAML 2.0: GA on Enterprise Cloud and Standard Cloud.
- SCIM 2.0: GA on Enterprise Cloud.
- Customer-managed encryption keys: GA on Enterprise Cloud for AWS only.
- Salesforce connector: GA on Enterprise Cloud.
- SAP S/4HANA connector: ROADMAP with no customer-committable date.
- On-premises deployment: UNSUPPORTED.

## Qualification rules

Availability for one tier or hosting environment must not be generalized to another. In particular, AWS customer-managed-key support does not establish equivalent support on another cloud, and a roadmap integration must not be described as production-ready.
