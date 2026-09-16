# Verified V1 Evaluation Metrics

**Scope:** Frozen synthetic 24-case primary comparison, single generalist versus orchestrated peers. This is a descriptive portfolio table, not a production-readiness claim.

| Metric | Single generalist | Orchestrated peers |
|---|---:|---:|
| Safe Completion Rate | 20/24 (83.3%) | 10/24 (41.7%) |
| Execution success | 24/24 | 20/24 |
| Routing macro F1 | 0.972 | 0.833 |
| Evidence Recall@5 | 0.944 | 0.786 |
| Unsupported-claim rate | 1.5% | 28.6% |
| Groundedness | 98.5% | 69.8% |
| HITL F1 | 0.857 | 0.889 |
| Conflict-detection F1 | 0.000 | 0.000 |
| Recovery-detection F1 | 0.000 | 0.222 |
| Observed mean latency | 7,192 ms | 9,734 ms |
| Observed estimated generation cost | $0.195032 | $0.250952 |
| Preserved primary failures | 0 | 4 |

Safe Completion Rate counts a safely finalized or correctly escalated case in the numerator; all requested cases, including execution failures, remain in the denominator. Cost and latency rows describe observed successful records and are not an invoice or complete cost of failed attempts. The estimate uses the frozen pricing snapshot and excludes retrieval-provider usage.

The single generalist is the **bounded preference for this synthetic V1 evaluation**. The full approved run accounted for 64 architecture executions and preserved 19 failures. The shared 128-generation-call ceiling was exhausted; 16 of 24 repeat-set observations failed at the budget boundary, so repeat variability is inconclusive. Neither architecture achieved nonzero conflict-detection F1. These results do not establish universal architecture superiority or production readiness.

**Verified provenance:** [Human approval record](../data/evaluation/provider_evaluation_final_approval_step_4_g8.json) binds [final analysis Markdown](../outputs/evaluation/provider_evaluation_final_step_4_g8.md) SHA-256 `fd2e20fa430248463c3267f29c5cde663cc8230c9b5cb7ffbd31a77faf2f9a08` and [final analysis JSON](../outputs/evaluation/provider_evaluation_final_step_4_g8.json) SHA-256 `84edc4919789043e30dc6c78b672475627c5906f515af238faf78ac4bb61bca8`. The source reports retained original draft/review labels because it was kept immutable; the separate approval record marks the reviewed decision as approved. `outputs/` is Git-ignored, so these source reports are available in this local workspace but not automatically in a source-only clone.
