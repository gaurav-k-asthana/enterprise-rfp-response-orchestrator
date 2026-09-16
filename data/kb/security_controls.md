---
doc_id: SEC-CTRL-001
domain: security
title: Security Controls Matrix
version: 2.1
effective_date: 2026-07-01
authority_rank: 5
status: current
---

## Encryption controls

Data in transit is protected with TLS 1.2 or later for supported application and API connections. Data at rest is encrypted using AES-256. Encryption statements describe the Northstar service boundary and do not, by themselves, validate a customer's endpoint, identity provider, or downstream export destination.

Customer-managed encryption keys are evidenced only for AWS-hosted Enterprise Cloud deployments. The Product Availability Matrix remains authoritative for tier and hosting availability.

## Independent assurance

Northstar has a current SOC 2 Type II report and is certified to ISO 27001. Reports and certificates may be shared only through the approved security-review process and subject to applicable confidentiality controls.

The platform is not certified to FIPS 140-3. SOC 2 Type II and ISO 27001 must not be used as substitutes for a certification that is not explicitly held.

## Evidence boundaries

Named controls and certifications support only the claims stated in this source. Requirements for an unlisted government authorization, certification level, or regulatory attestation require separate approved evidence and must not be inferred from adjacent controls.
