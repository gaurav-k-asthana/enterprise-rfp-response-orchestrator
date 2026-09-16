# LangGraph State Model and Control Flow

## Locked topology

The graph has three independent peer specialists: Product, Security/Compliance, and Implementation. The orchestrator may fan out to one, two, or all three and then fan in at merge. There are no specialist-to-specialist edges.

```text
Requirement Analyzer -> Strategy Orchestrator
                              |  |  |
                              v  v  v
                         Product Security Implementation
                              \  |  /
                               Merge
                                 |
                          Evidence Check
                                 |
                    Consistency / Commitment Check
                                 |
                         Risk / Authority Gate
                           |             |
                       Finalize        HITL
```

## Requirement Analyzer decomposition contract

Step 2.1 implements the deterministic decomposition layer that runs before domain, ambiguity, injection, or risk classification. The analyzer always retains `Requirement.original_text` unchanged and writes normalized atomic statements only to `Requirement.atomic_requirements`.

The V1 offline rules split only high-confidence structures:

- independent clauses that repeat an approved material action such as `describe ... and identify ...`;
- explicit capability, certification, encryption, residency, or commercial pairs whose shared context can be preserved;
- clear comma lists under one action, including comparison dimensions and implementation resources;
- shared qualifiers such as `required during implementation`, which are copied to every affected atomic item.

Ambiguous prose remains one item rather than being split speculatively. Output is stable, case-insensitively de-duplicated, and capped at 12 atomic items per source requirement. Blank input and excessive expansion fail closed. Step 2.1 does not assign domains, detect prompt injection, infer risk, retrieve evidence, or call a model; those responsibilities remain separate.

## Prompt-injection detection contract

Step 2.2 inspects only the unmodified `Requirement.original_text`. It treats every match as data and never executes, removes, rewrites, or obeys the matched text. The output includes:

- `prompt_injection_detected`: the simple boolean used by later graph routing;
- `prompt_injection_signals`: structured evidence containing signal type, exact matched text, and start/end character offsets into `original_text`.

V1 detects high-confidence role markers, policy/instruction overrides, forced yes/no responses, role reassignment, and requests to disclose system prompts or secrets. The requirement schema enforces that the boolean equals the presence of signals and that every stored span exactly matches the original source. Tests require RFP-024 to be the only flagged item in the 24-requirement sample while legitimate questions about policies, security controls, API-key rotation, and user-interface responses remain unflagged.

Detection alone does not choose a domain, assign a risk class, select a strategy, or finalize an answer. Those decisions remain explicit later graph steps.

## Requirement classification contract

Step 2.3 deterministically adds four structured views of the analyzed requirement while preserving the Step 2.1 decomposition and Step 2.2 injection evidence:

- `assigned_domains`: zero or more peer-specialist domains in the stable order Product, Security/Compliance, Implementation;
- `attributes`: request form and handling features such as information, confirmation, commitment, comparison, deliverable, absolute language, time bound, or untrusted instruction;
- `ambiguity_signals`: typed signals with an explanation and an exact source span in `original_text`;
- `initial_risk_flags`: text-only risk candidates visible before evidence retrieval.

Domain assignment uses explicit V1 indicators instead of broad words such as `data` or `integration`, which would over-route normal Implementation questions. A requirement may select multiple peer specialists, but this classification creates no specialist-to-specialist edge and does not yet choose an execution strategy.

Ambiguity signals cover relative timeframes, undefined deadlines, unbounded scope, and absolute language. The requirement schema verifies that every matched span is an exact substring of the unchanged source text.

Initial risk flags are deliberately distinct from the final risk and authority decision in Step 2.20. Step 2.3 may flag a visible SLA/service-credit request, roadmap commitment, pricing or legal term, security exception, or data-residency ambiguity. It does not invent evidence-dependent findings such as unsupported claims, conflicting evidence, specialist disagreement, or retry exhaustion before retrieval and graph execution have occurred.

The combined offline entry point runs decomposition, injection assessment, and classification in order without mutating the caller's `Requirement`. Step 2.3 performs no retrieval, model, provider, strategy, or LangGraph call.

## Core schemas

