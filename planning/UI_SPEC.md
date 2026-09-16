# Streamlit UI and Live Execution Map

The UI is lightweight and demo-focused. It supports selecting a sample RFP, running the orchestrator, inspecting requirements/evidence, resolving HITL decisions, and downloading a simple DOCX response.

## Implemented shell — Step 3.1

The local entry point is root-level `app.py`, launched from the project root with:

```bash
python -m streamlit run app.py
```

It delegates to `src/rfp_orchestrator/ui.py`, applies the page configuration before any visible Streamlit call, uses a wide layout and expanded sidebar, and renders the application title plus a compact subtitle. The workflow controls, safety notice, result views, live map, HITL decision controls, exact-checkpoint resume, sanitized recovery guidance, evidence- and approval-enriched DOCX generation, and local download control are implemented through Step 3.17.

Project-local `.streamlit/config.toml` reserves `http://localhost:8502` so this UI can run at the same time as the IRS project on port 8501. It binds only to localhost and disables optional Streamlit usage telemetry.

## Implemented controls — Step 3.2

The expanded sidebar loads the real 24-item synthetic RFP from `data/sample_rfp.md`. The selector shows stable IDs and full requirement text, with a disabled text-area preview beneath it. No duplicate option list is maintained in UI code.

**Run selected requirement** invokes the existing checkpointed graph with deterministic offline retrievers and writes the full returned state plus requirement and unique thread IDs into Streamlit session state. Each checkpoint thread ID contains a random per-browser-session identifier plus the monotonic run number, preventing two browser sessions from sharing a process-local checkpoint. This makes completed and interrupted runs available to later result, map, and HITL components without displaying them prematurely. **Clear current run** removes those current-result pointers but retains the session identifier and monotonic run counter so checkpoint thread IDs are never reused.

## Implemented safety notice — Step 3.3

A persistent yellow warning appears immediately beneath the title and subtitle, before any workflow controls or response content. It states that the demonstration uses a fictitious company, synthetic RFP requirements, and synthetic evidence; outputs are drafts requiring human review and may be incomplete; and the system has no authority to make legal, commercial, security-exception, roadmap, or customer-specific contractual commitments.

The notice is part of the page shell rather than conditional run state, so it remains visible before a requirement runs, after a run completes or interrupts, and after the current run is cleared. The same statement is preserved in the README and generated DOCX files.

## Implemented result table — Step 3.4

Before a run, the main page shows a short prompt beneath **Requirement result**. After **Run selected requirement** completes or interrupts, one summary row is derived directly from the saved graph state. The stable columns are:

- Requirement: stable ID plus the complete original requirement text;
- Strategy: the current graph strategy in a readable label;
- Selected specialists: only the peers selected by orchestration, or `None`;
- Evidence state: a deterministic summary of support, validation, and recovery state;
- Risk: the graph's risk classes in readable labels, or `None detected`;
- Final status: finalized, needs human, rejected, or in progress.

Evidence state is intentionally summary-only. Recovery exhausted and recovery required take precedence, followed by failed validation, aggregate specialist support, and pending/not-evaluated states. The row never recomputes or changes graph decisions. **Clear current run** removes the table because it removes the saved result pointer.

## Implemented detail panel — Step 3.5

An expanded **Response, evidence, approval, and trace details** panel appears only when a saved result exists. It contains five clearly separated views:

- proposed specialist answers with their aggregate support status;
- atomic claims with per-claim boolean support and cited evidence IDs;
- only the evidence records actually cited by those claims, including source metadata, retrieval method, and a bounded excerpt;
- the ordered human decision history, or an explicit awaiting/no-approval message;
- the ordered execution-event trace with step number, node, status, timestamp, and sanitized detail.

The panel derives presentation rows from saved graph state and never changes strategy, evidence judgments, approvals, or trace order. Long evidence is bounded to a 240-character normalized excerpt, while complete evidence remains in graph state. The future architecture map will consume these existing events beginning at Step 3.6; the detail panel does not infer map state.

## Implemented event reducer — Step 3.6

`src/rfp_orchestrator/node_status.py` defines the stable data contract that will drive the map. `initial_node_status()` returns a fresh insertion-ordered dictionary containing all 21 `GraphNode` values, each initialized to `inactive`. `apply_node_event(...)` immutably applies one validated event, and `reduce_node_status(...)` applies one requirement's ordered event sequence using last-event-wins semantics.

The reducer accepts only the locked execution statuses `inactive`, `active`, `complete`, `recovery`, `blocked`, and `state_access`. It fails closed on malformed events, unknown architecture nodes, noncanonical current dictionaries, unknown status values, or events mixed from different requirement IDs. Because inactive nodes are initialized rather than inferred, unselected Product, Security, or Implementation peers remain explicitly gray-ready.

