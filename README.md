# Tri9T-AI: CT-200 Medical Device Document Intelligence

A high-reliability Document Intelligence, Document Versioning, and Medical Device QA Traceability Engine built for the CardioTrack CT-200 Blood Pressure Monitor technical manuals.

Developed for the **Tri9T AI Internship Assignment**.

---

## Current Status: Milestone M5 (Stage 6 Complete — Submission Ready)

- **Stage 1 (Audit & Inspection):** Complete — documented in [`docs/stage-1-analysis.md`](docs/stage-1-analysis.md).
- **Stage 2 (PDF Extraction & Deterministic Engine):** Complete — documented in [`docs/stage-2-parser.md`](docs/stage-2-parser.md).
- **Stage 3 (Relational Versioning, Database & Lineage):** Complete — documented in [`docs/stage-3-versioning.md`](docs/stage-3-versioning.md).
- **Stage 4 (Version-Pinned Selections, Staleness & Impact Detection):** Complete — documented in [`docs/stage-4-selections-staleness.md`](docs/stage-4-selections-staleness.md).
- **Stage 5 (Grounded QA Generation, Validation, Provenance & Test Staleness):** Complete — documented in [`docs/stage-5-qa-generation.md`](docs/stage-5-qa-generation.md).
- **Stage 6 (Final Integration, Grounding Audit & Acceptance):** Complete — documented in [`docs/final-acceptance-report.md`](docs/final-acceptance-report.md), [`docs/stage-6-audit-plan.md`](docs/stage-6-audit-plan.md), and [`docs/api-reference.md`](docs/api-reference.md).
- **Automated Test Suite:** **76/76 tests passing** across PDF parsing, 7 structural edge cases, relational persistence, version lineage matching, named selections, staleness classification, LLM provider abstraction, strict Pydantic validation, idempotency, atomic document store, cross-version test staleness, and deterministic source-grounding audit.
- **Final End-to-End Acceptance Demo:** **14/14 milestones passing** via `python3 -m scripts.final_acceptance_demo`.

---

## Key Features Implemented

### 1. Deterministic PDF Extraction Engine (`app/services/pdf_parser.py`)
- High-fidelity typography extraction using `pdfplumber`.
- Multi-pass line aggregation with character-level font metadata (`size`, `fontname`, `bold`).
- Clean digital PDF parsing without lossy OCR overhead or stochastic LLM hallucination.

### 2. Explicit Handling of All 7 Confirmed Structural Irregularities
- **IR-1 (Missing 2.1.1 Parent):** Section `2.1.1.1` cleanly attached to `2.1` with diagnostic warning.
- **IR-2 (Body-Sized Heading Font):** Section `3.2` correctly recognized as Level-2 heading despite 11.0pt font.
- **IR-3 (Out-of-Order Sections):** Sections `3.4` and `3.3` preserved in exact source reading order with sequence warning.
- **IR-4 (Duplicate Heading Names):** Sections `4.2` and `7.1` ("Error Codes") receive unique occurrence IDs and respective parent trees.
- **IR-5 (Phantom Table Filtering):** Geometric enclosure and sparsity filtering discard cell-internal phantoms while retaining genuine specification and error code tables.
- **IR-6 (Numbered Lists in 3.3):** Blood pressure classification items 1–5 preserved as body text and not mistaken for section headings.
- **IR-7 (Cross-Page Content Continuation):** Seamlessly joins multi-page section text (e.g. 3.1 across p2–p3, 8.1 in v2 across p6–p7).

### 3. Persistent Relational Versioning & Immutable Trees (`app/db/models.py`)
- **`Document`:** Conceptual identity of the medical device manual.
- **`DocumentVersion`:** Immutable snapshot of a specific revision (v1: 27 nodes, v2: 28 nodes).
- **`LogicalNode`:** Permanent cross-version conceptual section identity.
- **`NodeVersion`:** Version-specific occurrence storing body text, cryptographic hashes (`content_hash`, `heading_hash`, `body_hash`), source page range, table data, and diagnostics.
- **SQLite Foreign Key Enforcement:** Strict connection pragmas enforce relational integrity.