```python
from typing import Literal, TypedDict

SupportStatus = Literal["SUPPORTED", "PARTIAL", "UNSUPPORTED"]

class Claim(TypedDict):
    claim_id: str
    text: str
    evidence_ids: list[str]
    supported: bool

class SpecialistOutput(TypedDict):
    specialist: Literal["product", "security", "implementation"]
    claims: list[Claim]
    proposed_answer: str
    support_status: SupportStatus
```

`Claim.supported` is a boolean at the atomic-claim level: each indivisible material claim is either supported by valid evidence or it is not. `SpecialistOutput.support_status` is the aggregate result for the specialist response.

Aggregation is deterministic:

- `SUPPORTED`: the output contains at least one material claim and every material claim has `supported=True`.
- `PARTIAL`: the output contains material claims and at least one is supported and at least one is unsupported.
- `UNSUPPORTED`: there are no material claims, or no material claim has `supported=True`.

```python
def aggregate_support(claims: list[Claim]) -> SupportStatus:
    if not claims:
        return "UNSUPPORTED"
    flags = [claim["supported"] for claim in claims]
    if all(flags):
        return "SUPPORTED"
    if any(flags):
        return "PARTIAL"
    return "UNSUPPORTED"
```

Claims must be atomic for this rule to remain meaningful. In short: claims are binary; responses can be partial.

## State and reducers

State is business state, not merely chat history. It includes the RFP case, current requirement, chosen strategy, specialist outputs, retrieved evidence, retry counters, conflicts, risk classes, approvals, run events, and the narrow commitment ledger.

Parallel specialist results are merged with an append-only reducer keyed by specialist. UI execution events are append-only and carry `node`, `status`, `timestamp`, and optional `detail`. Checkpoints are written before interrupts and after material state transitions.

Step 2.10 wraps every currently executable material node—Requirement Analyzer, Strategy Orchestrator, each selected peer specialist, and Merge—with the same instrumentation contract. The wrapper:

1. creates and immediately streams an `active` event before calling the node;
2. streams `complete` after a successful return;
3. appends both successful events to `execution_events` through the existing reducer;
4. streams `blocked` before re-raising a failure, using only the exception class in `detail` so the UI event does not expose raw internal error text.

LangGraph `custom` streaming makes the start event available before node completion for the future live map. Persisted events remain an audit trail; streaming telemetry and business-state execution use the same event object but the visualization cannot alter routing. Parallel specialists each emit their own active/complete pair, Merge starts only after all selected branches complete, terminal initial strategies emit only Analyzer and Orchestrator events, and inactive specialists emit nothing.

## Conditional control flow

The orchestrator selects the minimum-cost safe path:

- `SINGLE_SPECIALIST`
- `PARALLEL_SPECIALISTS`
- `RETRIEVAL_RECOVERY`
- `TARGETED_CONFLICT_RESOLUTION`
- `IMMEDIATE_HITL`
- `FINALIZE`

Step 2.4 defines these as validated `StrategyDecision` outputs. Every output contains a nonblank rationale and only the context valid for its route:

- `SINGLE_SPECIALIST` selects exactly one Product, Security/Compliance, or Implementation peer;
- `PARALLEL_SPECIALISTS` selects two or three unique peers;
- `RETRIEVAL_RECOVERY` selects at least one target peer and requires recorded recovery context;
- `TARGETED_CONFLICT_RESOLUTION` selects at least one target peer and requires one or more conflict IDs;
- `IMMEDIATE_HITL` selects no specialist because it routes directly to human review;
- `FINALIZE` selects no specialist and carries no recovery or conflict work.

Recovery context is invalid on every non-recovery route, and conflict IDs are invalid outside targeted conflict resolution. Duplicate specialists and conflict IDs fail validation. A helper converts a validated decision into explicit graph-state fields, but Step 2.4 contains no decision policy: the minimum-cost safe-path selection is implemented separately in Step 2.5.

Step 2.5 applies the deterministic selection policy in this safety-first order:

