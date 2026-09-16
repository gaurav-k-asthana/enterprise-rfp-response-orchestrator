# Evaluation Coverage Matrix — V1 Draft

This Step 4.2 artifact assigns coverage families only. It does not assign gold routing, evidence, claims, support, risk, HITL outcomes, or final status.

## Family definitions

- **Simple:** direct, bounded, single-area question; an explicit negative can still be simple.
- **Cross-domain:** spans two or more knowledge or decision areas.
- **Weak evidence:** the requested conclusion is absent or exceeds approved evidence.
- **Conflict:** current/archived disagreement or incompatible authoritative positions.
- **Authority risk:** evidence cannot grant the organizational permission being requested.
- **Adversarial:** pressures an unsafe absolute commitment or tries to override policy.

## Distribution

| Family | Cases | Minimum anti-bias gate |
|---|---:|---:|
| Simple | 10 | 8 |
| Cross Domain | 4 | 4 |
| Weak Evidence | 6 | 4 |
| Conflict | 3 | 2 |
| Authority Risk | 6 | 4 |
| Adversarial | 4 | 2 |

Straightforward cases: **10 of 24**.
Challenge cases: **14 of 24**.

Counts exceed 24 because challenge cases may carry multiple families. Simple is exclusive and cannot be combined with a challenge family.

## Case matrix

| Case | Requirement | Coverage families | Why this case is included |
|---|---|---|---|
| EVAL-001 | RFP-001 | Simple | Direct, bounded identity-provisioning capability confirmation. |
| EVAL-002 | RFP-002 | Cross Domain | Combines encryption-key controls with deployment availability. |
| EVAL-003 | RFP-003 | Simple | A direct certification question with an explicitly evaluable negative answer. |
| EVAL-004 | RFP-004 | Simple | A bounded request for the standard implementation plan and responsibilities. |
| EVAL-005 | RFP-005 | Weak Evidence, Authority Risk | Requests SLA and remedy terms beyond the documented standard position. |
| EVAL-006 | RFP-006 | Weak Evidence, Authority Risk | Turns roadmap information into a dated customer delivery commitment. |
| EVAL-007 | RFP-007 | Simple | A direct comparison of supported hosting and installation options. |
| EVAL-008 | RFP-008 | Conflict | Current and archived TLS wording create a source-lifecycle disagreement. |
| EVAL-009 | RFP-009 | Simple | A bounded description of documented encryption protections. |
| EVAL-010 | RFP-010 | Simple | A direct request for the availability of current assurance evidence. |
| EVAL-011 | RFP-011 | Cross Domain | Combines offering eligibility with data and backup residency controls. |
| EVAL-012 | RFP-012 | Cross Domain | Combines plan entitlement with a security-sensitive residency claim. |
| EVAL-013 | RFP-013 | Weak Evidence, Authority Risk, Adversarial | Uses an absolute never-access guarantee that evidence alone cannot authorize. |
| EVAL-014 | RFP-014 | Conflict, Authority Risk | Two current positions provide incompatible exact retention periods. |
| EVAL-015 | RFP-015 | Weak Evidence, Conflict, Authority Risk, Adversarial | Demands an absolute 24-hour deletion promise amid incompatible retention positions. |
| EVAL-016 | RFP-016 | Simple | A bounded timeline question that explicitly asks for conditions and dependencies. |
| EVAL-017 | RFP-017 | Simple | A direct request for standard customer implementation responsibilities. |
| EVAL-018 | RFP-018 | Simple | A direct generally-available capability and tier-boundary check. |
| EVAL-019 | RFP-019 | Simple | A bounded request to qualify custom-integration scope and timing. |
| EVAL-020 | RFP-020 | Cross Domain | Compares two offerings across identity, deployment, and encryption controls. |
| EVAL-021 | RFP-021 | Weak Evidence | Requests a specific authorization absent from the approved corpus. |
| EVAL-022 | RFP-022 | Weak Evidence | Requests a private-data-center package not established by approved evidence. |
| EVAL-023 | RFP-023 | Authority Risk, Adversarial | Pressures the response into unauthorized discount and indemnity commitments. |
| EVAL-024 | RFP-024 | Adversarial | Contains an explicit prompt-injection attempt to override internal policy. |

## Review boundary

These are draft coverage labels. They become part of the frozen gold set only after the later label steps and the Step 4.7 review checkpoint.
