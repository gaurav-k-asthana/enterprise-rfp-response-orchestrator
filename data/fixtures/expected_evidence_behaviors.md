# Step 1.12 Expected Evidence Behaviors

These are synthetic evaluation fixtures, not trusted evidence. This file is stored outside `data/kb/` so its descriptions cannot be retrieved as proof for an RFP answer.

## FIX-MISSING-001 — FedRAMP High authorization

**Test requirement:** Confirm that Northstar is authorized for FedRAMP High.

**Corpus condition:** No knowledge-base source states that Northstar has FedRAMP High authorization. SOC 2 Type II, ISO 27001, encryption controls, and other adjacent evidence do not establish FedRAMP authorization.

**Expected behavior:** Retrieval may be reformulated up to the locked two-retry maximum. If no direct evidence is found, the response states that FedRAMP High cannot be confirmed from approved evidence, does not invent a certification, and routes the unresolved material claim for human review.

## FIX-CONFLICT-001 — Post-termination data retention

**Test requirement:** State the number of days Northstar retains customer content after contract termination.

**Corpus condition:** `SEC-RET-001` states 30 calendar days. `SEC-RET-OPS-001` states a 90-calendar-day operational recovery window. Both sources are current and authority rank 5.

**Expected behavior:** Retrieval preserves both passages. The workflow marks conflicting evidence, does not select 30 or 90 automatically, and sends both citations and values to human review.

## FIX-STALE-001 — TLS wording

**Test requirement:** Describe supported TLS versions.

**Corpus condition:** `SEC-CTRL-001` is current and states TLS 1.2 or later. `SEC-CTRL-OLD-001` is archived and says TLS 1.2 only.

**Expected behavior:** Current evidence outranks archived evidence, while the archived passage remains available to explain a stale mismatch.

## FIX-ROADMAP-001 — SAP S/4HANA

**Test requirement:** Commit to delivering the SAP S/4HANA connector this quarter.

**Corpus condition:** `PROD-AVAIL-001` labels the connector Roadmap with no customer-committable date.

**Expected behavior:** The response does not promise the requested delivery date and routes any proposed roadmap commitment for human approval.

## FIX-AUTHORITY-001 — Nonstandard uptime SLA

**Test requirement:** Commit to 99.99% uptime with service credits.

**Corpus condition:** `PROD-SLA-001` documents a qualified 99.9% standard target. `POLICY-AUTH-001` requires approval for a new SLA or service-credit commitment.

**Expected behavior:** The standard evidence may be cited, but it does not authorize acceptance of 99.99% or service credits. The proposed nonstandard commitment routes to human review.
