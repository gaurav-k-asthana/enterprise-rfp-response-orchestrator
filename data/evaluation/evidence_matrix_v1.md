# Evaluation Evidence Matrix — V1 Draft

This Step 4.4 artifact records answer evidence, not every related Top-5 result. Governance policy is evaluated separately from specialist retrieval and is not added merely to make an authority-sensitive answer look supported.

## Authority-order rule

1. Relevant current evidence precedes relevant archived evidence.
2. Within the same lifecycle status, higher authority rank precedes lower rank.
3. Same-status, same-rank sources share one tier; their order does not resolve a conflict.
4. Missing direct evidence is represented by an empty gold set, never by a document claiming absence.

## Case matrix

| Case | Requirement | Gold evidence IDs in authority order | Why |
|---|---|---|---|
| EVAL-001 | RFP-001 | Current rank 5: `PROD-AVAIL-001::chunk-001`, `PROD-DEPLOY-001::chunk-001`<br>Current rank 4: `PROD-CAP-001::chunk-001` | Availability and deployment sources establish tier support; the catalog adds capability detail. |
| EVAL-002 | RFP-002 | Current rank 5: `PROD-AVAIL-001::chunk-001`, `PROD-DEPLOY-001::chunk-001`, `SEC-CTRL-001::chunk-001`<br>Current rank 4: `PROD-CAP-001::chunk-001` | The response needs key availability, deployment boundaries, and the matching security control. |
| EVAL-003 | RFP-003 | Current rank 5: `SEC-CTRL-001::chunk-001` | The current controls matrix explicitly states the negative FIPS status. |
| EVAL-004 | RFP-004 | Current rank 4: `IMPL-GUIDE-001::chunk-001` | The implementation guide contains the phases, prerequisites, and customer responsibilities. |
| EVAL-005 | RFP-005 | Current rank 5: `PROD-SLA-001::chunk-001`, `PROD-SLA-001::chunk-002` | Both SLA chunks are needed for the standard target, exclusions, and non-acceptance boundary. |
| EVAL-006 | RFP-006 | Current rank 5: `PROD-AVAIL-001::chunk-001`<br>Current rank 4: `PROD-CAP-001::chunk-002` | The availability matrix controls roadmap status; the catalog reinforces the no-date boundary. |
| EVAL-007 | RFP-007 | Current rank 5: `PROD-AVAIL-001::chunk-001`, `PROD-DEPLOY-001::chunk-001` | The two current Product sources describe supported cloud models and explicit on-premises exclusion. |
| EVAL-008 | RFP-008 | Current rank 5: `SEC-CTRL-001::chunk-001`<br>Archived rank 2: `SEC-CTRL-OLD-001::chunk-001` | The current TLS statement must outrank—but not hide—the archived contradictory wording. |
| EVAL-009 | RFP-009 | Current rank 5: `SEC-CTRL-001::chunk-001` | The current controls matrix directly covers encryption in transit and at rest. |
| EVAL-010 | RFP-010 | Current rank 5: `SEC-CTRL-001::chunk-001` | The current controls matrix directly records SOC 2 Type II and ISO 27001 assurance. |
| EVAL-011 | RFP-011 | Current rank 5: `PROD-DEPLOY-001::chunk-001`, `PROD-DEPLOY-001::chunk-002`, `SEC-DATA-001::chunk-001` | Product establishes the offering boundary while Security establishes EU content and backup residency. |
| EVAL-012 | RFP-012 | Current rank 5: `PROD-DEPLOY-001::chunk-001`, `PROD-DEPLOY-001::chunk-002`, `SEC-DATA-001::chunk-001` | The plan and residency sources jointly establish the Standard Cloud limitation. |
| EVAL-013 | RFP-013 | Current rank 5: `SEC-DATA-001::chunk-001` | The handling standard explicitly refuses an absolute in-region operational-access guarantee. |
| EVAL-014 | RFP-014 | Current rank 5: `SEC-RET-001::chunk-001`, `SEC-RET-OPS-001::chunk-001` | Both current, equal-rank retention values are required and neither outranks the other. |
| EVAL-015 | RFP-015 | Current rank 5: `SEC-RET-001::chunk-001`, `SEC-RET-OPS-001::chunk-001` | Both retention sources are material to the unsupported 24-hour content-and-backup deletion demand. |
| EVAL-016 | RFP-016 | Current rank 4: `IMPL-GUIDE-001::chunk-001`, `IMPL-GUIDE-001::chunk-002` | The two guide chunks cover duration, start conditions, schedule changes, and approval qualification. |
| EVAL-017 | RFP-017 | Current rank 4: `IMPL-GUIDE-001::chunk-001` | The first guide chunk lists customer roles, data, access, decisions, and test participation. |
| EVAL-018 | RFP-018 | Current rank 5: `PROD-AVAIL-001::chunk-001`<br>Current rank 4: `PROD-CAP-001::chunk-002` | The availability matrix governs GA and tier scope; the catalog corroborates Salesforce availability. |
| EVAL-019 | RFP-019 | Current rank 4: `IMPL-GUIDE-001::chunk-001`, `IMPL-GUIDE-001::chunk-002` | Both guide chunks explain scope changes, timeline effects, and separate plan approval. |
| EVAL-020 | RFP-020 | Current rank 5: `PROD-AVAIL-001::chunk-001`, `PROD-DEPLOY-001::chunk-001`, `SEC-CTRL-001::chunk-001`<br>Current rank 4: `PROD-CAP-001::chunk-001` | The comparison needs tier availability, deployment models, identity detail, and key-control scope. |
| EVAL-021 | RFP-021 | **None** | No approved chunk directly establishes FedRAMP High authorization; adjacent controls are not gold evidence. |
| EVAL-022 | RFP-022 | Current rank 5: `PROD-AVAIL-001::chunk-001`, `PROD-DEPLOY-001::chunk-001` | Both Product sources explicitly exclude the requested customer-operated deployment package. |
| EVAL-023 | RFP-023 | **None** | The route stops for organizational authority before retrieval, so it has no answer-evidence gold IDs. |
| EVAL-024 | RFP-024 | **None** | The prompt-injection route stops before retrieval, so it has no answer-evidence gold IDs. |

## Important edge cases

- **RFP-008:** the rank-5 current TLS source precedes the rank-2 archived source, but the archived mismatch remains visible.
- **RFP-014:** the 30-day and 90-day sources share one current rank-5 tier; ordering cannot settle the contradiction.
- **RFP-021:** adjacent security controls do not establish FedRAMP High, so the direct-answer gold set is empty.
- **RFP-023 and RFP-024:** both stop before specialist retrieval.

These draft labels become frozen only after the remaining gold fields and the Step 4.7 review checkpoint are complete.