### 4. Version-Pinned Named Selections (`app/db/models.py`, `app/repositories/document_repository.py`)
- **`Selection` & `SelectionNode`:** Relational entities defining named verification scopes pinned to an exact, immutable document version.
- **Strict Invariants:** A selection cannot span multiple document versions. Updating selection metadata never moves its pinned version. Deleting a selection never deletes underlying document history.
- **Insertion Order Preserved:** `SelectionNode.order_index` guarantees deterministic node retrieval order.

### 5. Explainable Staleness Classification (`app/services/staleness_classifier.py`)
- **11 Granular Categories:** `NO_CHANGE`, `FORMATTING_ONLY`, `WORDING_CHANGE`, `NUMERIC_CHANGE`, `TIMING_CHANGE`, `STRUCTURAL_CHANGE`, `ADDED`, `REMOVED`, `MOVED`, `AMBIGUOUS`, `UNCLASSIFIED`.
- **Precedence Hierarchy:** Timing and numerical changes take strict precedence over generic wording changes.
- **Contextual Delta Extraction:** Deterministic regex extractor pairs modified parameters between old and new texts:
  - §2.1.1.1: Battery life `300` $\rightarrow$ `250 cycles`, warning `15%` $\rightarrow$ `10%`.
  - §3.2: Cuff inflation increment `40` $\rightarrow$ `30 mmHg`.
  - §4.2: Auto-deflation timing `2` $\rightarrow$ `1.5 seconds`, new error code `E6 Bluetooth sync`.
  - §4.3: Error code range `E1-E5` $\rightarrow$ `E1-E6`.
- **Medical Risk Policy:** Any detected numerical or temporal shift flags `human_review_required: true`. Disclaimers included on every response.

### 6. Grounded QA Test Generation & LLM Provider Abstraction (`app/services/qa_generation_service.py`, `app/services/llm_provider.py`)
- **Pluggable Architecture:** Configurable between `MockLLMProvider` (zero external calls, repeatable test suites) and `OpenAICompatibleProvider` (exponential backoff on 429/5xx).
- **Strict Pydantic Output Validation:** Enforces exact PascalCase contract (`TestCaseId`, `Title`, `Prerequisites`, `Steps`, `ExpectedResult`, `PassFailCriteria`, `StandardRef`).
- **Bounded Validation Retries:** Maximum 3 total model attempts. Corrective feedback prompts guide the model to fix formatting or count discrepancies.
- **Deterministic Request Idempotency:** SHA-256 fingerprinting prevents duplicate executions on identical parameters while returning `HTTP 409 Conflict` on parameter mismatches.
- **Atomic Document Store:** Concurrency-safe local JSON document store (`JsonTestSuiteStore`) with temporary write replacement, advisory file locking, and corrupted file safety.
- **Cryptographic Provenance:** Binds exact source snapshot UUIDs, content hashes, and version labels directly to each test case.
- **Cross-Version Test Case Staleness:** Audits generated test suites against target document revisions (`v2`) without mutating original `v1` provenance.

### 7. Deterministic Source-Grounding Audit Engine (`app/services/grounding_auditor.py`)
- **Five-Category Claim Classification:** Evaluates every assertion, parameter, unit, and test fixture into:
  1. `SOURCE_SUPPORTED`: Explicitly present in cited source text or tables.
  2. `DERIVED_WITH_EXPLANATION`: Logically derived step progressions (e.g. $180 + 40 = 220\text{ mmHg}$).
  3. `PROPOSED_SETUP`: Engineering test bench fixtures or lab equipment tagged `[PROPOSED SETUP]` (not claimed as product specs).
  4. `UNSUPPORTED`: Ungrounded parameters, invented tolerances ($\pm 2$ mmHg), or unlisted error codes. Automatically flags `human_review_required = True`.
  5. `AMBIGUOUS`: Insufficient or conflicting source evidence.
- **StandardRef Citation Verification:** Validates that citations point to real sections and rejects fabricated external standards.
- **Suite-Level Aggregation:** Computes audit metrics and propagates human review flags to the suite payload.

