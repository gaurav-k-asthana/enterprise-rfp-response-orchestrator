# Five-minute demo script and credential-safe recording checklist — V1

This is a **4:50 target** for a user-recorded walkthrough of the five frozen,
fictitious cases in [demo_cases_v1.md](../data/fixtures/demo_cases_v1.md).
The Streamlit app is a deterministic **offline** demonstration. The separately
approved OpenAI/Pinecone comparison produced the [verified metrics](evaluation_metrics_v1.md);
the browser walkthrough is not a live provider run. Do not use a real customer
RFP or resume any human-review checkpoint in this first-run recording.

## Prepare in VS Code (before recording)

1. Open the `RFP Agentic AI` folder in VS Code. Close the `.env` editor tab and
   every account/API-key browser tab. Do not show VS Code or a terminal in the
   recorded area. Never display or paste a key, even briefly.
2. In **Terminal → New Terminal**, enter these lines one at a time (only if a
   Streamlit server for this project is not already running):

   ```bash
   cd "/Users/Gaurav_Asthana/Documents/AI System Builds/RFP Agentic AI"
   source .venv/bin/activate
   python -m streamlit run app.py
   ```

   Open `http://localhost:8502` after Streamlit reports it is ready. If 8502
   is occupied, leave the other process alone; run
   `python -m streamlit run app.py --server.port 8503` in the project terminal
   and open `http://localhost:8503` instead. The offline demo needs no API
   keys and should make no OpenAI, Pinecone, or LangSmith request.
3. In the browser, confirm the title **Enterprise RFP Response Orchestrator**
   and the synthetic-data warning. In the sidebar, locate **Sample requirement**,
   **Selected requirement text**, and **Run selected requirement**. The page
   shows **Architecture execution map** above **Requirement result**, with
   response/evidence/trace details farther down. Rehearse navigation once
   before recording; do not save reviewer decisions. A fresh browser session
   gives the cleanest first-run sequence. If you need to reset, use **Clear
   current run**; do not claim that clearing is durable checkpoint deletion.
4. Set browser zoom so the map and sidebar remain legible. Use a browser-only
   recording region/window, with notifications silenced, the address bar and
   bookmarks hidden or cropped, and no private desktop, username/path, other
   project, account tab, or terminal visible. Preview the capture boundary and
   microphone before starting. The recording tool and file destination are
   your choice; save locally first and inspect before sharing.

## Timed on-screen walkthrough (target 4:50; hard stop before 5:00)

Use the sidebar selector and click **Run selected requirement** *once* for
each case. Wait for **Saved run for RFP-…** before moving on. Scroll between
the map and the **Requirement result** row as needed; avoid opening human
decision controls. These are talking points, not claims that every possible
graph branch or every DOCX page was visually verified.

| Time | On screen / click | Short narration |
|---|---|---|
| 0:00–0:20 | Show title, synthetic warning, and map. | “This is a synthetic, offline RFP response workflow. It routes each requirement through evidence and authority checks; it does not make customer commitments on its own.” |
| 0:20–0:50 | Select `RFP-001`; click **Run selected requirement**; show Product lit and the finalized result row. | “A straightforward product question uses Product alone. The other peers stay inactive, and the evidence-backed draft finalizes.” |
| 0:50–1:25 | Select `RFP-002`; run; show Product and Security branches and their lit arrows joining at Merge. | “A cross-domain question fans out to two independent peers. Neither specialist calls the other; their results merge before the safety gates.” |
| 1:25–2:05 | Select `RFP-021`; run; show **Retrieval Recovery** counter `2/2` and human-review stop. | “FedRAMP High is not directly evidenced. Two bounded retrieval attempts do not invent certification, so there is no final answer.” |
| 2:05–2:45 | Select `RFP-014`; run; show **Conflict Reanalysis** counter `1/1` and human-review stop. | “Current retention sources disagree at 30 and 90 days. One targeted reanalysis cannot resolve the contradiction, so the workflow pauses.” |
| 2:45–3:25 | Select `RFP-005`; run; show the result and human-review area, without choosing an action. | “The documented 99.9% standard does not authorize this customer's requested 99.99% SLA and credits. The system stops for organizational review.” |
| 3:25–4:20 | Keep the safe browser view on the map/result; verbally cite the linked metrics table rather than switching to a secret-bearing window. | “Separately, we evaluated 24 frozen synthetic cases with provider-backed runs. Safe Completion was 20 of 24 for one generalist and 10 of 24 for orchestrated peers. That favors the generalist **in this V1 test**, not universally. Peer runs had four primary execution failures; neither arm detected conflicts well.” |
| 4:20–4:50 | Return to the synthetic warning or a paused result and close. | “The design makes routing, evidence, retries, and human authority inspectable. This remains a prototype: reviewer-action gaps, process-local checkpoints, and small-corpus limits need work before any real-data deployment.” |

If a run or scroll takes longer than rehearsed, shorten narration and leave
the three paused cases at **NEEDS_HUMAN**. Do not speed through or edit the
video so it appears that a review decision occurred. If you reach 4:20 before
the final case finishes, finish the safety example and give only the
one-sentence bounded result; omit a metric-by-metric tour. The linked table
has the complete numbers and caveats. Do not claim the demo itself produced
the provider metrics.

## Credential-safe recording and publication check

- [ ] **Before:** Only fictitious RFP data is loaded. `.env` and any API-key,
      Pinecone, OpenAI, or LangSmith account page are closed or outside the
      capture area. Browser bookmarks, profile, notifications, desktop, terminal,
      file paths, and other projects are not visible.
- [ ] **Before:** Capture a 5-second sample and replay it. Confirm text is
      readable, audio works, the whole capture frame is safe, and the title is
      the RFP project (not the IRS project on another port).
- [ ] **During:** Record the browser window/region only. Run the five IDs in
      frozen order; do not type credentials, open `.env`, make provider calls,
      submit a human decision, or make an unauthorized commitment.
- [ ] **During:** Show recovery `2/2`, conflict reanalysis `1/1`, and the
      paused result status honestly. Present 20/24 versus 10/24 only as the
      separately approved synthetic V1 comparison, not as a live demo score.
- [ ] **After:** Replay the entire file, including the first and last frames.
      Pause around every tab/window change and visible address bar. Check for
      secrets, personal identifiers, confidential data, misleading cuts, and
      a duration under five minutes. If anything sensitive appears, do not
      publish that file; make a clean recording instead.
- [ ] **Before sharing:** Keep the recording local until reviewed by Gaurav
      Asthana. Link the [architecture snapshot](architecture_execution_rfp002.md)
      and [metrics table](evaluation_metrics_v1.md) in accompanying text; do
      not bundle `.env`, ignored `outputs/`, raw traces, or provider credentials.

The recording itself is user-owned and is **not** created by this checklist.
This step prepares and verifies the script; it does not imply that the video
has been recorded, reviewed, or published.