1. Prompt-injection signals route to immediate human review even if ordinary domain indicators are also present.
2. Pricing/discount or warranty/indemnity requests route immediately to human review unless the context records prior human approval; these are organizational-authority decisions rather than research questions.
3. Identified conflicts route only to their affected peer specialists for targeted resolution.
4. Recorded retrieval failures route only to their failed peer specialists while the retry count is below two; an exhausted two-retry budget stops automation and routes to human review.
5. `FINALIZE` is available only when a separate downstream guard explicitly marks the response ready and no recovery or conflict work remains.
6. Otherwise, one classified domain selects one specialist, two or three domains select parallel peers, and no safe domain fails closed to immediate human review.

This ordering defines “minimum cost” as the least expensive route that does not bypass a safety, authority, conflict, or recovery requirement. Initial SLA, roadmap, security-exception, and data-residency flags still retrieve relevant evidence before the later Step 2.20 risk/authority gate; the initial orchestrator does not mistake those flags for completed evidence judgments.

Retrieval and parse failures may retry, with a hard maximum of two retrieval retries. Persistent disagreement, exhausted retries, unsupported categorical commitments, or authority risk route to HITL. Human decisions are `APPROVE`, `EDIT_AND_APPROVE`, `REJECT`, `ADD_GUIDANCE`, or `REQUEST_RETRY`.

## Peer specialist node contract

Step 2.6 implements three independent offline specialist functions. Each accepts one analyzed `Requirement` plus only its own domain-locked `SpecialistRetriever`; none can invoke another specialist.

- Product uses hybrid Top-5 retrieval and preserves GA, tier, hosting, roadmap, SLA, integration, and deployment boundaries. Roadmap is never rewritten as current availability, and unsupported deployment models never receive a categorical yes.
- Security/Compliance uses hybrid Top-5 retrieval and requires direct evidence for named controls, certifications, assurance, encryption, residency, access, and retention claims. Adjacent certifications do not establish FedRAMP or another unlisted authorization. Equal-authority retention positions remain separately visible.
- Implementation uses the deterministic semantic substitute for the future dense Top-5 provider path. Timeline language retains prerequisite, dependency, scope-change, approval, and non-guarantee qualifications.

The V1 offline responses are conservative, rule-based, and evidence-extractive. A claim is marked supported only when its expected source passage is present in the evidence returned for that invocation. Missing evidence produces an explicit unsupported result rather than model-memory completion. Every returned citation belongs to the same node's returned evidence, all evidence remains within the specialist domain, and the result never exceeds Top 5.

The specialist boundary rejects unselected domains, another peer's retriever, and prompt-injection content even if that content also contains a valid domain keyword. This is a local construction guard; the independent post-merge citation and authority validators remain Steps 2.11–2.13.

## Enforced peer topology

Step 2.7 makes the peer-only structure executable and inspectable in `graph_topology.py`. The locked core edges are:

```text
requirement_analyzer -> strategy_orchestrator

strategy_orchestrator -> product_specialist        -> merge
strategy_orchestrator -> security_specialist       -> merge
strategy_orchestrator -> implementation_specialist -> merge
```

The structural validator requires all three orchestrator-to-peer and peer-to-merge edges. It rejects every specialist-to-specialist direction, any specialist successor other than deterministic merge, any non-orchestrator source of initial specialist work, and a missing peer edge.

The compiled LangGraph skeleton contains the analyzer, orchestrator, three peers, and merge, but its temporary conditional router stops before specialist execution. This is deliberate: Step 2.7 proves the allowed graph shape without running every peer. Step 2.8 replaces that stop with selected-specialist fan-out, so runtime activation remains governed by the orchestrator rather than static edges.

## Selected-specialist fan-out contract

Step 2.8 replaces the structural stop with `route_selected_specialists`. The router reconstructs and revalidates the `StrategyDecision` from graph state before returning one node name for a single route, a list of two or three node names for a parallel LangGraph superstep, or `END` for a terminal strategy. Corrupted strategy cardinality therefore fails before specialist execution.

The executable offline path now performs:

```text
START -> Requirement Analyzer -> Strategy Orchestrator
                                      |
                                      +-> only selected peer node(s)
                                                    |
                                              merge barrier -> END
```

