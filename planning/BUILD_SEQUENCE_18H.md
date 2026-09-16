# 18-Hour Build Sequence

| Time | Work | Exit condition |
|---:|---|---|
| 0:00–1:00 | Repository, environment, package skeleton, config, typed models | Clean imports and local tests |
| 1:00–3:00 | Synthetic corpus, metadata, sample RFP, seeded failure cases | Fixtures cover the five demo paths |
| 3:00–5:00 | Retrieval adapters: Product/Security hybrid Top-5; Implementation dense Top-5 | Stable results with citations and filters |
| 5:00–8:00 | LangGraph state, analyzer, orchestrator, three peer specialists, fan-out/fan-in | Single and parallel traces pass |
| 8:00–10:00 | Evidence checks, bounded recovery, narrow commitment ledger, consistency | Weak evidence and conflicts route correctly |
| 10:00–11:30 | Risk/authority gate and HITL interrupt/resume | Approval decisions resume safely |
| 11:30–13:30 | Streamlit workflow plus live architecture execution map | Node events animate actual graph state |
| 13:30–14:15 | Simple `python-docx` export | Download opens and remains readable |
| 14:15–16:00 | 24-case eval harness and single-agent baseline | Same cases/metrics run on both paths |
| 16:00–17:00 | LangSmith tracing, latency/token capture, failure testing | Traces and errors are inspectable |
| 17:00–18:00 | README, five-case demo rehearsal, contingency fixes | Reproducible local demo |

The live map is budgeted as a simple Streamlit HTML/SVG component driven by LangGraph events. If time is constrained, reduce animation polish, not the event contract or correctness.