After each UI run, the reduced dictionary is saved separately in Streamlit session state under `node_status`; it is not written into `GraphState` and cannot influence routing or finalization. Clear removes the derived dictionary along with the current result. Step 3.6 does not render the dictionary; lightweight HTML/SVG rendering begins in Step 3.7.

## Implemented architecture renderer — Step 3.7

`src/rfp_orchestrator/architecture_map.py` defines one responsive SVG with all 21 canonical nodes and every locked `PEER_TOPOLOGY_EDGES` connection. The diagram includes the analyzer, orchestrator, three peer specialists, merge and validation chain, recovery controls, narrow commitment controls, conflict and authority gates, HITL checkpoint/interrupt/rework nodes, finalization, and commitment promotion. The three specialists remain peers: the rendered edge set contains no specialist-to-specialist edge.

Each node contains its readable label and current status as text, so the first-pass diagram does not rely on color. The SVG has a title, description, per-node accessible label, responsive view box, theme-aware neutral system color, and thin directional connectors. Before a run it receives a fresh all-inactive dictionary. After a run it receives the saved Step 3.6 dictionary.

The map is hosted in Streamlit's isolated `st.iframe` HTML component because the installed `st.html` sanitizer removes inline SVG elements from the live browser DOM. The component remains local, contains no JavaScript or external resource, and is not a separate frontend. Step 3.7 keeps all nodes neutral; the locked gray/blue/green/orange/red/purple treatment remains Step 3.8, and incremental event rerendering remains Step 3.9.

## Implemented status treatment — Step 3.8

The renderer now maps the six validated execution states to the locked semantic colors: inactive is gray, active/executing is blue, complete is green, recovery is orange, blocked or awaiting human review is red, and state access is purple. The mapping is defined once in `STATUS_VISUALS` and drives both node styling and the visible legend, preventing the legend and graph from drifting apart.

Each theme-aware status color is used for the node border, a low-opacity node fill, and the status line. The readable node name remains the normal canvas text color. Every node continues to expose its status as visible text, a `data-status` attribute, and an accessible label, so color is a redundant signal rather than the only signal. The selected Product path in RFP-001 renders green after completion while unselected Security and Implementation peers remain gray.

Step 3.8 changes presentation only. It does not alter the event reducer, graph state, routing, evidence, authority checks, or finalization. The map still renders a completed snapshot; event-by-event rerendering remains Step 3.9.

## Implemented live event map — Step 3.9

The UI now runs the graph with the combined LangGraph `custom` and `values` stream modes. Each validated `custom` execution event is applied immediately to a copied UI-only node-status dictionary and replaces the existing map frame in one stable Streamlit placeholder. The latest `values` chunk becomes the saved final graph state. The streamed status dictionary is saved separately for the final map snapshot and never enters `GraphState`.

The map shell is created before the Run handler begins, allowing events to appear in the main page while the sidebar action is still executing. Each live frame identifies the current node in a polite status region, marks the map as busy, and briefly holds the frame for demo legibility. After the stream ends, the same placeholder displays a clean completed snapshot. Event callbacks receive copies, so presentation code cannot mutate the reducer's status or persisted graph events.

Node fills, borders, and status text use modest 180-millisecond CSS transitions. A `prefers-reduced-motion: reduce` rule removes the transitions while preserving the complete event sequence and written status updates. The component uses no polling, external resource, or second orchestration engine.

### Step 3.9 refinement — event-derived information-flow arrows

The live map applies the same semantic states to directional arrows. Unused routes stay thin and faint gray. The incoming route to the executing node becomes bright blue, then remains as a softer green traversed route after completion. Recovery, blocked/HITL, and state-access routes use orange, red, and purple respectively. Arrowheads inherit the route state, and the legend explicitly applies to both nodes and arrows.

The UI derives arrow state from the ordered execution-event sequence rather than assuming that an edge was traversed whenever both endpoint nodes completed. For ordinary nodes, the most recently completed valid predecessor supplies the incoming route. Merge is the deliberate exception: every selected specialist completed since the preceding Merge completion receives a traversed fan-in route. This preserves cross-domain convergence while keeping unused peers, alternate branches, and possible loop-back routes visually subdued. The edge dictionary remains presentation-only and never enters `GraphState`.

## Unselected specialist visibility — Step 3.10

Every streamed run starts from a fresh canonical node-status dictionary in which Product, Security, and Implementation are gray/inactive. As values chunks reveal graph-selected domains, the UI retains the cumulative specialist selection for that run. Before each event frame is rendered, a fail-closed validator confirms that every specialist outside that cumulative selection is still exactly `inactive`. This allows a later recovery or reanalysis specialist to remain visibly invoked while preventing unused peers from appearing active, complete, blocked, or in recovery.

