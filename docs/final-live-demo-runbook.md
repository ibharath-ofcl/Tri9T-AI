# CardioTrack CT-200 — Final Live Demo Runbook
## 5–7 Minute Interactive Technical Walkthrough for Evaluators & Reviewers

---

### Executive Demo Summary
This runbook provides an evaluator or presenter with an exact, repeatable, 5-to-7-minute live demonstration of the CardioTrack CT-200 Document Intelligence and QA Generation system. The demonstration runs 100% offline, using deterministic local parsing and the offline `MockLLMProvider`, requiring zero external API keys or cloud databases.

---

### Phase 0: Prerequisites & Setup (~1 minute)

#### 1. Activate Environment & Confirm Dependencies
Open a clean terminal in the repository root:
```bash
cd /path/to/Tri9T-AI
source .venv/bin/activate  # or: python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

#### 2. Confirm Assets & Offline Mode
Check that both CT-200 manual PDFs are present:
```bash
ls -lh data/ct200_manual*.pdf
```
*Expected Output:*
- `data/ct200_manual.pdf` (~443 KB)
- `data/ct200_manual_v2.pdf` (~447 KB)

> **Spoken Cue:**  
> *"Welcome. Today I am demonstrating the CardioTrack CT-200 Medical Device Document Intelligence and QA Generation Engine. This system ingests technical manuals, extracts structured document hierarchies, maintains immutable version lineage, generates grounded QA test cases, and automatically detects when revisions invalidate existing test suites. The entire demo runs fully offline and deterministically on local storage."*

---

### Phase 1: High-Speed Verification Suite (~1 minute)

Run the automated verification runner to demonstrate overall system integrity:
```bash
python3 -m scripts.stage7_final_verification
```

#### Observable Output:
- **Test Suite:** 90 tests passed in ~6.5 seconds.
- **Red-Team Tests:** 14/14 adversarial grounding vectors passed.
- **OpenAPI Validation:** 18 operational routes validated.
- **Verdict:** `STAGE 7 FINAL VERIFICATION VERDICT: [ALL CHECKS PASSED]`

> **Spoken Cue:**  
> *"Before exploring the interactive demo, we execute the automated verification runner. In six seconds, it validates all 90 unit tests, 14 adversarial red-team vectors, and 18 OpenAPI endpoints, confirming that our core invariants are 100% functional."*

---

### Phase 2: The Core Evaluator Walkthrough Demo (~2 minutes)

Execute the 14-milestone automated walkthrough:
```bash
python3 -m scripts.evaluator_demo
```

#### Key Milestones to Point Out:

1. **Steps 2 & 3 — Ingestion & Hierarchy:**
   - Ingests v1 (6 pages, 27 nodes) and v2 (7 pages, 28 nodes).
   - Resolves all 7 typography edge cases including IR-1 (§2.1.1.1 gap) and IR-2 (§3.2 11pt heading).
2. **Step 5 — Cross-Version Specification Changes:**
   - Highlights 6 real differences:
     - Battery cycles: $300 \rightarrow 250$ cycles.
     - Low-battery alert: $15\% \rightarrow 10\%$.
     - Cuff step increment: $40 \rightarrow 30\text{ mmHg}$.
     - E3 overpressure auto-deflation limit: $2.0 \rightarrow 1.5\text{ seconds}$.
     - Table 4.1: Row `E6` (Bluetooth Sync Failure) added.
     - Section 5.3 Data Export: New section added with 2 subsections.
3. **Steps 7 & 8 — Version-Pinned Selection & Generation:**
   - Creates `CT200-Core-Safety-Critical-Suite` permanently pinned to v1.
   - Generates 4 PascalCase test cases via `MockLLMProvider`.
4. **Step 9 — Cryptographic Provenance Bindings:**
   - Shows SHA-256 content hashes (e.g., `dec9f4eebc56542f...`) binding each test case to v1 source nodes.
5. **Step 10 — Source-Grounding Audit:**
   - Audits 33 claims: 27 `SOURCE_SUPPORTED`, 6 `PROPOSED_SETUP`, 0 `UNSUPPORTED`.
6. **Step 11 — Adversarial Grounding Attack Detection:**
   - Injects unsupported assertion `40 mmHg ±2 mmHg` & `99.9% uptime`.
   - Engine flags 4 unsupported claims and raises `human_review_required: true`.
7. **Step 12 & 13 — Staleness & Control Case:**
   - Safety-critical suite marked `IMPACTED` due to numeric and timing deltas.
   - Control section §1.1 Intended Use verified as `CURRENT` (zero false alarms).

> **Spoken Cue:**  
> *"Notice Step 11: when an adversarial test case claims a tolerance of ±2 mmHg—which does not exist in the manual—the grounding auditor catches it immediately and flags it for human review. In Step 12, when evaluating our v1 suite against v2, the classifier identifies that the battery life dropped from 300 to 250 cycles and inflation steps changed from 40 to 30 mmHg, marking the suite as STALE."*

---

### Phase 3: Interactive REST API & Swagger UI (~2 minutes)

#### 1. Start FastAPI in Terminal 1
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

#### 2. Open Browser or Run cURL in Terminal 2

##### Check System Health
```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```
*Expected Output:* Status `healthy`, version `0.3.0`, both PDF assets present.

##### Explore Interactive Swagger Documentation
Open your browser to:
[http://localhost:8000/docs](http://localhost:8000/docs)

Show the 18 registered endpoints across the 4 major resource groups:
- `/api/v1/documents/*` — Ingest, list, hierarchy tree, search, and document impact.
- `/api/v1/nodes/*` — Node details, cross-version diffs, and change classification.
- `/api/v1/selections/*` — Version-pinned selections CRUD, validation, and staleness.
- `/api/v1/test-suites/*` — Test suite generation, atomic retrieval, and grounding audit.

##### Ingest Document via API (Live Demonstration)
```bash
curl -s -X POST "http://localhost:8000/api/v1/documents/ingest" \
  -H "Content-Type: application/json" \
  -d '{"file_path": "data/ct200_manual.pdf", "version": "v1"}' | python3 -m json.tool
```
*Expected Output:* Returns document ID, version UUID, 6 pages, 27 nodes.

> **Spoken Cue:**  
> *"The FastAPI backend provides 18 fully documented endpoints conforming to OpenAPI 3.1. Through Swagger UI, evaluators can inspect document hierarchies, query cross-version node diffs, create version-pinned selections, and generate grounded test suites programmatically."*

---

### Phase 4: Clean Shutdown & Graceful Exit (~30 seconds)

1. In Terminal 1 where Uvicorn is running, press:
   `Ctrl + C`
2. Confirm the server shuts down cleanly:
   ```
   INFO:     Shutting down
   INFO:     Waiting for application shutdown.
   INFO:     Application shutdown complete.
   INFO:     Finished server process
   ```
3. Run `git status` to prove to the evaluator that zero untracked databases or temporary junk files were left behind:
   ```bash
   git status
   ```
   *Expected Output:* `nothing to commit, working tree clean`.

> **Spoken Cue:**  
> *"The demo leaves zero side effects or dangling processes. All test runs operate in isolated scratch databases, and the working tree remains completely clean."*

---

### Fallback Plan (Contingency Guide)

| Scenario | Symptom | Immediate Contingency Action |
| :--- | :--- | :--- |
| **Port 8000 Busy** | `[Errno 48] Address already in use` | Run Uvicorn on an alternate port: `uvicorn app.main:app --port 8080`. |
| **Browser Unavailable** | Presentation machine lacks GUI | Use the terminal-based `python3 -m scripts.evaluator_demo`, which outputs all 14 milestones in formatted color text. |
| **No Network / Offline** | Air-gapped presentation room | System is 100% offline by default using `MockLLMProvider` and local SQLite. No internet connection is needed. |
| **Accidental File Mutation** | Unsaved edits in working tree | Run `git restore .` to revert to the clean audited commit `5c93f16`. |