Each specialist branch writes two reducer-backed dictionaries keyed by `product`, `security`, or `implementation`:

- `specialist_outputs`: the structured `SpecialistOutput` for that peer;
- `specialist_evidence`: the exact evidence list returned by that peer.

Keyed state prevents one parallel branch from overwriting another and keeps citations associated with the evidence from the same invocation. Unselected specialists are not called. Immediate-HITL and other terminal strategies execute no specialist. The merge node in Step 2.8 is only a synchronization barrier; stable specialist ordering and flattened merged state belong to Step 2.9.

## Deterministic specialist merge contract

Step 2.9 replaces the synchronization-only merge body with `merge_specialist_state`. It first requires the `specialist_outputs` and `specialist_evidence` key sets to match `selected_specialists` exactly. Missing branches, unexpected branches, duplicate or unknown selections, an output declaring the wrong specialist, cross-domain evidence, and citations outside the originating branch all fail closed.

Valid branch state is emitted in the canonical order:

```text
Product -> Security/Compliance -> Implementation
```

The original keyed dictionaries remain intact for provenance. Merge additionally writes:

- `merged_specialist_outputs`: a stable ordered list of the selected structured outputs;
- `merge_order`: the ordered specialist keys that were merged;
- `evidence`: a flattened evidence list grouped by canonical specialist order while preserving the original ranking within each specialist branch.

Canonical order is independent of `selected_specialists` input order and parallel branch completion order. A single branch is merged the same way, while terminal strategies bypass merge and retain empty merged views.

## Citation-membership gate

Step 2.11 adds an instrumented `citation_validation` node immediately after Merge and before any independent semantic support judgment. It does not decide whether a passage meaningfully supports a claim. Instead, it proves the structural prerequisites for that later decision:

- every provisionally supported claim has at least one citation ID;
- each citation ID exists in evidence returned during the current specialist retrieval;
- each citation belongs to the same specialist branch as the claim;
- each cited chunk survived into the deterministic merged evidence view;
- a claim does not repeat a citation ID;
- merged evidence does not contain duplicate chunk IDs.

An unsupported claim may legitimately have no citation; FedRAMP High is the seeded example. The validator records structured issues without changing `Claim.supported`, aggregate support status, or final-answer state. Multiple affected claims produce multiple claim-level diagnostics. State receives `citation_valid` plus the complete `citation_validation` result, and the node emits the normal active/complete execution events.

This gate rechecks citation membership independently even though specialist construction and Merge already enforce local provenance. Defense in depth ensures that later model-generated or resumed state cannot reach semantic support evaluation with invented, cross-branch, dropped, or duplicated citations.

## Source lifecycle and authority-metadata gate

Step 2.12 adds an instrumented `source_validation` node immediately after `citation_validation`. The two gates answer different questions: citation validation proves that a citation belongs to the evidence retrieved for this run, while source validation proves that the cited evidence is eligible to support a current claim.

For every merged evidence item, source validation requires a stable nonblank chunk ID and document ID, a nonblank version, a valid ISO effective date that is not in the future, an integer authority rank from 1 through 5, and a recognized `current` or `archived` lifecycle status. State receives `source_metadata_valid` and the complete typed `source_validation` result, including current and archived evidence IDs, eligible cited evidence IDs, authority by evidence ID, the weakest eligible cited authority rank, and all detected issues.

Archived evidence may remain in retrieval and merged state for diagnosis, stale-source testing, or explaining a historical conflict. Its presence alone is valid. Citing it as support for a current claim produces `ARCHIVED_CITATION`, and only fully valid current evidence is added to `eligible_cited_evidence_ids`. The node also fails closed when the upstream citation gate did not pass or a cited item is absent from merged evidence.

Source authority rank is document-governance metadata. It must not be confused with organizational approval authority: even perfect rank-5 evidence cannot authorize pricing, legal terms, an SLA exception, a roadmap promise, or a security exception. Those risk and human-authority decisions remain the separate Step 2.20 gate. Source validation does not alter claim booleans, aggregate support status, or final-answer state.

## Atomic-claim support gate

