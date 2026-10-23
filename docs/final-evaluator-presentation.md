# CardioTrack CT-200 — Final Evaluator Presentation
## Document Intelligence, Relational Lineage & Source-Grounded QA Test Generation

---

### Slide 1: Title & Overview
**CardioTrack CT-200 Medical Device Document Intelligence & QA Generation Engine**  
*Deterministic Document Hierarchy Reconstruction, Cryptographic Provenance, and Explainable Staleness Detection for Regulated Medical Software*

- **Domain:** Document Intelligence, Software Verification & Validation (V&V), Relational Version Lineage.
- **One-Sentence Value Proposition:** Transforms unstructured medical device PDF manuals into structured, cryptographically grounded, version-tracked QA test suites while deterministically preventing specification drift and LLM hallucinations.
- **Target System:** CardioTrack CT-200 Non-Invasive Blood Pressure Monitor (v1 & v2 Technical Manuals).
- **Presenter:** Project Assessment Team / Independent Technical Assessor.
- **Repository:** `https://github.com/ibharath-ofcl/Tri9T-AI.git` (Branch: `main`).

---

### Slide 2: Problem Statement & Industrial Motivation
**Why is Medical Device Specification Management Fragile?**

1. **Unstructured & Irregular Manuals:** Technical specifications reside in complex PDFs with non-standard typography, numbering gaps (§2.1.1.1 child of §2.1), body-sized headings (11pt in §3.2), split tables, and duplicate headings.
2. **Silent Specification Drift:** Revisions modify safety-critical limits (battery cycle ratings, inflation pressure steps, overpressure timing) without unified machine-readable changelogs.
3. **Generative LLM Hallucinations:** LLMs drafting test cases routinely fabricate unsupported tolerances (e.g. `±2 mmHg`), invent error codes, or blend specifications across versions.
4. **Unpinned Test Artifacts:** Without cryptographic bindings to immutable document snapshots, test suites silently become stale and invalid when device revisions are released.
5. **Intended Boundary:** This system is an **engineering QA verification and traceability tool**; it does not perform clinical diagnosis, patient monitoring, or device parameter control.

---

### Slide 3: Proposed Solution
**An End-to-End Deterministic Verification Pipeline**

```
┌─────────────────────────────────┐      ┌───────────────────────────────────┐
│  Digital PDF Manuals (v1 & v2)  │ ───► │  Typography Extraction Engine     │
└─────────────────────────────────┘      │  (Character geometry & IR-1..IR-7)│
                                         └─────────────────┬─────────────────┘
                                                           │
┌─────────────────────────────────┐      ┌─────────────────▼─────────────────┐
│  Version-Pinned Named Selection │ ◄─── │  Immutable Relational Snapshots   │
│  (Safety-Critical Scope)        │      │  (SQLite: Nodes, Tree, SHA-256)   │
└────────────────┬────────────────┘      └───────────────────────────────────┘
                 │
┌────────────────▼────────────────┐      ┌───────────────────────────────────┐
│  QA Test Case Generation Engine │ ───► │  Deterministic Grounding Auditor  │
│  (Bounded retry, Mock/OpenAI)   │      │  (5-state claim evaluation)       │
└─────────────────────────────────┘      └─────────────────┬─────────────────┘
                                                           │
┌─────────────────────────────────┐      ┌─────────────────▼─────────────────┐
│  Target v2 Cross-Version Diff   │ ───► │  Explainable Staleness Classifier │
│  (Multi-signal lineage match)   │      │  (Precedence hierarchy & deltas)  │
└─────────────────────────────────┘      └───────────────────────────────────┘
```

- **Deterministic Ingestion:** Eliminates typography edge cases via geometric character extraction.
- **Relational Lineage:** Stores immutable versioned snapshots with SHA-256 content hashes.
- **Cryptographic Provenance:** Every test assertion binds to a specific `node_version_id` and content hash.
- **Explainable Staleness:** Automatically detects requirement drift and highlights parameter deltas.

---

### Slide 4: System Architecture & Core Modules
**Modular, Loosely Coupled Backend Architecture**

1. **PDF Parsing Engine (`app/services/pdf_parser.py`):**
   - Built on `pdfplumber` geometric layout analysis.
   - Deterministically resolves all 7 identified document irregularities (IR-1 through IR-7).
2. **Relational Versioning & Lineage (`app/db/models.py`, `app/services/version_matcher.py`):**
   - SQLite relational models: `DocumentModel`, `DocumentVersionModel`, `LogicalNodeModel`, `NodeVersionModel`.
   - Multi-signal matching across titles, section numbers, and hierarchical positions.