The validator rejects contradictory or malformed telemetry rather than silently recoloring it. A single-domain Product path therefore keeps Security and Implementation gray in every frame; a Product-plus-Security path keeps Implementation gray. A new run receives a new dictionary, so specialist colors cannot leak from the preceding run. Each inactive peer also retains visible `Inactive` text and an accessible label, making gray a redundant visual cue rather than the only indicator.

## Bounded attempt counters

The Retrieval Recovery Attempt node displays `Attempts: n/2`, and the Conflict Reanalysis Attempt node displays `Attempts: n/1`. Both counters start at zero for a new run and increment on the node's `recovery` start event, not on its matching completion event. Their accessible node labels state the same count in words. The values are reduced from copied execution events, validated against the locked attempt limits, stored only in UI session state, and never written into `GraphState`.

## Visualization failure isolation — Step 3.11

Architecture rendering is an optional presentation consumer of graph telemetry. Frame generation and iframe replacement run behind a deliberate exception boundary. If either fails, the map placeholder shows a fixed sanitized warning stating that the map is unavailable and the requirement result is unaffected. Internal error details are not rendered.

The stream consumer disables further visualization callbacks after the first escaped callback failure but continues consuming LangGraph custom and values chunks. The final authoritative graph state, thread ID, node status, edge status, and attempt counts are saved before final visualization handling. A `visualization_failed` boolean communicates presentation health without entering graph state or affecting routing, evidence, HITL, consistency, or finalization.

## HITL decision controls — Step 3.12

The **Human review** section appears only when the saved graph state is paused at a validated human-review checkpoint. It displays the checkpoint reason and rationale plus all five locked actions: Approve, Edit and approve, Reject, Add guidance, and Request retry. Unavailable actions remain visible with an explanation; in particular, Request retry is disabled after the two-retry evidence budget is exhausted.

Choosing an action reveals only its relevant inputs. Every decision requires reviewer identity. Edit and approve requires replacement answer text. Approve and Edit and approve may select only commitment proposals owned by the saved requirement. Add guidance requires guidance and offers only specialists already relevant to the checkpoint. Request retry offers the same scoped specialists and optional retry guidance. The UI generates the audit timestamp locally.

Submitting the form validates and stores a strict `HumanReviewDecision` draft in Streamlit session state. It does not send a LangGraph resume command, alter the saved graph state, record an approval, promote a commitment, or finalize a response. The UI explicitly states that the graph remains paused. Starting a new run or clearing the current run clears all review-control and draft keys.

## Exact-checkpoint resume — Step 3.13

After a valid draft exists, **Apply decision and resume workflow** performs a second strict validation and resolves the checkpoint through the saved browser-session-isolated LangGraph thread ID. Resume is allowed only when that checkpoint still points to `human_review_interrupt` and its requirement, current review request, and prior human-decision history match the saved UI result. Missing, completed, or stale checkpoints fail closed, retain the draft for correction, and do not execute graph work.

The five decisions retain their governed meanings. Approve resumes through finalization and promotes only selected commitments. Edit and approve uses the exact reviewed replacement response. Reject terminates without a final answer or commitment promotion. Add guidance executes only selected in-scope specialists before returning to validation and, when required, another human checkpoint. Request retry uses the bounded evidence-recovery route and remains unavailable after its two-attempt budget is exhausted.

The interrupt streams a red `blocked` event immediately before pausing and a `complete` event after a valid resume. Subsequent node and edge events use the same presentation-only reducers as the initial run, including recovery and reanalysis counters, so the map shows the actual resume route. The updated result, decision history, telemetry, and original thread ID replace the prior saved run atomically at the UI boundary. The applied draft is then cleared to prevent accidental replay. A visualization callback failure remains non-authoritative and cannot stop the resumed graph.

## Sanitized operational feedback — Step 3.14

One fixed catalog covers sample loading, requirement execution, map rendering, human-review controls, missing decision drafts, stale checkpoints, unexpected resume failures, result-summary display, and detail-panel display. Each entry contains a plain-language title, the effect on saved state, a specific next action, and a stable `RFP-UI-00x` reference. The formatter accepts only the category; it never accepts or interpolates an exception, provider payload, credential, local path, or traceback.

UI boundaries fail independently. A failed new run stores no partial result, retains any previous saved result, restores its map snapshot, and advances the unique run number so a partially created checkpoint thread is not reused. A stale checkpoint tells the reviewer to clear the run and create a new checkpoint. An unexpected resume failure retains both checkpoint and draft and allows one retry before recommending a clean rerun. Result, detail, review-control, and map display failures cannot mutate the saved graph result.

