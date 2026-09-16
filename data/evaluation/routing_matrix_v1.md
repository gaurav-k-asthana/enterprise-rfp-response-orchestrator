# Evaluation Routing Matrix — V1 Draft

This Step 4.3 artifact labels the initial decision immediately after requirement analysis. Later recovery, conflict, risk, HITL, and finalization transitions are not encoded as the initial strategy.

## Distribution

| Initial strategy | Cases |
|---|---:|
| Single Specialist | 18 |
| Parallel Specialists | 4 |
| Immediate Hitl | 2 |

| Expected domain / selected peer | Case memberships |
|---|---:|
| Product | 10 |
| Security/Compliance | 12 |
| Implementation | 4 |

Domain memberships total 26 because four cross-domain cases each select two peers. Immediate-HITL cases select no specialist.

## Case matrix

| Case | Requirement | Expected domains | Initial strategy | Selected peer specialists | Why |
|---|---|---|---|---|---|
| EVAL-001 | RFP-001 | Product | Single Specialist | Product | Identity provisioning is a Product capability. |
| EVAL-002 | RFP-002 | Product, Security/Compliance | Parallel Specialists | Product, Security/Compliance | Key availability is Product-scoped while encryption controls are Security-scoped. |
| EVAL-003 | RFP-003 | Security/Compliance | Single Specialist | Security/Compliance | Certification status belongs to Security/Compliance. |
| EVAL-004 | RFP-004 | Implementation | Single Specialist | Implementation | Plans, prerequisites, and customer responsibilities are Implementation concerns. |
| EVAL-005 | RFP-005 | Product | Single Specialist | Product | The initial evidence route is Product for the documented SLA position. |
| EVAL-006 | RFP-006 | Product | Single Specialist | Product | Connector availability and roadmap status belong to Product. |
| EVAL-007 | RFP-007 | Product | Single Specialist | Product | Supported deployment models and installation availability belong to Product. |
| EVAL-008 | RFP-008 | Security/Compliance | Single Specialist | Security/Compliance | Transport-security protocol versions belong to Security/Compliance. |
| EVAL-009 | RFP-009 | Security/Compliance | Single Specialist | Security/Compliance | Encryption in transit and at rest belongs to Security/Compliance. |
| EVAL-010 | RFP-010 | Security/Compliance | Single Specialist | Security/Compliance | Assurance reports and certifications belong to Security/Compliance. |
| EVAL-011 | RFP-011 | Product, Security/Compliance | Parallel Specialists | Product, Security/Compliance | Offering eligibility is Product-scoped; content and backup residency are Security-scoped. |
| EVAL-012 | RFP-012 | Product, Security/Compliance | Parallel Specialists | Product, Security/Compliance | Plan entitlement and residency controls require Product and Security peers. |
| EVAL-013 | RFP-013 | Security/Compliance | Single Specialist | Security/Compliance | Regional data-access controls and the requested exception belong to Security/Compliance. |
| EVAL-014 | RFP-014 | Security/Compliance | Single Specialist | Security/Compliance | Post-termination content retention belongs to Security/Compliance. |
| EVAL-015 | RFP-015 | Security/Compliance | Single Specialist | Security/Compliance | Content and backup deletion controls belong to Security/Compliance. |
| EVAL-016 | RFP-016 | Implementation | Single Specialist | Implementation | Duration, start conditions, and dependencies belong to Implementation. |
| EVAL-017 | RFP-017 | Implementation | Single Specialist | Implementation | Customer roles, access, data, and test resources belong to Implementation. |
| EVAL-018 | RFP-018 | Product | Single Specialist | Product | Connector availability and tier boundaries belong to Product. |
| EVAL-019 | RFP-019 | Implementation | Single Specialist | Implementation | Custom-integration scope, timeline, and approval belong to Implementation. |
| EVAL-020 | RFP-020 | Product, Security/Compliance | Parallel Specialists | Product, Security/Compliance | Offering capabilities span Product while encryption controls require Security. |
| EVAL-021 | RFP-021 | Security/Compliance | Single Specialist | Security/Compliance | FedRAMP authorization status belongs to Security/Compliance before any recovery. |
| EVAL-022 | RFP-022 | Product | Single Specialist | Product | Private-data-center package availability belongs to Product. |
| EVAL-023 | RFP-023 | None | Immediate Hitl | None | Discount and indemnity acceptance requires organizational authority before specialist work. |
| EVAL-024 | RFP-024 | None | Immediate Hitl | None | The embedded operating instruction must stop before specialist selection. |

## Locked interpretation

- Specialists are peers selected by the orchestrator.
- Parallel selection does not create specialist-to-specialist edges.
- The initial strategy is not a prediction of the complete execution trace.
- These draft labels become frozen only after the Step 4.7 review checkpoint.
