# Synthetic Enterprise Data and Tools Plan

## Trust boundary

Customer RFP content is untrusted input and supplies requirements, never operating instructions. The exact original text remains preserved for audit. High-confidence operating-instruction patterns are recorded as structured prompt-injection signals with exact source spans; they are never executed or removed. The synthetic internal knowledge base is trusted evidence. Every source carries `doc_id`, `domain`, `title`, `version`, `effective_date`, `authority_rank`, and `status`; current, authoritative sources outrank older or weaker sources.

## Synthetic corpus

V1 uses 12 fictitious trusted sources in `data/kb/` for product capabilities and availability, integrations, deployment models, service levels, security controls and certifications, data handling/residency, deliberately conflicting retention positions, implementation prerequisites, commitment authority, and proposal evidence policy. Expected behaviors live separately in `data/fixtures/` and are never indexed as evidence. Seeded cases include missing evidence, stale/conflicting sources, prompt injection, cross-domain disagreement, and authority-sensitive commitments.

## Retrieval design

All specialist retrieval returns up to Top 5 after domain and metadata filtering. After ranking, results below 25% of the strongest result's raw retrieval score are removed so a small corpus does not fill unused slots with marginal evidence. The same transparent relative cutoff applies to offline and Pinecone-backed specialist boundaries; retrieval may therefore return fewer than five results.

| Specialist | Retrieval strategy | Why |
|---|---|---|
| Product | Hybrid dense + BM25/sparse, Top 5 | Combines semantic matching with exact product names, acronyms, integrations, and availability labels. |
| Security/Compliance | Hybrid dense + BM25/sparse, Top 5 | Preserves exact matches for controls, certifications, protocols, and standards. |
| Implementation | Dense semantic, Top 5 | Implementation questions are primarily conceptual and process-oriented. |

Pinecone is the preferred retrieval layer. Hybrid result fusion must be deterministic and observable; final citations retain source IDs and metadata. If Pinecone hybrid support or account setup blocks the demo, a local BM25+dense adapter may be used behind the same tool contract without changing graph behavior.

The Pinecone adapter is lazy: importing or constructing it does not import the Pinecone SDK, create a client, resolve an index, embed a query, or make a network call. A search may initialize the provider only after the query builder and either an injected index factory or the required key/index configuration are present. Provider filters always include the locked specialist domain. Cross-domain or incomplete provider results fail closed.

## Tool contracts

- `search_product_kb(query, k=5)` -> hybrid results
- `search_security_kb(query, k=5)` -> hybrid results
- `search_implementation_kb(query, k=5)` -> dense results
- `reformulate_search_query(query, failure_context)`
- `validate_citation_ids(answer, evidence)`
- `check_source_authority(evidence)`
- `record_claim(claim)` and `lookup_prior_claims(claim_type)`
- `check_structured_conflict(proposed, prior)`
- `request_human_approval(reason, payload)`

Each specialist search boundary fixes its domain before applying optional metadata filters for lifecycle status, minimum authority rank, allowed document IDs, and effective date. Filters apply before scoring and cannot be used to request another specialist's documents. The boundary accepts only `k=1` through `k=5`; V1 defaults to, never exceeds, and does not pad Top 5. Results below the frozen `0.25 × strongest raw score` relevance floor are omitted.

The Step 2.14 reformulation tool is deterministic and operates only on recorded recoverable evidence context. It preserves the original material query, adds the failed atomic claim plus domain- and failure-specific terms, produces one query per affected specialist, and caps output at 800 characters. It performs no retrieval itself. Empty, missing-direct, weak, ineligible, tool-exception, and invalid-output states remain distinct; invalid structured output is recorded but is not treated as a search-query problem. Prompt-injection state is rejected, and tool contexts retain only exception class names rather than raw provider messages.

Step 2.15 passes each saved reformulated query through the same domain-locked specialist search boundary used initially. A recovery round may target one or several peers, but it increments the requirement-level retry counter once. Successful peer outputs from the initial run remain available when another peer retries. Every retry re-enters Merge and all evidence gates. `RecoveryAttempt` accepts only attempts 1 and 2; unresolved failure at count 2 stops automation at `IMMEDIATE_HITL`. V1 records exact retry queries for audit, and local tests execute only deterministic offline retrieval.

Step 2.16 implements the draft side of `record_claim` as a deterministic normalization boundary after successful claim support and recovery planning. It recognizes only the seven approved commitment types and records the source requirement, atomic claim, specialist, and evidence IDs with every proposal. Draft proposals are always non-approved and non-authoritative and remain separate from `commitments`. Promotion, prior-authoritative-value lookup, and conflict decisions remain later graph steps; extraction cannot authorize its own output.

Step 2.17 implements the authoritative write boundary. A proposal ID must be explicitly selected, the same requirement must carry an approving human decision, and the requirement must be finalized before `record_claim` may update authoritative `commitments`. Authoritative records retain proposal, claim, specialist, evidence, reviewer, decision, and timestamp provenance. Non-selection, missing approval, missing finalization, and non-approving decisions are observable non-write outcomes; malformed or conflicting state fails closed. Prior-value lookup and comparison remain Step 2.18.

Step 2.18 implements `lookup_prior_claims` and normalized comparison as a local, read-only boundary. It validates authoritative records as approved and finalized, groups values by narrow commitment type plus material subject, and distinguishes no prior value, an exact approved match, a changed prior value, and disagreement among current proposals. Conflict records retain both current and prior IDs and values. The node does not update either ledger or choose a route; Step 2.19 consumes its saved result.

Step 2.19 implements one targeted `check_structured_conflict` recovery round. It resolves each conflict to the peer specialists that produced the involved proposals, creates one value-specific query per affected peer, and records exact execution inputs. The pass uses the normal domain-locked retrievers and every evidence gate. Conflict reanalysis has a separate one-round counter and cannot consume or expand the two-retry evidence budget. A remaining contradiction ends at `NEEDS_HUMAN`; neither value is selected and authoritative memory is unchanged.

Step 2.20 implements the separate organizational-authority boundary after evidence and consistency checks. Current, high-authority evidence may prove the documented standard position, but it cannot grant the agent permission to accept a customer-specific SLA, service credit, roadmap date, pricing or legal term, security exception, or material residency ambiguity. The deterministic `risk_authority` node maps each finding to its required human owner, records whether the upstream evidence checks passed, and stops authority-sensitive work at `NEEDS_HUMAN` before commitment promotion. Ordinary supported descriptions with no mandatory approval category continue. No provider or model call is involved in this decision.

Step 2.21 adds LangGraph process-local checkpointing and a real human-review interrupt. V1 uses `InMemorySaver` only for local development and tests; it is not represented as durable across process restarts. The graph accepts an injected compatible checkpointer for a future database-backed deployment. The full checkpoint retains evidence and governance state under an isolated `thread_id`; the interrupt payload contains compact reviewer-facing fields and evidence IDs rather than duplicating full source passages. Checkpoint and interrupt operations are local and make no OpenAI, Pinecone, or other network call.

## Preferred V1 stack

Python + LangChain + LangGraph + OpenAI API + Pinecone + LangSmith + Streamlit + `python-docx`.

Mem0 and ElevenLabs are not used in V1 unless a new, concrete need emerges. Nebius remains optional and must not be forced into the architecture. No real customer data or production enterprise integrations are in scope.
