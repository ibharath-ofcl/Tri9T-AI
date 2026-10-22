# Tri9T-AI: CT-200 Medical Device Document Intelligence

A high-reliability Document Intelligence, Document Versioning, and Medical Device QA Traceability Engine built for the CardioTrack CT-200 Blood Pressure Monitor technical manuals.

Developed for the **Tri9T AI Internship Assignment**.

---

## Current Status: Milestone M2 (Stage 3 Complete)

- **Stage 1 (Audit & Inspection):** Complete — documented in [`docs/stage-1-analysis.md`](docs/stage-1-analysis.md).
- **Stage 2 (PDF Extraction & Deterministic Engine):** Complete — documented in [`docs/stage-2-parser.md`](docs/stage-2-parser.md).
- **Stage 3 (Relational Versioning, Database & Lineage):** Complete — documented in [`docs/stage-3-versioning.md`](docs/stage-3-versioning.md).
- **Automated Test Suite:** **30/30 tests passing** across extraction, edge cases, database persistence, lineage matching, and API endpoints.

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

### 3. Persistent Document Versioning & Relational Schema (`app/db/models.py`)
- **`Document`:** Conceptual identity of the medical device manual.
- **`DocumentVersion`:** Immutable snapshot of a specific revision (v1: 27 nodes, v2: 28 nodes).
- **`LogicalNode`:** Permanent cross-version conceptual section identity.
- **`NodeVersion`:** Version-specific occurrence storing body text, cryptographic hashes (`content_hash`, `heading_hash`, `body_hash`), source page range, table data, and diagnostics.
- **Foreign Key Constraints & SQLite Session Management:** SQLite foreign keys enforced via connection pragma.

### 4. Multi-Signal Cross-Version Lineage Matcher (`app/services/version_matcher.py`)
- Distinguishes **`UNCHANGED`** (23 nodes), **`MODIFIED`** (4 nodes: §2.1.1.1, §3.2, §4.2, §4.3), and **`ADDED`** (1 node: §5.3 Data Export).
- Evaluates full structural paths (`4. > 4.2` vs `7. > 7.1`) to prevent duplicate headings from crossing parents.
- Supports **`AMBIGUOUS`** classification for unforced candidate resolution.

### 5. Persistent REST API (`app/main.py`)
- `POST /api/v1/documents/ingest?version=v1|v2` — Transactional, idempotent ingestion.
- `GET /api/v1/documents` — Lists conceptual documents and ingested revisions.
- `GET /api/v1/documents/{document_id}/sections?version=v1` — Returns hierarchical section tree.
- `GET /api/v1/nodes/{node_version_id}` — Detailed node inspection with tables and provenance.
- `GET /api/v1/search?q=...&version=v1` — Cross-version search with text snippets.
- `GET /api/v1/nodes/{logical_node_id}/changes?from_version=v1&to_version=v2` — Unified diff comparison.
- `GET /health` & `GET /api/v1/documents/preview` — Health telemetry and in-memory development preview.

---

## Project Structure

```
Tri9T-AI/
├── app/
│   ├── __init__.py
│   ├── main.py                     # FastAPI application with persistence, search & diff endpoints
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py               # Application settings and database URLs
│   ├── db/
│   │   ├── __init__.py
│   │   ├── base.py                 # SQLAlchemy DeclarativeBase
│   │   ├── models.py               # Relational models: Document, DocumentVersion, LogicalNode, NodeVersion
│   │   └── session.py              # Engine, sessionmaker, and SQLite FK pragma
│   ├── repositories/
│   │   ├── __init__.py
│   │   └── document_repository.py  # Data access layer for documents, versions, nodes, and search
│   ├── schemas/
│   │   ├── __init__.py
│   │   ├── api.py                  # Pydantic schemas for API requests and responses
│   │   └── document.py             # Pydantic schemas for extracted document trees
│   └── services/
│       ├── __init__.py
│       ├── document_ingestion.py   # Atomic transactional ingestion service
│       ├── pdf_parser.py           # Core deterministic PDF hierarchy extraction engine
│       └── version_matcher.py      # Multi-signal cross-version lineage matching engine
├── data/
│   ├── ct200_manual.pdf            # CT-200 v1 technical manual (6 pages)
│   ├── ct200_manual_v2.pdf         # CT-200 v2 technical manual (7 pages)
│   └── IMPORTANT_ASSIGNMENT_UPDATE (Read to check MD).txt
├── docs/
│   ├── stage-1-analysis.md         # Stage 1 repository audit and dataset analysis
│   ├── stage-2-parser.md           # Stage 2 parser architecture and edge case handling
│   └── stage-3-versioning.md       # Stage 3 relational schema, lineage matching & API reference
├── scripts/
│   ├── __init__.py
│   ├── demo_e2e_versioning.py      # Automated 11-step end-to-end demonstration script
│   ├── ingest_document.py          # CLI tool for ingesting manuals and viewing version summaries
│   └── inspect_manual.py           # Standalone PDF diagnostic inspector
├── tests/
│   ├── __init__.py
│   ├── test_api.py                 # Base API endpoint tests
│   ├── test_parser_edge_cases.py   # Dedicated tests for all 7 confirmed structural edge cases
│   ├── test_pdf_parser.py          # Core parser extraction and table tests
│   ├── test_versioning_and_ingestion.py # DB schema, ingestion, idempotency & lineage tests
│   └── test_versioning_api.py      # Persistent browse, search & diff endpoint tests
├── .env.example                    # Environment configuration template
├── .gitignore                      # Git exclusion rules
├── pytest.ini                      # Pytest configuration
├── README.md                       # Project documentation
└── requirements.txt                # Project dependencies
```

---

## Setup & Installation

### 1. Prerequisites
- Python 3.11+ (tested on Python 3.13)
- `pip` package manager

### 2. Environment Setup
```bash
# Clone repository
git clone https://github.com/ibharath-ofcl/Tri9T-AI.git
cd Tri9T-AI

# Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install required dependencies
pip install -r requirements.txt
```

---

## Usage

### 1. Ingest Documents via CLI
```bash
# Ingest v1 manual
python -m scripts.ingest_document --version v1

# Ingest v2 manual (automatically matches lineage against v1)
python -m scripts.ingest_document --version v2

# View complete database inventory and cross-version lineage summary
python -m scripts.ingest_document --summary
```

### 2. Run the End-to-End Demonstration Script
```bash
python -m scripts.demo_e2e_versioning
```

### 3. Run the Automated Test Suite (30 Tests)
```bash
pytest tests/
```

### 4. Launch the FastAPI Server
```bash
uvicorn app.main:app --reload --port 8000
```
- **Interactive Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)
- **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)
- **List Ingested Revisions:** [http://localhost:8000/api/v1/documents](http://localhost:8000/api/v1/documents)
- **Search Across Versions:** [http://localhost:8000/api/v1/search?q=cuff&version=v1](http://localhost:8000/api/v1/search?q=cuff&version=v1)

---

## Upcoming Implementation Scope (Stages 4–5)

- **Stage 4:** Version-pinned named selections, full staleness detection algorithms, and QA impact assessment.
- **Stage 5:** Validated LLM test-case generation with Pydantic structured output, bounded retries, and MongoDB persistence.