Step 2.13 adds an instrumented `claim_support_validation` node immediately after source validation. Specialist claims are provisional inputs to this node, not trusted conclusions. Each claim is independently adjudicated against the cited evidence IDs that Step 2.12 marked eligible current support.

The offline V1 adjudicator is deterministic and intentionally inspectable while paid generation remains disabled. It normalizes a small documented set of equivalent terms, requires at least 70% coverage of material claim terms in cited evidence, and requires every numeric anchor to occur with the supporting claim terms in the same evidence statement. This is a conservative local support check for the synthetic corpus, not a claim of production-grade natural-language entailment. A later model-backed implementation may replace the semantic scorer while retaining the same typed contract, gates, fixtures, and deterministic aggregation.

The node also requires nonblank stable claim IDs and text, rejects duplicates that could inflate aggregate support, distinguishes invalid upstream gates from an honest unsupported claim, and reports disagreements with provisional Boolean or aggregate values. A cited but ineligible passage cannot support a claim. A claim with no citation is independently `supported=False` without becoming a validation error when the specialist already reported it honestly.

The canonical `aggregate_support` function is reused after adjudication: at least one claim and all true is `SUPPORTED`; a mix of true and false is `PARTIAL`; no claims or no true claims is `UNSUPPORTED`. The node writes corrected support fields into the specialist outputs used downstream, plus `claim_support_valid` and the full `claim_support_validation` result. It preserves proposed-answer text and cannot finalize the requirement.

## Evidence-failure context and query reformulation

Step 2.14 adds an instrumented `recovery_planning` node after claim support. This node plans recovery but does not execute it. It classifies evidence failure as `EMPTY_RETRIEVAL`, `MISSING_DIRECT_EVIDENCE`, `WEAK_EVIDENCE`, `INELIGIBLE_EVIDENCE`, `TOOL_EXCEPTION`, or `INVALID_STRUCTURED_OUTPUT` so later routing does not treat every failure as the same problem.

Every typed failure context records the affected peer specialist, claim IDs and text, relevant evidence IDs, current retry count, recoverability, and a stable reason. Tool exceptions store only their class name; the original exception message is excluded from state and telemetry. Invalid structured output is observable but is not sent to query reformulation because changing search terms cannot repair a malformed response object.

For every specialist with at least one recoverable evidence failure, the node creates exactly one deterministic query. It retains the original material requirement, adds the failed atomic claim, adds domain-specific search vocabulary, and adds terms appropriate to the failure type. A query is limited to one specialist, differs from the original, is capped at 800 characters, and cannot be created from prompt-injection state or nonrecoverable context.

State receives `recovery_needed`, `evidence_failure_contexts`, `recovery_specialists`, `reformulated_queries`, and a concise `recovery_context`. A fully supported path writes empty recovery state. The missing FedRAMP fixture writes a Security-only `MISSING_DIRECT_EVIDENCE` plan. Step 2.14 never changes `retry_count`, reruns a specialist, changes graph strategy, or finalizes; Step 2.15 owns the conditional recovery edge and hard two-retry ceiling.

## Bounded recovery execution

Step 2.15 closes the conditional loop. When recovery is needed and `retry_count < 2`, `recovery_planning` returns control to the same Strategy Orchestrator. The existing minimum-safe-path policy emits `RETRIEVAL_RECOVERY`, selecting only the affected peer specialists and carrying the recorded failure summary. A separate `recovery_attempt` node then validates the strategy and saved queries, increments the counter once, snapshots the attempt, and fans out only those peers.

Specialists accept a query override only on a recovery strategy; the exact `reformulated_query` saved by Step 2.14 is passed to the domain-locked retriever. Results return through the normal deterministic Merge, citation, source, claim-support, and recovery-planning sequence. No shortcut bypasses an evidence gate.

`initial_specialists` preserves the peers that participated in the original response while `selected_specialists` may temporarily contain only the current retry targets. Merge uses the initial participant set so successful non-retried peer results remain present. Parallel recovery increments the counter once for the round, not once per peer.

