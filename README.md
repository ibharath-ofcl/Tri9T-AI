# Tri9T-AI: CT-200 Medical Device Document Intelligence

A high-reliability Document Intelligence and Medical Device QA Traceability Engine built for the CardioTrack CT-200 Blood Pressure Monitor technical manuals.

Developed for the **Tri9T AI Internship Assignment**.

---

## Current Status: Milestone M0 + Stage 2 Parser Foundation

- **Stage 1 (Audit & Inspection):** Complete — documented in [`docs/stage-1-analysis.md`](docs/stage-1-analysis.md).
- **Stage 2 (PDF Extraction & Hierarchy Engine):** Complete — documented in [`docs/stage-2-parser.md`](docs/stage-2-parser.md).
- **Test Suite:** 17/17 tests passing across extraction, edge cases, and API preview endpoints.

---

## Key Features Implemented

1. **Deterministic PDF Extraction Engine (`app/services/pdf_parser.py`):**
   - High-fidelity typography extraction using `pdfplumber`.
   - Multi-pass line aggregation with character-level font metadata (`size`, `fontname`, `bold`).
   - Clean digital PDF parsing without lossy OCR overhead or stochastic LLM hallucination.

2. **Explicit Handling of All 7 Confirmed Structural Irregularities:**
   - **IR-1 (Missing 2.1.1 Parent):** Section `2.1.1.1` cleanly attached to `2.1` with diagnostic warning.
   - **IR-2 (Body-Sized Heading Font):** Section `3.2` correctly recognized as Level-2 heading despite 11.0pt font.
   - **IR-3 (Out-of-Order Sections):** Sections `3.4` and `3.3` preserved in exact source reading order with sequence warning.
   - **IR-4 (Duplicate Heading Names):** Sections `4.2` and `7.1` ("Error Codes") receive unique occurrence IDs and respective parent trees.
   - **IR-5 (Phantom Table Filtering):** Geometric enclosure and sparsity filtering discard cell-internal phantoms while retaining genuine specification and error code tables.
   - **IR-6 (Numbered Lists in 3.3):** Blood pressure classification items 1–5 preserved as body text and not mistaken for section headings.
   - **IR-7 (Cross-Page Content Continuation):** Seamlessly joins multi-page section text (e.g. 3.1 across p2–p3, 8.1 in v2 across p6–p7).

3. **Deterministic Cryptographic Content Hashing:**
   - SHA-256 computed for `heading_hash`, `body_hash` (including structured table content), and combined `content_hash`.
   - Normalization preserves medical numeric thresholds, units (`mmHg`, `bpm`, `%`, `seconds`), and clinical symbols (`±`, `<`, `>`, `≤`, `≥`).

4. **FastAPI Development Preview Endpoint (`app/main.py`):**
   - `GET /health` — Service readiness and manual asset verification.
   - `GET /api/v1/documents/preview?version=v1` (or `v2`) — Full hierarchy tree, node metadata, and diagnostics.
   - Strict version whitelisting preventing arbitrary path traversal.

---

## Project Structure

```
Tri9T-AI/
├── app/
│   ├── __init__.py
│   ├── main.py                  # FastAPI application with /health and /preview
│   ├── core/
│   │   ├── __init__.py
│   │   └── config.py            # Pydantic Settings and file path configuration
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── document.py          # Pydantic schemas (DocumentTree, DocumentNode, TableData)
│   └── services/
│       ├── __init__.py
│       └── pdf_parser.py        # Core deterministic PDF hierarchy extraction engine
├── data/
│   ├── ct200_manual.pdf         # CT-200 v1 technical manual (6 pages)
│   ├── ct200_manual_v2.pdf      # CT-200 v2 technical manual (7 pages)
│   └── IMPORTANT_ASSIGNMENT_UPDATE (Read to check MD).txt
├── docs/
│   ├── stage-1-analysis.md      # Comprehensive Stage 1 repository audit and dataset analysis
│   └── stage-2-parser.md        # Parser architecture, typography rules, and edge case guide
├── scripts/
│   ├── __init__.py
│   └── inspect_manual.py        # Standalone PDF diagnostic and typography inspector
├── tests/
│   ├── __init__.py
│   ├── test_api.py              # FastAPI endpoint integration tests
│   ├── test_parser_edge_cases.py# Dedicated tests for all 7 confirmed structural edge cases
│   └── test_pdf_parser.py       # Core parser metadata, table, and hash stability tests
├── .env.example                 # Environment configuration template
├── .gitignore                   # Git exclusion rules
├── pytest.ini                   # Pytest configuration
├── README.md                    # Project documentation
└── requirements.txt             # Project dependencies
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

### 1. Run the Diagnostic PDF Inspector
Inspect page metrics, typography breakdown, and candidate tables:
```bash
# Inspect v1 manual
python -m scripts.inspect_manual data/ct200_manual.pdf

# Inspect v2 manual
python -m scripts.inspect_manual data/ct200_manual_v2.pdf
```

### 2. Run the Automated Test Suite
Execute the 17 unit and integration tests:
```bash
pytest tests/
```

### 3. Launch the FastAPI Development Server
```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```
- **Health Check:** [http://localhost:8000/health](http://localhost:8000/health)
- **v1 Hierarchy Preview:** [http://localhost:8000/api/v1/documents/preview?version=v1](http://localhost:8000/api/v1/documents/preview?version=v1)
- **v2 Hierarchy Preview:** [http://localhost:8000/api/v1/documents/preview?version=v2](http://localhost:8000/api/v1/documents/preview?version=v2)
- **Interactive Swagger Docs:** [http://localhost:8000/docs](http://localhost:8000/docs)

---

## Upcoming Implementation Scope (Stages 3–5)

- **Stage 3:** SQLite database schema and SQLAlchemy ORM models for versioned document trees, logical node identities, and version-pinned selections.
- **Stage 4:** Cross-version comparison, structural diffing, and automated staleness classification.
- **Stage 5:** Validated LLM test case generation with Pydantic validation, bounded retries, and MongoDB persistence.