---

## REST API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/documents/ingest?version=v1\|v2` | Transactional, idempotent ingestion of a manual revision. |
| `GET` | `/api/v1/documents` | Lists registered documents and all ingested versions. |
| `GET` | `/api/v1/documents/{document_id}/sections?version=v1` | Hierarchical section navigation tree. |
| `GET` | `/api/v1/nodes/{node_version_id}` | Detailed node inspection with tables, diagnostics, and hashes. |
| `GET` | `/api/v1/search?q=...&version=v1` | Full-text search across headings, bodies, and tables. |
| `GET` | `/api/v1/nodes/{logical_node_id}/changes?from_version=v1&to_version=v2` | Unified textual diff between versions. |
| `POST` | `/api/v1/selections` | Create a named selection pinned to a specific document version. |
| `GET` | `/api/v1/selections?version=v1` | List selections with optional document and version filtering. |
| `GET` | `/api/v1/selections/{selection_id}` | Retrieve selection details and all pinned node snapshots. |
| `PATCH` | `/api/v1/selections/{selection_id}` | Update selection metadata or node membership within pinned version. |
| `DELETE` | `/api/v1/selections/{selection_id}` | Delete selection without affecting underlying document history. |
| `GET` | `/api/v1/selections/{selection_id}/staleness?target_version=v2` | Assess selection staleness with parameter deltas. |
| `GET` | `/api/v1/selections/{selection_id}/impact?target_version=v2` | Partition selection nodes into affected and unaffected sets. |
| `GET` | `/api/v1/documents/{document_id}/impact?from_version=v1&to_version=v2` | Document-wide impact analysis across all pinned selections. |
| `POST` | `/api/v1/selections/{selection_id}/test-suites` | Generate 3–5 grounded QA test cases from a version-pinned selection. |
| `POST` | `/api/v1/nodes/{node_version_id}/test-suites` | Generate 3–5 grounded QA test cases from an individual node version. |
| `GET` | `/api/v1/test-suites/{generation_id}` | Retrieve persisted test suite and test cases by generation ID. |
| `GET` | `/api/v1/selections/{selection_id}/test-suites` | List all generated test suites for a selection. |
| `GET` | `/api/v1/nodes/{node_version_id}/test-suites` | List all test suites referencing an exact source node snapshot. |
| `GET` | `/api/v1/test-suites/{generation_id}/staleness?target_version=v2` | Evaluate test suite staleness against target document revision. |
| `GET` | `/api/v1/documents/{document_id}/test-suite-impact?from_version=v1&to_version=v2` | Document-wide test-suite impact across all generated suites. |

---

## Project Structure