The counter is guarded in three places: graph state starts at zero; `RecoveryAttempt.attempt_number` permits only 1 or 2; and `recovery_attempt_node` refuses any attempt unless the existing counter is an integer from 0 through 1. When a recoverable failure remains at count 2, planning sets `recovery_exhausted`, selects `IMMEDIATE_HITL`, and ends automation without finalizing. The FedRAMP fixture therefore has three total Security calls—initial plus two retries—and never a fourth.

Recovery attempts append the exact attempt number, peers, and queries to `recovery_attempts`. Their execution event starts with status `recovery` and ends with `complete`, allowing the later UI map to render orange from actual graph telemetry. Retry routing adds no specialist-to-specialist edge; peers receive retry work from the orchestration-controlled recovery-attempt node and still fan in through Merge.

## Commitment and consistency controls

The commitment ledger remains intentionally narrow. V1 normalizes only selected material commitments such as data residency, retention period, uptime SLA, deployment model, supported integration, product availability, and roadmap commitment. The consistency check compares a proposed normalized value with prior accepted values and routes unresolved contradictions to targeted reanalysis or HITL.

Step 2.16 separates proposed and authoritative memory. After claim support succeeds and no evidence recovery remains active, `commitment_ledger` deterministically maps eligible supported claims into `ProposedCommitment` records. Each proposal carries a stable ID, one of the seven locked types, a canonical value, its source requirement and atomic claim, the originating peer specialist, and cited evidence IDs. Unsupported and ordinary non-commitment claims cannot silently become proposals.

Proposals are fixed at `approved=False` and `authoritative=False` and are stored in `proposed_commitments`. The node never writes `commitments`, which remains the authoritative collection. Prompt-injection state, invalid support adjudication, active recovery, and exhausted recovery cannot reach extraction. Step 2.17 adds the separate approved/finalized promotion gate; Steps 2.18–2.19 then compare accepted values and handle conflicts.

Step 2.17 adds `commitment_promotion` downstream of draft extraction. Promotion requires an exact proposal ID in `approved_proposal_ids`, an `APPROVE` or `EDIT_AND_APPROVE` decision whose requirement ID matches the current requirement, and `final_status=FINALIZED`. Each condition is independently necessary. The result reports `NO_SELECTION`, `AWAITING_APPROVAL`, `AWAITING_FINALIZATION`, `BLOCKED`, or `PROMOTED`; only `PROMOTED` may update `commitments`.

An authoritative record is a stricter type than a proposal. It is fixed at `approved=True` and `FINALIZED`, retains normalized value plus requirement/claim/specialist/evidence provenance, and adds approving decision, reviewer, and timestamp. Existing authoritative memory is revalidated before promotion. Exact repeat promotion is idempotent; unknown selections, cross-requirement approval, duplicates, malformed state, unapproved existing records, or a conflicting record under the same proposal ID fail closed. Human interrupt/resume behavior will populate these fields in Steps 2.21–2.22; Step 2.23 remains the final-answer guard.

Step 2.18 inserts `commitment_consistency` between extraction and promotion. It classifies each proposal as `NEW`, `CONSISTENT`, or `CONFLICT` against prior approved authoritative values and separately detects disagreement among current proposals. Comparison is keyed by material subject, not broad type: SAML and SCIM are distinct integration keys, while the 30-day standard and 90-day recovery-window statements share the post-termination-retention key.

Conflict records distinguish `PRIOR_AUTHORITATIVE` from `CURRENT_PROPOSALS` and retain stable IDs plus proposed and prior provenance. Exact prior values are consistent; no prior subject is new; any differing prior value is conflicting. Both proposal and authoritative collections are fully revalidated, canonical normalized form is required, and comparison mutates neither collection. Step 2.18 records results only. Step 2.19 consumes them for targeted reanalysis and HITL routing.

Step 2.19 adds `conflict_resolution` after consistency. No conflict continues toward the authority and promotion gates. A first conflict produces `REANALYSIS_REQUIRED`, resolves proposal IDs to affected peer specialists, and creates one deterministic domain query containing the original requirement, stable conflict IDs, and exact proposed/prior normalized values. The Strategy Orchestrator emits `TARGETED_CONFLICT_RESOLUTION`, then `conflict_reanalysis_attempt` snapshots the query and fans out only those peers.

