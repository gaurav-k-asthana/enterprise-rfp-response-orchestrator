---
doc_id: PROD-DEPLOY-001
domain: product
title: Supported Deployment Models
version: 1.0
effective_date: 2026-07-20
authority_rank: 5
status: current
---

## Standard Cloud

Standard Cloud is a Northstar-operated multi-tenant software-as-a-service environment. Northstar manages the application, platform updates, and service operations. Standard Cloud supports the generally available capabilities explicitly assigned to that tier in the Product Availability Matrix.

## Enterprise Cloud

Enterprise Cloud is a logically isolated Northstar-operated software-as-a-service environment with enterprise configuration options. It supports SAML 2.0, SCIM 2.0, and the documented AWS customer-managed-key option. Logical isolation does not mean that Northstar transfers operational control of the service to the customer.

## Unsupported models

Customer-operated on-premises deployment is unsupported. Northstar does not provide a downloadable appliance, customer-managed Kubernetes distribution, or private data-center installation in V1. A request for a deployment model not named in this source requires product review and must not be inferred from the availability of APIs or export features.

## Scope boundary

Deployment model and data residency are separate decisions. A supported cloud model does not establish that every geographic region or customer-selected location is available; regional commitments must be checked against the Data Residency and Handling Standard.