```
Tri9T-AI/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application with persistence, search, diff, selections & QA generation
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py               # Application settings, LLM provider & store configuration
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py                 # SQLAlchemy DeclarativeBase
│   │   ├── models.py               # Models: Document, DocumentVersion, LogicalNode, NodeVersion, Selection, SelectionNode
│   │   └── session.py              # Engine, sessionmaker, and SQLite FK pragma
│   ├── prompts/
│   │   ├── __init__.py
│   │   └── qa_generation.py        # System instructions, injection defense boundary, and prompt templates
│   ├── repositories/
│   │   ├── __init__.py
│   │   ├── document_repository.py  # Data access layer for relational document snapshots & selections
│   │   ├── json_test_suite_store.py# Atomic filesystem document store with flock concurrency
│   │   ├── mongo_test_suite_store.py# Decoupled MongoDB document store integration
│   │   └── test_suite_store.py     # Document store abstraction and factory
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── api.py                  # Pydantic schemas for API requests, responses, staleness & impact
│   │   ├── document.py             # Pydantic schemas for extracted document trees
│   │   └── qa_test_case.py         # Strict Pydantic models for QA test cases, suites & provenance
│   └── services/
│       ├── __init__.py
│       ├── document_ingestion.py   # Atomic transactional ingestion service
│       ├── impact_analyzer.py      # Selection-centric and document-wide impact analysis engine
│       ├── llm_provider.py         # BaseLLMProvider, OpenAICompatibleProvider, and MockLLMProvider
│       ├── pdf_parser.py           # Core deterministic PDF hierarchy extraction engine
│       ├── qa_generation_service.py# Grounded QA test case generation, validation retry loop & staleness
│       ├── staleness_classifier.py # Rule-based explainable staleness classification engine
│       └── version_matcher.py      # Multi-signal cross-version lineage matching engine
├── data/
│   ├── ct200_manual.pdf            # CT-200 v1 technical manual (6 pages)
│   ├── ct200_manual_v2.pdf         # CT-200 v2 technical manual (7 pages)
│   └── IMPORTANT_ASSIGNMENT_UPDATE (Read to check MD).txt
├── docs/
│   ├── stage-1-analysis.md         # Stage 1 repository audit and dataset analysis
│   ├── stage-2-parser.md           # Stage 2 parser architecture and edge case handling
│   ├── stage-3-versioning.md       # Stage 3 relational schema, lineage matching & API reference
│   ├── stage-4-selections-staleness.md # Stage 4 selections, staleness classification & impact analysis
│   └── stage-5-qa-generation.md    # Stage 5 QA generation, validation, persistence & test staleness
├── scripts/
│   ├── __init__.py
│   ├── demo_e2e_qa_generation.py   # Stage 5 13-step QA generation and test staleness demonstration
│   ├── demo_e2e_staleness.py       # Stage 4 11-step selection staleness & impact demonstration
│   ├── demo_e2e_versioning.py      # Stage 3 end-to-end versioning demonstration script
│   ├── ingest_document.py          # CLI tool for ingesting manuals and viewing version summaries
│   └── inspect_manual.py           # Standalone PDF diagnostic inspector
├── tests/
│   ├── __init__.py
│   ├── test_api.py                 # Base API endpoint tests
│   ├── test_impact_and_selection_api.py # Selection CRUD, staleness, and impact API integration tests
│   ├── test_parser_edge_cases.py   # Dedicated tests for all 7 confirmed structural edge cases
│   ├── test_pdf_parser.py          # Core parser extraction and table tests
│   ├── test_qa_generation.py       # Stage 5 QA generation, schemas, providers, retries & staleness tests
│   ├── test_selections.py          # Selection models, repository methods, and immutability tests
│   ├── test_staleness_classifier.py# Unit tests for staleness rules, deltas, and precedence
│   ├── test_versioning_and_ingestion.py # DB schema, ingestion, idempotency & lineage tests
│   └── test_versioning_api.py      # Persistent browse, search & diff endpoint tests
├── .env.example                    # Environment configuration template
├── .gitignore                      # Git exclusion rules
├── pytest.ini                      # Pytest configuration
├── README.md                       # Project documentation
└── requirements.txt                # Project dependencies
```

---

## Setup & Execution

### 1. Prerequisites & Installation
```bash
git clone https://github.com/ibharath-ofcl/Tri9T-AI.git
cd Tri9T-AI

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Run the Full Automated Test Suite (76 Tests)
Executes all regression tests for Stages 2 through 6 (PDF extraction, edge cases, versioning, selections, staleness classifier, QA generation, and grounding audit):
```bash
pytest -v
```

### 3. Run the Stage 6 Final Acceptance Demonstration (Recommended for Reviewers)
Executes the comprehensive 14-step workflow on authentic CT-200 v1/v2 PDFs in isolated, disposable storage:
```bash
python3 -m scripts.final_acceptance_demo
```

### 4. Optional: Run Prior Stage Demonstration Scripts
```bash
# Stage 5 QA Generation & Staleness Demo:
python3 -m scripts.demo_e2e_qa_generation

# Stage 4 Selection & Impact Demo:
python3 -m scripts.demo_e2e_staleness
```

### 5. Launch the FastAPI Server
```bash
uvicorn app.main:app --reload --port 8000
```
- **Interactive Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc:** [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Telemetry:** [http://localhost:8000/health](http://localhost:8000/health)