Conflict reanalysis has its own counter and a hard maximum of one round; it does not consume the two evidence-retrieval retries. Results still pass through Merge, citation validation, source validation, atomic claim support, evidence recovery planning, commitment extraction, and consistency. Initial peer participation remains preserved so a targeted rerun cannot erase a successful sibling result.

If the second consistency result is clear, routing continues. If any conflict remains, `conflict_resolution` preserves the conflict IDs and values, sets `IMMEDIATE_HITL` and `NEEDS_HUMAN`, clears active work, and ends with no final answer or promotion. This is the safe HITL boundary state; checkpoint interruption and the five human resume decisions remain Steps 2.21–2.22.

Step 2.20 inserts `risk_authority` after successful evidence and conflict checks and before commitment promotion. The node deliberately answers a different question from source validation: evidence checks establish whether the draft is supported, while this gate decides whether the system has organizational permission to make the requested promise. It records an ordered `RiskAuthorityAssessment`, the detected risk classes, the required authority owners, `authority_required`, and `authority_gate_passed`.

Mandatory approval categories are deterministic: unsupported categorical yes; roadmap dates or delivery promises; pricing or discounts; new SLA or service-credit terms; warranty or indemnity terms; security exceptions; material data-residency ambiguity; conflicting evidence; peer-specialist disagreement; and exhausted recovery. Product roadmap decisions map to a Product owner, security/residency exceptions to Security/Legal, commercial and legal terms to Commercial/Legal, and evidence/conflict failures to a proposal reviewer. The classifier also distinguishes a supported negative answer such as “No, FIPS 140-3 is not established” from an unsupported affirmative answer.

`CLEAR` is possible only when citation membership, source metadata, atomic-claim support, and commitment consistency have passed and no mandatory authority risk exists. `NEEDS_HUMAN` clears active specialist work, preserves the evidence and risk audit, sets `IMMEDIATE_HITL`, leaves `final_answer=None`, and stops before promotion. Rank-5 source evidence cannot override this boundary: the RFP-005 99.99%-plus-service-credits path passes every evidence check and still interrupts, while the ordinary supported RFP-001 path clears the gate and continues. LangGraph persistence and resumable human decisions remain Steps 2.21–2.22.

Step 2.21 gives every implemented human-review route a shared checkpointed boundary. Immediate Orchestrator stops, exhausted evidence recovery, unresolved commitment conflicts, and authority-gate stops route to `human_review_checkpoint`, which writes a validated `HumanReviewRequest`, sets `awaiting_human_review=True` and `NEEDS_HUMAN`, and preserves `final_answer=None`. The next `human_review_interrupt` node calls LangGraph `interrupt()` with the compact request.

Checkpointed execution uses `build_checkpointed_fanout_graph(...)` and requires a stable `thread_id`. V1 defaults to LangGraph `InMemorySaver`, providing deterministic process-local persistence for development; callers may inject another compatible checkpointer without changing graph logic. The saved checkpoint contains complete business state, while the interrupt packet contains only reviewer-facing context and evidence IDs. Different thread IDs cannot see or overwrite each other's checkpoints.

The packet exposes `APPROVE`, `EDIT_AND_APPROVE`, `REJECT`, `ADD_GUIDANCE`, and `REQUEST_RETRY` as the locked decisions. A safe path such as RFP-001 completes without an interrupt. A non-checkpointed graph remains useful for offline component tests and stops at the same safe HITL state without attempting `interrupt()`.

Step 2.22 validates the value returned by `interrupt()` as a strict `HumanReviewDecision`. The decision is bound to the saved requirement ID and requires reviewer and timestamp audit fields. Extra fields, blank audit fields, unknown decisions, duplicate or cross-requirement proposal IDs, and rework specialists outside the saved requirement scope fail closed. Each accepted decision is appended to `human_decision_history` with its review reason; the original reviewer packet and the full checkpoint state remain available for audit.

