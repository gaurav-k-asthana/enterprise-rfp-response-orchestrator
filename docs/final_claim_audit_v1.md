# Final V1 evidence-to-claim audit

**Audit date:** September 22, 2026

**Release:** `v0.1.0`

**Scope:** Material claims in `README.md`,
`docs/evaluation_metrics_v1.md`, and the generated project report. This is a
submission audit, not a production-readiness assessment.

## Audit method

The review compared public narrative and table values with the frozen gold
set, the immutable human approval record, the locally retained raw/derived
evaluation artifacts, implementation files, automated tests, and final
release checks. The detailed provider outputs remain under Git-ignored
`outputs/evaluation/`; their reviewed SHA-256 values are public so the local
copies can be checked without publishing raw trace content.

## Material claim review

| Public claim | Evidence reviewed | Result |
|---|---|---|
| The system uses three independent peer specialists with no specialist-to-specialist edges. | `src/rfp_orchestrator/graph_topology.py`, `src/rfp_orchestrator/graph_fanout.py`, topology/fan-out tests, and `planning/LANGGRAPH_DESIGN.md`. | Verified. |
| Product and Security/Compliance use domain-locked hybrid Top 5; Implementation uses domain-locked dense semantic Top 5 in the provider path. | `src/rfp_orchestrator/provider_retrieval.py`, `src/rfp_orchestrator/retrieval.py`, provider-query tests, and `planning/DATA_AND_TOOLS.md`. | Verified. The offline Implementation scorer remains a deterministic substitute, not a production embedding claim. |
| Atomic `Claim.supported` values are Boolean while specialist `support_status` is the aggregate `SUPPORTED`/`PARTIAL`/`UNSUPPORTED` enum. | `src/rfp_orchestrator/models.py`, `src/rfp_orchestrator/claim_support.py`, claim-support/specialist tests, and the documented aggregation rule. | Verified. |
| Recovery is bounded at two retrieval attempts and conflict reanalysis at one attempt; unresolved safety or authority conditions stop at checkpointed human review. | `src/rfp_orchestrator/recovery.py`, `conflict_resolution.py`, `risk_authority.py`, `human_review.py`, `graph_fanout.py`, and their tests. | Verified for the implemented deterministic graph. |
| The Streamlit map reflects execution events and observed arrows, and the UI exports a simple reviewable DOCX without rerunning the graph. | `src/rfp_orchestrator/execution_events.py`, UI/map/DOCX modules, `tests/test_demo_clean_start.py`, and `tests/test_demo_map_docx.py`. | Verified across the frozen five-case demo. Page-by-page visual DOCX review remains non-exhaustive as disclosed. |
| The primary provider comparison used a frozen 24-case synthetic set and preserved failures in denominators. | `data/evaluation/evaluation_cases_v1.json`, the approved final analysis, raw local archives, and metric-generation tests. | Verified. Primary execution success was 24/24 for the generalist and 20/24 for peers; four peer primary failures remain visible. |
| Primary Safe Completion was 20/24 (83.3%) for the single generalist and 10/24 (41.7%) for orchestrated peers. | Local final-analysis JSON SHA-256 `84edc4919789043e30dc6c78b672475627c5906f515af238faf78ac4bb61bca8`; Markdown SHA-256 `fd2e20fa430248463c3267f29c5cde663cc8230c9b5cb7ffbd31a77faf2f9a08`; `docs/evaluation_metrics_v1.md`. | Verified. The preference is bounded to this frozen synthetic V1 evaluation. |
| The full plan contained 64 architecture executions, preserved 19 failures, exhausted the 128-generation-call ceiling, and left 16/24 repeat observations budget-failed. | Approved final analysis and local raw run archives; `data/evaluation/provider_evaluation_final_approval_step_4_g8.json`. | Verified. Repeat variability is inconclusive. |
| The cumulative frozen-pricing generation estimate was `$0.814364`, excluding retrieval-provider usage. | Approved final analysis, frozen pricing snapshot, and regenerated efficiency report. | Verified as an estimate, not an invoice or total operating cost. |
| Step 5.17 passed 1,309 tests, Ruff, dependency integrity, deterministic result regeneration, reviewed DOCX integrity, and a fresh Streamlit HTTP 200 startup. | Final local command outputs, `PROJECT_JOURNAL.md`, and the regression test added for logical DOCX-package comparison. | Verified. No provider call was made during the release checks. |

## Human approval and interpretation boundary

`data/evaluation/provider_evaluation_final_approval_step_4_g8.json` records
Gaurav Asthana's approval and binds the exact final-analysis hashes above. It
explicitly rejects both a universal multi-agent-superiority claim and a
production-readiness claim. The public report therefore retains the bounded
single-generalist preference, all preserved failures, the repeat-censoring
warning, and the known RFP-006, RFP-015, reviewer-action, conflict-detection,
small-corpus, durability, scale, and authentication limitations.

## Release conclusion

No audited material claim required a metric change or removal. Obsolete draft
and pending-step language was replaced only after the final checks completed.
This audit supports submission of the synthetic V1 portfolio release; it does
not authorize real customer data, autonomous commitments, or production use.