3. **Version-Pinned Selections (`app/repositories/document_repository.py`):**
   - Named test selections pinned immutably to a specific document version UUID.
4. **QA Test Generation Service (`app/services/qa_generation_service.py`):**
   - Pluggable provider abstraction (`MockLLMProvider` for deterministic offline execution; OpenAI compatible for remote models).
   - Strict PascalCase Pydantic validation with bounded corrective retries (max 3).
5. **Deterministic Grounding Auditor (`app/services/grounding_auditor.py`):**
   - Evaluates claims into 5 canonical states: `SOURCE_SUPPORTED`, `DERIVED_WITH_EXPLANATION`, `PROPOSED_SETUP`, `UNSUPPORTED`, `AMBIGUOUS`.
6. **Persistence & REST API (`app/main.py`, `app/repositories/json_test_suite_store.py`):**
   - Atomic JSON document store using temporary write + `os.replace` and `fcntl.flock`.
   - FastAPI REST API providing 18 operational OpenAPI endpoints.

---

### Slide 5: End-to-End Verification Workflow
**From Raw Technical Manual to Audited QA Test Suite**

1. **Ingest Document Revisions:**
   - Ingest `ct200_manual.pdf` (v1: 6 pages, 27 nodes) and `ct200_manual_v2.pdf` (v2: 7 pages, 28 nodes).
   - Compute SHA-256 content hashes across headings, bodies, and tables.
2. **Establish Named Verification Selection:**
   - Curate safety-critical requirements (§2.1.1.1 Battery, §3.2 Cuff Inflation, §4.2 Error Codes).
   - Pin selection permanently to v1 snapshot UUID.
3. **Generate Structured QA Candidates:**
   - Produce 4 structured test cases conforming to `TestCaseSchema` (ID, Title, Prerequisites, Steps, Expected Result, Standard Ref, Provenance).
4. **Audit Grounding & Provenance:**
   - Audit 33 distinct factual claims: 27 `SOURCE_SUPPORTED`, 6 `PROPOSED_SETUP`, 0 `UNSUPPORTED`.
   - Verify that test equipment fixtures are clearly separated from device requirements.
5. **Evaluate Staleness Against Target Revision (v2):**
   - Classify 4 pinned test cases as `STALE` due to detected numerical and timing deltas.
   - Automatically raise `human_review_required: true`.
6. **Evaluate Unchanged Control Case:**
   - Section 1.1 (Intended Use) evaluated against v2 $\rightarrow$ classified as `CURRENT`.

---

### Slide 6: Verified Version Differences (CT-200 v1 vs v2)
**Ground-Truth Physical Manual Changes Detected by the Engine**

| Specification Parameter | CT-200 v1 Manual | CT-200 v2 Manual | Classification | Engine Impact Analysis |
| :--- | :---: | :---: | :---: | :--- |
| **Battery Life Rating** (§2.1.1.1) | 300 cycles | **250 cycles** | `NUMERIC_CHANGE` | Flags TC-BAT-001 & 002 as STALE |
| **Low-Battery Alarm Threshold** (§2.1.1.1) | 15% | **10%** | `NUMERIC_CHANGE` | Precedence over wording change |
| **Cuff Inflation Step Increment** (§3.2) | 40 mmHg | **30 mmHg** | `NUMERIC_CHANGE` | Flags TC-CUFF-001 as STALE |
| **Overpressure E3 Auto-Deflate** (§4.2) | 2.0 seconds | **1.5 seconds** | `TIMING_CHANGE` | Flags TC-ERR-001 as STALE |
| **Bluetooth Sync Error** (Table 4.1) | Not present | **Added 'E6'** | `TABLE_ROW` | Detects new error code row |
| **Data Export Feature** (§5.3) | Not present | **New Section 5.3** | `ADDED` | Detects added feature & 2 subsections |

- **Zero Silent Drift:** The staleness classifier maps source node modifications directly to dependent test cases.
- **Unchanged Control Guarantee:** §1.1 Intended Use remains strictly `CURRENT` (zero false positives).

---

### Slide 7: Grounding, Cryptographic Provenance & Safety
**Defending Against Hallucinations and Adversarial Inputs**

- **Cryptographic Provenance Binding:**
  - Each assertion records `source_node_version_id`, `source_content_hash`, and section reference.
  - If a content hash is tampered with or points to a differing version, the auditor flags the claim as `UNSUPPORTED`.
