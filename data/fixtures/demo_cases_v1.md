# Five-Case Demo Set — V1

This is the frozen **selection and expected first-run behavior** for the
synthetic, offline demo. The machine-readable source is
[`demo_cases_v1.json`](demo_cases_v1.json). It is bound by SHA-256 to the
sample RFP and the user-approved 24-case evaluation set. It does not change
the evaluation gold labels or authorize a provider call. The clean-terminal
rehearsal is Step 5.10; map and DOCX verification is Step 5.11.

| Order | Demo path | Select in Streamlit | What should happen on the first run |
|---:|---|---|---|
| 1 | Simple | `RFP-001` | Product alone runs; Security and Implementation stay inactive; grounded answer finalizes with no review. |
| 2 | Cross-domain | `RFP-002` | Product and Security run as peers and merge; Implementation stays inactive; answer finalizes. |
| 3 | Recovery | `RFP-021` | Security cannot verify FedRAMP High; two retrieval retries occur, then the run pauses for human review with no final answer. |
| 4 | Contradiction | `RFP-014` | The current 30-day and 90-day retention sources conflict; one targeted reanalysis occurs, then the run pauses for human review with no final answer. |
| 5 | Authority risk | `RFP-005` | The standard 99.9% position is evidenced, but the requested 99.99% SLA and credits require organizational approval; the run pauses before finalization. |

The graph's **terminal strategy** is `IMMEDIATE_HITL` for the three paused
cases, even though their gold *initial routing family* is `SINGLE_SPECIALIST`.
These are different observations: a specialist is invoked first, then the
governance gate changes the route. For `RFP-014` and `RFP-021`, the gold risk
labels describe the case, while the live graph stops at conflict/recovery
before a later risk-assessment node; an empty live `risk_classes` list is not
evidence that the issue was cleared.

Human review must not be confused with permission to make the requested
promise. `RFP-021` cannot claim FedRAMP High from adjacent certifications;
after exhaustion, only Reject or Add guidance is offered. `RFP-014` cannot
approve away conflicting evidence; its approval controls are disabled while
the conflict remains. `RFP-005` permits an authorized reviewer to approve a
specific narrow proposal or take another valid review action, but the frozen
first-run expectation is **NEEDS_HUMAN**, not automatic acceptance of the
customer's requested term. Any reviewer continuation is a separate demo
branch, not a sixth frozen case.

To inspect this selection in VS Code, open this Markdown file and use
**Preview** (`Shift+Cmd+V` on macOS). Open the JSON file beside it if you want
the exact input text, selected specialists, counters, stop reason, and source
hashes. The automated checks in `tests/test_demo_cases_v1.py` compare all five
entries with the frozen evaluation labels and run every case through the real
checkpointed offline graph. Changing the case list or either source requires
a reviewed V2 manifest and matching tests; do not quietly edit V1.
