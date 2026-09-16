# Northstar Synthetic Corpus Inventory

This inventory records the completed Step 1.12 synthetic knowledge base and the deliberate evidence fixtures that later retrieval and orchestration tests must preserve. It describes a fictitious company and must not be treated as real enterprise documentation.

## Trusted knowledge-base inventory

Only Markdown sources inside `data/kb/` are trusted retrieval evidence. The V1 corpus now contains 12 sources: 4 Product, 7 Security/Compliance or policy, and 1 Implementation. Eleven are current and one is deliberately archived.

| Source ID | File | Domain | Coverage | Authority / status |
|---|---|---|---|---|
| `PROD-CAP-001` | `product_capabilities.md` | Product | Identity, provisioning, key management, integration boundaries | Rank 4 / current |
| `PROD-AVAIL-001` | `product_availability.md` | Product | GA, Roadmap, Unsupported, tier and hosting qualifications | Rank 5 / current |
| `PROD-DEPLOY-001` | `deployment_models.md` | Product | Standard Cloud, Enterprise Cloud, unsupported on-premises models | Rank 5 / current |
| `PROD-SLA-001` | `service_levels.md` | Product | Qualified 99.9% standard target and nonstandard SLA boundary | Rank 5 / current |
| `SEC-CTRL-001` | `security_controls.md` | Security/Compliance | TLS, AES-256, SOC 2 Type II, ISO 27001, non-FIPS status | Rank 5 / current |
| `SEC-CTRL-OLD-001` | `security_controls_stale.md` | Security/Compliance | Deliberately archived TLS wording for stale-source testing | Rank 2 / archived |
| `SEC-DATA-001` | `data_residency_and_handling.md` | Security/Compliance | US/EU Enterprise residency, US Standard residency, access boundaries | Rank 5 / current |
| `SEC-RET-001` | `data_retention_standard.md` | Security/Compliance | 30-day post-termination retention position | Rank 5 / current |
| `SEC-RET-OPS-001` | `data_retention_operations_addendum.md` | Security/Compliance | Conflicting 90-day operational recovery window | Rank 5 / current |
| `POLICY-AUTH-001` | `authority_matrix.md` | Security/Compliance policy | Human authority for material and nonstandard commitments | Rank 5 / current |
| `POLICY-EVID-001` | `proposal_evidence_policy.md` | Security/Compliance policy | Support, qualification, missing evidence, conflict, and archive rules | Rank 5 / current |
| `IMPL-GUIDE-001` | `implementation_guide.md` | Implementation | Delivery phases, prerequisites, responsibilities, timeline qualifications | Rank 4 / current |

## Coverage assessment

| Required area | Step 1.12 status | Evidence or deliberate condition |
|---|---|---|
| Product capabilities | Covered for V1 | Identity, key management, Salesforce, SAP, and scope boundaries |
| Product availability labels | Covered for V1 | GA, Roadmap, and Unsupported rules and examples |
| Integrations | Covered for V1 | Salesforce GA and SAP Roadmap |
| Core security controls | Covered for V1 | Encryption, TLS, assurance reports, certification boundaries |
| Implementation | Covered for V1 | Phases, prerequisites, customer roles, schedule qualifications |
| Commitment authority | Covered for V1 | Decision rights and mandatory approval categories |
| Deployment models | Covered for V1 | Standard Cloud, Enterprise Cloud, and unsupported customer-operated models |
| Data residency and handling | Covered for V1 | US/EU boundaries, access, migration, and exception handling |
| Data retention | Deliberately conflicted | Equal-authority current sources state 30 and 90 days |
| Standard SLA | Covered for V1 | Qualified 99.9% target; 99.99% and credits require approval |
| Proposal evidence policy | Covered for V1 | Explicit rules for GA, Roadmap, Unsupported, insufficient, conflict, and archived evidence |
| Missing-evidence fixture | Seeded by absence | No trusted KB source supports FedRAMP High; adjacent controls cannot substitute |
| Direct-conflict fixture | Seeded | `SEC-RET-001` and `SEC-RET-OPS-001` remain equally authoritative and incompatible |
| Stale-source fixture | Preserved | Current and archived TLS sources remain independently visible |
| Sample RFP breadth | Complete for V1 | 24 stable requirement IDs cover the five primary demo paths plus adversarial input |

## Expected-behavior fixtures

`data/fixtures/expected_evidence_behaviors.md` describes five evaluation conditions and their expected safe behavior. It is deliberately outside `data/kb/`, so the fixture descriptions themselves cannot become retrieval evidence.

- `FIX-MISSING-001`: FedRAMP High has no supporting source; do not infer or invent authorization.
- `FIX-CONFLICT-001`: preserve both 30-day and 90-day retention passages and require human resolution.
- `FIX-STALE-001`: current TLS evidence outranks, but does not erase, archived evidence.
- `FIX-ROADMAP-001`: SAP Roadmap status does not authorize a delivery date.
- `FIX-AUTHORITY-001`: the 99.9% standard does not authorize 99.99% or service credits.

## Corpus completion rules

1. Every trusted source must retain the metadata contract enforced by `src/rfp_orchestrator/corpus.py`.
2. Missing evidence is represented by no supporting trusted source, never by adding a source that appears to prove the absence.
3. Direct-conflict fixtures keep both values visible so later consistency logic escalates instead of silently choosing.
4. Archived evidence remains retrievable for diagnosis but does not outrank relevant current, higher-authority evidence.
5. Lifecycle and authority affect ranking; neither may erase a relevant contradiction.
6. All material remains synthetic and contains no customer or proprietary data.

## Step 1.12 conclusion

The knowledge-base coverage gaps identified in Step 1.5 are filled for V1. The corpus is now large and varied enough to implement deterministic retrieval while remaining understandable during a demo.

## Step 1.13 addition

The untrusted sample RFP now contains 24 requirements with stable IDs `RFP-001` through `RFP-024`. `data/fixtures/sample_rfp_demo_map.md` maps the preliminary simple, cross-domain, recovery, contradiction, and authority-risk demo paths and separately preserves the prompt-injection case. These path expectations support development and demonstration; they do not freeze the Phase 4 evaluation labels.
