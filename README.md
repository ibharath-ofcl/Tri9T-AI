# Tri9T-AI: CT-200 Medical Device Document Intelligence

A high-reliability Document Intelligence, Document Versioning, and Medical Device QA Traceability Engine built for the CardioTrack CT-200 Blood Pressure Monitor technical manuals.

Developed for the **Tri9T AI Internship Assignment**.

---

## Current Status: Milestone M3 (Stage 4 Complete)

- **Stage 1 (Audit & Inspection):** Complete — documented in [`docs/stage-1-analysis.md`](docs/stage-1-analysis.md).
- **Stage 2 (PDF Extraction & Deterministic Engine):** Complete — documented in [`docs/stage-2-parser.md`](docs/stage-2-parser.md).
- **Stage 3 (Relational Versioning, Database & Lineage):** Complete — documented in [`docs/stage-3-versioning.md`](docs/stage-3-versioning.md).
- **Stage 4 (Version-Pinned Selections, Staleness & Impact Detection):** Complete — documented in [`docs/stage-4-selections-staleness.md`](docs/stage-4-selections-staleness.md).
- **Automated Test Suite:** **52/52 tests passing** across PDF parsing, 7 structural edge cases, relational persistence, version lineage matching, named selections, staleness rules, and REST APIs.

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

### 6. Revision Impact Analysis (`app/services/impact_analyzer.py`)
- **Selection-Centric Impact:** Evaluates an individual pinned selection against target version v2, reporting affected nodes and deltas.
- **Document-Centric Impact:** Evaluates all selections across the entire document, partitioning them into impacted, review-required, and unaffected categories.

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

---

## Project Structure

```
Tri9T-AI/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application with persistence, search, diff, selections & impact
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py               # Application settings and database URLs
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py                 # SQLAlchemy DeclarativeBase
│   │   ├── models.py               # Models: Document, DocumentVersion, LogicalNode, NodeVersion, Selection, SelectionNode
│   │   └── session.py              # Engine, sessionmaker, and SQLite FK pragma
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── document_repository.py  # Data access layer for documents, versions, nodes, search & selections
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── api.py                  # Pydantic schemas for API requests, responses, staleness & impact
│   │   └── document.py             # Pydantic schemas for extracted document trees
│   └── services/
│       ├── __init__.py
│       ├── document_ingestion.py   # Atomic transactional ingestion service
│       ├── impact_analyzer.py      # Selection-centric and document-wide impact analysis engine
│       ├── pdf_parser.py           # Core deterministic PDF hierarchy extraction engine
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
│   └── stage-4-selections-staleness.md # Stage 4 selections, staleness classification & impact analysis
├── scripts/
│   ├── __init__.py
│   ├── demo_e2e_staleness.py       # Automated 11-step Stage 4 staleness & impact demonstration
│   ├── demo_e2e_versioning.py      # Stage 3 end-to-end versioning demonstration script
│   ├── ingest_document.py          # CLI tool for ingesting manuals and viewing version summaries
│   └── inspect_manual.py           # Standalone PDF diagnostic inspector
├── tests/
│   ├── __init__.py
│   ├── test_api.py                 # Base API endpoint tests
│   ├── test_impact_and_selection_api.py # Selection CRUD, staleness, and impact API integration tests
│   ├── test_parser_edge_cases.py   # Dedicated tests for all 7 confirmed structural edge cases
│   ├── test_pdf_parser.py          # Core parser extraction and table tests
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

### 2. Run the Stage 4 End-to-End Demonstration Script
Demonstrates v1 ingestion, selection creation, v2 migration, numerical/timing delta detection, unchanged selection verification, and document-wide impact analysis:
```bash
python3 -m scripts.demo_e2e_staleness
```

### 3. Run the Automated Test Suite (52 Tests)
```bash
pytest
```

### 4. Launch the FastAPI Server
```bash
uvicorn app.main:app --reload --port 8000
```
- **Interactive Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Telemetry:** [http://localhost:8000/health](http://localhost:8000/health)

---

## Upcoming Stage 5 Scope

- **Validated LLM QA Generation:** Generating 3–5 structured test-case specifications per node/selection.
- **Pydantic Structured Output Validation:** Enforcing strict schema compliance with bounded retries.
- **Document Store Persistence:** MongoDB or structured JSON persistence linking generated test cases directly to immutable source node hashes.
- **Cross-Version Test Staleness:** Automatically retrieving and flagging stale test cases when underlying requirements change.
