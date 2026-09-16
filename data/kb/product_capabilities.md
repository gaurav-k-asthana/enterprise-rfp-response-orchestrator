---
doc_id: PROD-CAP-001
domain: product
title: Northstar Product Capability Catalog
version: 1.0
effective_date: 2026-07-01
authority_rank: 4
status: current
---

## Identity and access

Northstar Enterprise Cloud supports SAML 2.0 single sign-on and SCIM 2.0 user provisioning as generally available capabilities. SAML can be configured with a customer identity provider during implementation. SCIM supports automated user creation, update, deactivation, and group-based assignment for Enterprise Cloud customers.

Local username and password access can be disabled after a customer administrator validates SAML. Northstar does not claim support for proprietary identity protocols that are not named in approved product documentation.

## Encryption key management

Customer-managed encryption keys are generally available for Enterprise Cloud deployments hosted on AWS. Key setup requires an approved AWS key policy and validation during implementation. Customer-managed keys are not supported for the Standard Cloud tier or for hosting environments not explicitly listed in the Product Availability Matrix.

## Integrations

Salesforce is a generally available integration. SAP S/4HANA integration is a roadmap item and is not generally available. Roadmap status indicates product intent only; it does not authorize a delivery date or customer-specific commitment.

## Capability interpretation

A capability described as generally available may be presented as supported only within its documented tier, hosting, and configuration boundaries. Items not named here or in a higher-authority availability source require additional evidence rather than an inferred categorical answer.
