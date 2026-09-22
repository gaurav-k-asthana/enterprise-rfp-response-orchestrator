# Enterprise RFP Response Orchestrator

A local, synthetic prototype for drafting evidence-grounded RFP responses while making recovery, contradictions, and human authority visible. It is a portfolio build, not a production proposal service. Do not put real customer RFPs, confidential documents, or credentials into the demo.

## Why this project exists

An RFP response can be factually supported yet still unsafe to promise: a roadmap item may not be generally available, two current policies may disagree, or a customer-specific service credit may require approval. This project tests whether an orchestrator can choose the *minimum-cost safe path* for each requirement—one specialist, selected peer specialists in parallel, bounded retrieval recovery, targeted conflict reanalysis, or a human-review stop—while retaining the evidence and decision trail.

The V1 design has three independent peers: Product, Security/Compliance, and Implementation. No specialist calls another specialist. The system checks citations, source authority, atomic-claim support, prior approved commitments, and organizational authority before finalization. A narrow commitment ledger stores only selected, human-approved and finalized commitments; it is not general conversation memory.

The current Streamlit demonstration runs a **deterministic offline graph** over fictitious Northstar Cloud Systems data. The separate, approved Phase 4 comparison used OpenAI generation and Pinecone retrieval to evaluate the same 24 synthetic cases against a single-generalist baseline. The offline UI is not a live provider-backed proposal assistant. Provider graph calls remain disabled by default, and the previous 128-call evaluation ceiling is exhausted.

## Architecture at a glance

```text
Untrusted RFP requirement
  → Requirement Analyzer → Strategy Orchestrator
                             ├─ Product specialist
                             ├─ Security/Compliance specialist
                             └─ Implementation specialist
                     selected peers → Merge
  → citation, source, and claim-support gates
  → bounded retrieval recovery if needed (at most 2 attempts)
  → narrow commitment proposals and consistency check
  → one targeted conflict reanalysis if needed
  → risk/organizational-authority gate
  → guarded final response OR checkpointed human review
```

The diagram shows the main flow; real runs branch and can re-enter selected peers. The LangGraph state carries requirements, evidence IDs, claims, counters, decisions, and approved commitments. A local `InMemorySaver` supports the demo's interrupt/resume flow but is **not durable across process restarts**. The live Streamlit SVG observes LangGraph events; its colored nodes, arrows, and attempt counters do not control graph decisions.

See the [verified RFP-002 architecture snapshot](docs/architecture_execution_rfp002.md) for a completed Product-and-Security path. It is a static capture of the implemented map; the app animates the same status changes during a live run.

For a short walkthrough, use the [five-minute demo script and credential-safe recording checklist](docs/demo_script_and_recording_checklist_v1.md). The recording is user-owned and is not included in this repository.

The [final project report PDF](docs/Enterprise_RFP_Response_Orchestrator_Project_Report.pdf) follows the assignment-report format of the companion portfolio project. Its claims were checked against the frozen evaluation artifacts in the [final evidence-to-claim audit](docs/final_claim_audit_v1.md). The optional user-owned recording is not included in this repository; the report's offline build source is [`scripts/build_project_report.py`](scripts/build_project_report.py).

Product and Security/Compliance use hybrid dense + BM25/sparse retrieval, each capped at Top 5. Implementation uses dense semantic Top 5 in the provider path; the offline UI uses a deterministic semantic substitute for repeatable tests. All searches are domain-locked. A claim has a Boolean `supported` value; a specialist response aggregates its claims as `SUPPORTED`, `PARTIAL`, or `UNSUPPORTED`. Evidence IDs and source lifecycle/authority metadata travel with cited claims.

The approved V1 stack is Python, LangChain, LangGraph, OpenAI API, Pinecone, LangSmith, Streamlit, and `python-docx`. Mem0 and ElevenLabs are not used; Nebius is optional, not a dependency.

## Run locally in VS Code

These instructions assume macOS and the existing project folder at `Documents/AI System Builds/RFP Agentic AI`. If you copied the project elsewhere, use that folder instead. For a first-time setup, install Python 3.10 or newer, open this project with **File → Open Folder…**, then choose **Terminal → New Terminal** in VS Code. Type each line separately:

```bash
cd "/Users/Gaurav_Asthana/Documents/AI System Builds/RFP Agentic AI"
pwd
test -d .venv || python3 -m venv .venv
source .venv/bin/activate
python --version
python -m pip install -c constraints-direct-v1.txt -e '.[dev]'
test -e .env || cp .env.example .env
python -m pytest -p no:cacheprovider -q
python -m ruff check .
```

`pwd` should end in `AI System Builds/RFP Agentic AI`, `python --version` must show 3.10+, and the prompt should begin with `(.venv)` after activation. The offline demo needs **no API key**. Do not overwrite an existing `.env` or paste its values into chat. If VS Code asks for an interpreter, select this project's `.venv/bin/python`. The step-by-step [VS Code beginner guide](planning/VS_CODE_BEGINNER_GUIDE.md) explains the editor and terminal controls.