`APPROVE` accepts the saved proposed answer, while `EDIT_AND_APPROVE` requires and preserves exact reviewer-edited text. Both may select only explicit saved proposal IDs and route to commitment promotion, but they leave the answer candidate at `PENDING` with `final_answer=None`; the Step 2.23 finalization guard remains mandatory. `REJECT` records `REJECTED`, clears selections, and ends with no answer. `ADD_GUIDANCE` creates one auditable guided-rework attempt and fans out only to relevant peer specialists before re-entering every normal evidence and governance gate. `REQUEST_RETRY` uses the existing retrieval-recovery node and counter; it is accepted only below the locked limit of two and can never create a third retrieval attempt. A reworked request may interrupt again, preserving its earlier human-decision history.

Step 2.23 inserts `finalization_guard` after a clear authority assessment and after an approving human resume, but before commitment promotion. Those are the only two incoming paths. Both the risk node and human interrupt no longer have a direct promotion edge. `finalization_guard` is the only node allowed to set `FINALIZED` and write `final_answer`; promotion can therefore rely on a completed hard guard rather than a caller-supplied status.

The typed result records four independent decisions. Evidence is acceptable only when injection is absent, citation and source gates pass, claim adjudication is valid, every atomic claim is supported and cited, every specialist aggregate is `SUPPORTED`, and no active or exhausted recovery remains. Consistency requires a validated conflict-free commitment comparison and no active or unresolved conflict state. Authority requires either a deterministic `CLEAR` assessment or an approving, requirement-bound human decision for a `NEEDS_HUMAN` assessment. Candidate integrity requires the exact generated/approved answer or a reviewer edit that matches the approved checkpoint value, introduces no new numeric anchor, and retains at least 50% material-term overlap with the grounded generated candidate.

Every pass condition is necessary. Approval cannot override evidence, injection, recovery, or conflict failure. A rejected, pending, prewritten, tampered, novel-number, or unrelated candidate cannot finalize. Malformed and contradictory state raises instead of being guessed through. A valid failure clears `final_answer` and routes checkpointed execution back to human review; a prior rejection remains `REJECTED`. A valid pass writes the exact answer and `FINALIZED`, then and only then runs narrow commitment promotion.

Step 2.24 verifies the assembled offline graph as path families rather than as isolated nodes. Exact completed-node traces cover a one-specialist simple path; peer Product/Security fan-out and deterministic fan-in; a successful targeted Security retry; a two-attempt exhausted-recovery stop; one targeted contradiction reanalysis followed by HITL; a fully evidenced SLA request that still interrupts for authority; prompt injection that interrupts before every specialist and retrieval tool; rejection with no answer or promotion; valid checkpoint approval followed by finalization and promotion; and an unsafe approval resume that the finalization guard blocks and returns to review. These tests establish that conditional routing changes real execution while preserving the peer-only topology and shared safety boundary.

Step 2.25 freezes the completed deterministic graph before model-backed specialist generation is enabled. The secret-safe milestone records file-level and aggregate checksums for source, tests, scripts, configuration templates, and synthetic data; the exact Python/package environment; the frozen retrieval configuration; 640 passing tests; and zero provider/network requests during the freeze. The future generation profile is `gpt-5.6-terra` through the Responses API with low reasoning, strict structured outputs, a 2,000-token output ceiling, response storage off, and temperature/top-p omitted. `PROVIDER_GRAPH_CALLS_ENABLED` remains false. The current model identifier is documented as an alias rather than a dated snapshot, so later provider experiments must record the resolved model and cannot claim byte-identical outputs. This freeze detects drift but does not replace version-control history.

## Section 16: illustrative execution traces

The following traces are illustrative examples only, not an exhaustive list of valid paths. Conditional edges may produce other paths based on domains, evidence state, specialist disagreement, risk/authority classification, retries, prior commitments, and human decisions.

```text
Simple: analyzer -> orchestrator -> product -> merge -> evidence -> consistency -> risk -> finalize

Cross-domain: analyzer -> orchestrator -> [product || security] -> merge -> evidence -> consistency -> risk -> finalize

Recovery: analyzer -> orchestrator -> security -> evidence -> retrieval recovery -> security -> evidence -> HITL

Authority: analyzer -> orchestrator -> product -> evidence -> consistency -> risk -> HITL -> resume -> finalize
```