- **5-State Categorization:**
  - `SOURCE_SUPPORTED`: Number, unit, and condition directly found in authoritative section text.
  - `DERIVED_WITH_EXPLANATION`: Arithmetic step progression with explicit formula and base value.
  - `PROPOSED_SETUP`: External laboratory fixture/equipment (distinguished from device requirement).
  - `UNSUPPORTED`: Hallucinated tolerance (e.g. `±2 mmHg`), invented error code (`E9`), or wrong unit.
  - `AMBIGUOUS`: Unresolved cross-references or conflicting thresholds.
- **PDF Prompt-Injection Resilience:**
  - Adversarial instructions embedded in manual text (e.g., `<SYSTEM>Ignore rules</SYSTEM>`) are treated as inert string content, neutralizing prompt injection vectors.
- **Boundary Truth:** Grounding rules utilize deterministic unit/value matching; complex natural-language paraphrases conservative route to **Human-in-the-Loop review**.

---

### Slide 8: Technology Stack & REST API
**Lightweight, Fully Offline Architecture**

- **Runtime & Framework:** Python 3.13, FastAPI (ASGI), Uvicorn.
- **Schema Validation:** Pydantic v2 (Strict typing, PascalCase serialization).
- **Relational Persistence:** SQLAlchemy 2.0 ORM with SQLite database (zero-dependency).
- **Document Store:** Atomic JSON repository with `fcntl.flock` concurrency protection.
- **PDF Extraction:** `pdfplumber` geometric typography extractor.
- **Test Harness:** `pytest`, `pytest-asyncio`, `httpx` TestClient.

#### Operational REST Endpoints (18 OpenAPI Paths)
- `POST /api/v1/documents/ingest` — Ingest PDF manual, extract nodes, store snapshot.
- `GET  /api/v1/documents/{id}/sections` — Retrieve document hierarchy tree.
- `GET  /api/v1/nodes/{id}/changes` — Cross-version section diff & content delta.
- `POST /api/v1/selections` — Create version-pinned named selection.
- `POST /api/v1/selections/{id}/test-suites` — Generate grounded QA test candidates.
- `GET  /api/v1/selections/{id}/staleness` — Selection-wide staleness & impact assessment.
- `GET  /api/v1/test-suites/{generation_id}` — Retrieve persisted QA test suite & audit.

---

### Slide 9: Verification Evidence & Test Results
**Rigorous Multi-Layer Verification Suite**

```
┌────────────────────────────────────────────────────────────────────────┐
│                   VERIFICATION SUMMARY (COMMIT 5c93f16)                 │
├────────────────────────────────────────────────────────────────────────┤
│  ✓ Automated Test Suite (pytest)       : 90 / 90 PASSED (100% Pass)    │
│  ✓ Evaluator Walkthrough Demo          : 14 / 14 MILESTONES PASSED     │
│  ✓ Requirements Traceability (RTM)     : 16 / 16 REQUIREMENTS PASSED   │
│  ✓ Adversarial Red-Team Grounding      : 14 / 14 ATTACK VECTORS CAUGHT │
│  ✓ OpenAPI Schema Consistency          : 18 / 18 REGISTERED ROUTES     │
│  ✓ Sample JSON Response Validation     : 6 / 6 EXAMPLES SCHEMA-VALID   │
│  ✓ Clean-Checkout Execution Time       : ~6.5 seconds total runtime    │
└────────────────────────────────────────────────────────────────────────┘
```

- **Reproducibility Guarantee:** Executed and verified in a clean-checkout environment without pre-existing databases or network dependencies.
- **Idempotency Verified:** Duplicate requests return identical generation IDs; conflicting parameters reject with `HTTP 409 Conflict`.

---

### Slide 10: Limitations, Impact & Conclusion
**Practical Impact, Ethical Disclosures & Future Horizon**

#### Documented Limitations
1. **Rule-Based Grounding Scope:** Canonicalizes numbers, units, tolerances, and error codes; subtle natural language semantic shifts require human engineer review.
2. **Typography-Bound PDF Parser:** Optimized for digital CT-200 vector manuals; does not perform optical character recognition (OCR) on scanned bitmap images.
3. **Storage Concurrency:** SQLite and local atomic files provide zero-setup evaluation; enterprise multi-user deployments require PostgreSQL.

#### Regulatory & Safety Non-Claim
- **Prototype QA Tool:** Generates candidate test procedures to assist QA engineers. It is **not** certified under FDA 21 CFR Part 820, IEC 62304, or ISO 13485.

#### Summary of Contribution
- A fully reproducible, explainable, and grounded medical document intelligence platform that bridges the gap between unstructured technical manuals and version-safe automated QA verification.
