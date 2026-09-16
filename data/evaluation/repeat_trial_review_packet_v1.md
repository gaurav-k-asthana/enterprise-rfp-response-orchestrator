# Repeat-Trial Plan — V1 Review Packet

**Status:** AWAITING_APPROVAL; provider execution is not authorized.
**Plan SHA-256:** `77acb469316289d92871d8450d35f7975d5b2cddbead1f6a81f710b6a5f88b2a`

## Proposed repeated cases

| Case | Requirement | Why variability matters | Total trials |
|---|---|---|---:|
| EVAL-001 | RFP-001 | Simple directly supported Product case used as a low-complexity stability control. | 3 |
| EVAL-002 | RFP-002 | Cross-domain case where variable tool selection or peer synthesis could change coverage. | 3 |
| EVAL-015 | RFP-015 | Combined weak-evidence, conflict, authority, and adversarial case where safe escalation must remain stable. | 3 |
| EVAL-021 | RFP-021 | Absent direct evidence tests whether unsupported assurance and bounded recovery remain stable. | 3 |

Trial 1 is the case's primary comparison run. Only Trials 2 and 3 are additional repeats.
EVAL-023 and EVAL-024 are not repeated because their correct deterministic pre-model stops remove model variability.

## Execution and cost ceiling

- Primary paired executions: 48
- Additional repeat executions: 16
- Maximum architecture executions: 64
- Maximum provider calls: 128
- Proposed hard cost cap: $5.12
- Currently authorized spend: $0.00
- Automatic provider retries: forbidden
- Stop before the next call if any call, token, execution, or cost ceiling would be exceeded.

The $5.12 value is a worst-case ceiling calculated from the frozen dated pricing snapshot and token envelope, not an expected charge or spending target.

## Approval boundary

No provider comparison or repeated trial may run until the user explicitly approves this exact plan and names an authorized USD cap no greater than $5.12. Approval of this review packet does not itself implement or execute a provider-backed architecture.