Expected decision-form validation remains specific because those messages are fixed application copy rather than raw exceptions. Each validation error now tells the reviewer to correct the visible fields and save again. The safety notice remains separate and persistent; operational feedback does not weaken authority boundaries or imply that an incomplete run succeeded.

## Basic DOCX generation — Step 3.15

One saved requirement state can be serialized to a reviewable DOCX without recomputing graph decisions. A finalized export requires and preserves the exact guarded final answer. Awaiting-human, rejected, pending, and in-progress states receive explicit status language and cannot carry a final answer. Missing, unknown, or contradictory fields fail closed.

The `rfi_response` business preset uses US Letter portrait pages, one-inch margins, explicit Calibri styles, a restrained synthetic Northstar header/footer, clear requirement and response headings, and a shaded safety-notice paragraph. The notice reuses the exact centralized Streamlit safety copy. Step 3.15 intentionally omits citations, support status, approval notes, and the Streamlit download control so those concerns remain isolated in Steps 3.16–3.17.

## Evidence and approval DOCX details — Step 3.16

The DOCX now presents two support layers without conflating them. Every atomic claim displays its binary Supported or Unsupported value plus its citation IDs. Each specialist displays the aggregate Supported, Partial, or Unsupported status calculated from those claim booleans, together with a plain-language explanation of the aggregation rule.

The cited-evidence section contains only records referenced by a claim. Each record preserves the evidence ID, source title, domain, version, effective date, source status, retrieval method, and a bounded excerpt. A citation that does not resolve to saved evidence, conflicting duplicate evidence IDs, repeated specialists or claim IDs, or an aggregate status that disagrees with its claims causes export to fail closed.

Approval notes preserve ordered human-decision history with decision, reviewer, timestamp, review reason, edited answer, and guidance. Autonomous paths explicitly state that no human approval was required or recorded; interrupted paths with no decision explicitly state that review is still pending. Human-approved audit details begin together on a new page so the decision block is not split awkwardly. The Streamlit download button remains Step 3.17.

## DOCX download — Step 3.17

The page ends with a **Download response** section. Before a requirement runs, it explains that a saved result is required and exposes no download. After any valid saved graph result exists—including a truthful paused or rejected status—the UI prepares the existing guarded DOCX bytes in memory and exposes one primary **Download DOCX response** button.

The filename is deterministic and safe for the local filesystem: `northstar-rfp-response-<sanitized-requirement-id>.docx`. The response uses the official DOCX MIME type. Building or downloading the document does not rerun the graph, mutate the saved state, resume a checkpoint, initialize a provider, or call an external service.

Document preparation has its own sanitized failure boundary, `RFP-UI-010`. Malformed saved state produces no download button, does not expose an incomplete document or internal exception details, and leaves the saved graph and human-review state unchanged. The downloaded-equivalent RFP-001 file passed archive integrity, content, render, and browser-control checks.

The representative RFP-001 output renders as one clean page. Required PNG inspection confirmed that the final version has no clipping, overlap, missing glyphs, broken spacing, or inherited title rule.

## Live architecture execution map

The Streamlit UI consumes LangGraph node execution events and rerenders a simple HTML/SVG diagram. It does not require React, D3, or a separate frontend.

```python
node_status = {
    "requirement_analyzer": "complete",
    "strategy_orchestrator": "complete",
    "product_specialist": "active",
    "security_specialist": "inactive",
    "implementation_specialist": "inactive",
}
```

The example is abbreviated for readability; the runtime dictionary always contains all 21 canonical architecture nodes in `GraphNode` enum order.

Status colors:

- gray: not invoked/inactive
- blue: executing
- green: completed
- orange: retry/recovery
- red: blocked/HITL
- purple: state read/write

Events use a small stable contract: `node`, `status`, `timestamp`, `requirement_id`, and optional `detail`. The map shows actual fan-out/fan-in and leaves specialists that were not selected gray. Animation is achieved through incremental event-driven rerenders and modest CSS transitions. The map is explanatory telemetry, not a second orchestration engine.

Step 2.10 implements the event source used by this UI. Every executed material node streams an `active` event before work and a `complete` event afterward, while successful events are also appended to graph state for audit. A failed node streams `blocked` with only the exception type; raw exception messages are not copied into the UI event. Unselected specialists emit no events and therefore remain gray. The Streamlit layer consumes LangGraph `custom` stream chunks rather than polling or attempting to infer execution from final state.

Acceptance criteria:

- a single-domain run visibly activates only one specialist;
- a cross-domain run visibly activates peer specialists in parallel;
- a recovery run turns the recovery node orange;
- an interrupted run turns HITL red and resumes after a human decision;
- graph execution remains correct if the visual component fails.
