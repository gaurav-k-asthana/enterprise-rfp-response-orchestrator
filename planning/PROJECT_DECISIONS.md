# Project Decision Register

These decisions are locked for V1:

- Three independent peer specialists: Product, Security/Compliance, and Implementation.
- No specialist-to-specialist routing or edges.
- Orchestrator selects strategy and minimum safe execution path; it is not a simple classifier.
- Product and Security/Compliance use hybrid dense + BM25/sparse Top-5 retrieval; Implementation uses dense Top-5.
- Narrow structured commitment ledger plus a distinct consistency check.
- HITL is based on risk and organizational authority, not only confidence.
- Synthetic enterprise data and an explicit trusted-KB/untrusted-RFP boundary.
- Simple DOCX output via `python-docx`.
- Single-agent baseline evaluated on the same 24-case gold set.
- Safe Completion Rate remains the end-to-end headline metric.
- Preferred stack: Python, LangChain, LangGraph, OpenAI API, Pinecone, LangSmith, Streamlit, and `python-docx`.
- Mem0 and ElevenLabs stay out of V1 unless a new need emerges; Nebius is optional.
- The live architecture map is lightweight, event-driven, and demo-focused.
- Post-submission architecture simplification analysis is outside this project.