The [reviewed V1 version record](docs/runtime_versions_v1.md) lists Python and the direct package versions behind this build. The constraints file pins those direct dependencies for a new installation, but it is not a complete transitive lockfile. Do not reinstall packages into a working environment simply to inspect the record.

For later sessions, do not recreate the environment or reinstall packages unless dependencies changed:

```bash
cd "/Users/Gaurav_Asthana/Documents/AI System Builds/RFP Agentic AI"
source .venv/bin/activate
python -m streamlit run app.py
```

Open [http://localhost:8502](http://localhost:8502) when Streamlit reports that it is ready. The project binds to localhost and uses port 8502 so it can coexist with the IRS project on 8501. If 8502 is occupied, do not stop an unidentified process; run `python -m streamlit run app.py --server.port 8503` and open [http://localhost:8503](http://localhost:8503). To stop only the server in your current terminal, press **Control+C** there.

## Walk through the five-case demo

In the sidebar, select a requirement, read its full synthetic text, and click **Run selected requirement**. Wait for the saved-run confirmation before selecting another case. Use the frozen [five-case demo guide](data/fixtures/demo_cases_v1.md) in this order:

| Case | What to watch on the first run |
|---|---|
| `RFP-001` | Product alone; the other peers remain gray; supported answer finalizes. |
| `RFP-002` | Product and Security run as independent peers, then merge; answer finalizes. |
| `RFP-021` | Missing direct FedRAMP High evidence triggers two retrieval attempts, then human review; no final answer. |
| `RFP-014` | Current 30-day and 90-day retention evidence remains in conflict after one targeted reanalysis; human review, no final answer. |
| `RFP-005` | The documented 99.9% standard does not authorize the requested 99.99% SLA and credits; human review, no automatic promise. |

The architecture map lights only observed nodes and traversed arrows. Blue means active, green complete, orange recovery, red blocked/review, and purple state access; gray routes were not invoked. Recovery and conflict nodes show their bounded counters. The summary and detail panel show strategy, peers, evidence, claims, citations, stop reason, and execution trace. The **Download DOCX response** button exports the current saved result without rerunning the graph. A paused case's DOCX states that no final response has been authorized.

The first-run demo ends at the three human-review checkpoints. Reviewer continuation is a separate branch: the UI presents governed review actions, validates the reviewer and decision fields, and resumes against the exact saved checkpoint. Some checkpoints still expose more actions than the gold safety contract permits (see Limitations). Human approval cannot turn missing evidence or an unresolved contradiction into a verified fact. The five first-run paths and their map/DOCX contents are covered by automated tests; the Step 5.11 journal entry records the remaining non-exhaustive page-layout QA limitation.

## How the evidence and safety boundary works

Only the 12 synthetic Markdown sources in [`data/kb/`](data/kb/) are trusted retrieval evidence. The [corpus inventory](data/corpus_inventory.md) describes each source and seeded conditions. The 24 requirements in [`data/sample_rfp.md`](data/sample_rfp.md) are untrusted customer-style input: their text is preserved for audit, but instructions embedded in them do not override system rules. [`data/fixtures/`](data/fixtures/) and [`data/evaluation/`](data/evaluation/) supply expected behavior and gold labels; they are never indexed as evidence.

Missing FedRAMP evidence, an archived TLS source, conflicting current retention positions, roadmap-only functionality, and a nonstandard SLA request are deliberate fixtures. Retrieval cannot silently promote a stale or weak source over a current authoritative one. Unsupported atomic claims cannot become an unqualified final answer. Evidence recovery is capped at two attempts; conflict reanalysis has its own one-attempt cap. Risk and authority—not model confidence alone—determine when a human must decide. A saved approval can promote only a specifically selected, finalized commitment, with reviewer and evidence provenance.

The UI and DOCX carry the same prominent warning: this is a synthetic demonstration, produces drafts for human review, and is not authorized to make legal, commercial, security-exception, roadmap, or customer-specific contractual commitments. Errors shown in the UI are sanitized; raw provider messages, credentials, and tracebacks are not displayed. Keep `.env` private and never add real customer material to this repository.

The [Git and credential hygiene review](docs/git_hygiene_v1.md) records the ignore rules, bounded secret scans, public-source publication check, and final release freeze. Ignoring a file is not a substitute for checking the staged file list before any future commit.

## Evaluation method and measured result

The [24-case frozen gold set](data/evaluation/evaluation_cases_v1.json) includes simple, cross-domain, missing-evidence, conflict, stale-source, prompt-injection, and authority-sensitive requirements. The single generalist and orchestrated-peer arm used the same synthetic corpus, retrieval contracts, model configuration, safety policy, and scoring rubric. Gold labels were excluded from generation. The headline metric is:

```text
Safe Completion Rate =
  (safely finalized cases + correctly escalated cases)
  / all requested cases
```

A finalization counts only if its evidence, citation, source, conflict, recovery, risk, and authority checks pass. Required human-review cases count only when they reach the correct checkpoint without exposing a final answer. Failures remain in the denominator.

The approved primary 24-case result, copied from the saved [final analysis](outputs/evaluation/provider_evaluation_final_step_4_g8.md), is:

| Metric | Single generalist | Orchestrated peers |
|---|---:|---:|
| Safe Completion Rate | 20/24 (83.3%) | 10/24 (41.7%) |
| Execution success | 24/24 | 20/24 |
| Evidence Recall@5 | 0.944 | 0.786 |
| Unsupported-claim rate | 1.5% | 28.6% |
| Groundedness | 98.5% | 69.8% |
| Preserved primary failures | 0 | 4 |

The [verified final metrics table](docs/evaluation_metrics_v1.md) includes the remaining primary measures, source hashes, and interpretation limits.

The single generalist is the **bounded preference for this frozen synthetic V1 evaluation**, not a universal architecture winner. The planned comparison comprised 64 architecture executions: 48 primary observations plus 16 extra observations for four repeat cases. All 19 failures across the complete run were preserved. The shared approved 128-generation-call ceiling was exhausted; 16 of 24 repeat-set observations failed at the budget boundary, so repeat variability is inconclusive. The cumulative frozen-pricing generation estimate is $0.814364, excluding retrieval-provider usage; observed per-arm cost totals also omit unobserved usage on failed executions. The [human approval record](data/evaluation/provider_evaluation_final_approval_step_4_g8.json) binds the exact reviewed analysis and its limitations.

The canonical raw runs and derived reports live under `outputs/evaluation/` locally. **`outputs/` is Git-ignored**, so a clone of the source repository will not contain those run artifacts unless they are separately shared. Do not rerun the old paid execution commands to recreate them: the approved call ceiling is exhausted. The build history and artifact hashes are in the [Build Plan](planning/BUILD_PLAN.md) and [project journal](PROJECT_JOURNAL.md).

## Observability and verification

The UI exposes ordered node events and safe routing state. A separately approved LangSmith setup captured synthetic traces with allowlisted case/route/safety metadata, token declarations, latency, and sanitized errors; raw RFP inputs and outputs are hidden. Normal offline demo use does not require LangSmith. Existing live trace commands are historical one-time operations, not routine setup steps.

To check local behavior without provider calls, with `(.venv)` active run:

```bash
python -m pytest -p no:cacheprovider tests/test_demo_clean_start.py tests/test_demo_map_docx.py -q
python -m pytest -p no:cacheprovider -q
python -m ruff check .
```

The five-case tests run the real local graph and Streamlit test session. They do not upload data or make OpenAI, Pinecone, or LangSmith requests. The full suite guards routing, peer topology, retrieval limits, evidence validation, bounded recovery, human review, commitment promotion, fault handling, evaluation math, and provider-call boundaries.

## Limitations and next improvements

This is a small, synthetic prototype. Its local checkpoint store is process-local; its offline specialist behavior and Implementation semantic scorer are deterministic substitutes, not production model judgments. It has not been tested with large or changing enterprise corpora, real customer data, concurrent reviewers, durable audit storage, or production authentication. The approved evaluation used one provider/model configuration and one 24-case primary trial; the repeat set was budget-censored.

Known quality gaps remain: `RFP-006` exhausts retrieval before the expected roadmap-authority gate; `RFP-015` surfaces the security exception but misses the second expected retention conflict; and some evidence-gap/pre-retrieval checkpoints offer more human actions than the gold safety contract permits. Both architectures had zero conflict-detection F1 in the primary comparison. The Step 5.11 QA verified all five DOCX files structurally and inspected first-page previews, but did not complete visual inspection of every page after the Word UI stopped responding. These are open limitations, not solved production behaviors.

A future version would address those gates first, then add durable checkpointing and role-based reviewer authorization, expand the corpus with properly licensed synthetic or permissioned data, test retrieval and latency at scale, run an independently budgeted evaluation, and validate a deployment security/privacy plan before any real-data use. None of those expansions is part of this V1 demo.

## Repository guide

| Location | Purpose |
|---|---|
| [`planning/`](planning/) | Locked decisions, graph/UI designs, beginner guide, and checked build plan. |
| [`src/rfp_orchestrator/`](src/rfp_orchestrator/) | Graph, specialists, retrieval, gates, UI, DOCX, evaluation, and provider adapters. |
| [`tests/`](tests/) | Offline regression and safety checks. |
| [`data/`](data/) | Synthetic trusted KB, untrusted RFP, fixtures, and frozen evaluation labels. |
| `outputs/` | Local generated artifacts, raw evaluation runs, and QA files; Git-ignored. |
| [`PROJECT_JOURNAL.md`](PROJECT_JOURNAL.md) | Chronological build decisions, errors, approvals, and verification evidence. |

The required V1 build is complete and frozen as release `v0.1.0`. See [Current Status](planning/BUILD_PLAN.md#152-current-status--next-step) for the final verification record.
