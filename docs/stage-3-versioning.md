# Stage 3 — Persistent Document Versioning, Relational Data Layer & Node Lineage

**Project:** Tri9T AI Internship Assignment — CT-200 Medical Device Manual Document Intelligence  
**Component:** Relational Data Model, Versioning, Lineage Matcher & Search APIs  
**Status:** Stage 3 Complete  
**Date:** 2026-10-22  

---

## 1. Executive Summary

Stage 3 implements a production-grade relational persistence and lineage tracking architecture for the CardioTrack CT-200 technical manuals using SQLAlchemy and SQLite.

The fundamental engineering principle in this stage is the strict separation between:
1. **`LogicalNode` (Conceptual Section Identity):** Represents an enduring requirement or functional section across manual revisions (e.g., Section 3.2 "Cuff Inflation Sequence").
2. **`NodeVersion` (Immutable Occurrence):** Represents the exact textual, structural, tabular, and cryptographic state of a section within one specific document version (e.g., v1 with 40 mmHg inflation increments vs. v2 with 30 mmHg increments).

This design ensures that historical versions (v1) remain completely immutable, audit-trailed, and retrievable, while new revisions (v2) establish verified lineage without destructive in-place updates.

---

## 2. Relational Data Model & Entity Relationships

```
┌─────────────────────────────────────────────────────────────┐
│                          Document                           │
│  - id: UUID (PK)                                            │
│  - document_key: "CT-200" (Unique)                          │
│  - title: "CardioTrack CT-200 Manual"                       │
│  - created_at: Timestamp                                    │
│  - latest_version_id: UUID (FK -> DocumentVersion)          │
└──────────────────────┬───────────────────────────────┬──────┘
                       │ 1:N                           │ 1:N
                       ▼                               ▼
┌─────────────────────────────────┐   ┌────────────────────────────────┐
│         DocumentVersion         │   │          LogicalNode           │
│  - id: UUID (PK)                │   │  - id: UUID (PK)               │
│  - document_id: UUID (FK)       │   │  - document_id: UUID (FK)      │
│  - version_label: "v1" | "v2"   │   │  - canonical_section_number    │
│  - source_filename: "ct200..."  │   │  - canonical_heading           │
│  - source_sha256: Hash          │   │  - created_at: Timestamp       │
│  - page_count: 6 | 7            │   └───────────────┬────────────────┘
│  - total_nodes: 27 | 28         │                   │
│  - status: "SUCCESS"            │                   │ 1:N
│  - metadata_json / diagnostics  │                   │
└────────────────┬────────────────┘                   │
                 │ 1:N                                │
                 ▼                                    ▼
┌──────────────────────────────────────────────────────────────┐
│                         NodeVersion                          │
│  - id: UUID (PK)                                             │
│  - document_version_id: UUID (FK -> DocumentVersion)         │
│  - logical_node_id: UUID (FK -> LogicalNode)                 │
│  - parent_node_version_id: UUID (FK -> NodeVersion, self)    │
│  - heading: str                                              │
│  - section_number: str                                       │
│  - level: int                                                │
│  - body_text: text                                           │
│  - content_hash: SHA-256                                     │
│  - heading_hash / body_hash: SHA-256                         │
│  - page_start / page_end: int                                │
│  - source_order: int (1-indexed stream position)             │
│  - source_metadata_json: text (tables, layout metrics)       │
│  - diagnostics_json: text (warnings)                         │
└──────────────────────────────────────────────────────────────┘
```

### Key Relational Constraints
- **Unique Version Labels:** `UniqueConstraint("document_id", "version_label")` prevents accidental duplication of version labels.
- **Unique Logical Node per Version:** `UniqueConstraint("document_version_id", "logical_node_id")` ensures a conceptual section appears at most once in a given document revision.
- **Intra-Version Parent Referencing:** `parent_node_version_id` strictly references another `NodeVersion` within the same `document_version_id`, preventing cross-version graph entanglement.
- **Acyclic Hierarchy:** Trees are guaranteed cycle-free and resolve upward to Level-1 root sections.

---

## 3. Transactional Ingestion & Idempotency Guarantees

The ingestion service (`app/services/document_ingestion.py`) provides mission-critical guarantees for regulated software environments:

1. **Transactional Atomicity:**
   All document version records, logical nodes, node versions, and parent relationships are committed in a single atomic transaction. Any parsing or persistence exception immediately triggers `db.rollback()`, ensuring no partial trees or corrupted states are ever committed.
2. **Deterministic Idempotency:**
   If `ingest_version()` is called with a version label and source file whose SHA-256 checksum exactly matches an existing successful ingestion, the engine returns the existing record immediately (`is_idempotent_replay: True`) without creating duplicate records or altering existing node versions.
3. **Conflict Detection:**
   If a request attempts to ingest a manual under an existing version label (e.g. `v1`) with a different source checksum, the service raises `IngestionConflictError` (HTTP 409). Silent overwriting of historical revisions is strictly forbidden.
4. **Immutability of Historical Versions:**
   When ingesting `v2`, all `NodeVersion` records from `v1` remain untouched. New `NodeVersion` records are created for `v2`, referencing either existing `LogicalNode` IDs (for matched sections) or newly created `LogicalNode` IDs (for new sections like §5.3).

---

## 4. Multi-Signal Lineage Matching Engine (`app/services/version_matcher.py`)

### Matching Signals & Scoring

The engine resolves cross-version identity across 5 cascading passes:

| Pass | Signal | Criteria | Outcome |
|---|---|---|---|
| **Pass 1: Exact Structural Match** | Section Number + Ancestor Path | Exact match on `section_number` AND normalized heading similarity $\ge 0.50$ AND matching parent context | `UNCHANGED` (if content hash identical) or `MODIFIED` (if content hash differs). Retains `logical_node_id`. |
| **Pass 2: Moved / Relocated Sections** | Normalized Heading + Body Context | Normalized heading similarity $\ge 0.80$ with different parent | `MOVED` (or `MODIFIED_AND_MOVED`). Retains `logical_node_id`. |
| **Pass 3: Ambiguity Resolution** | Multi-Candidate Conflict | Top candidate score difference $< 0.10$ | `AMBIGUOUS`. Emits warning and leaves match unforced. |
| **Pass 4: Added Sections** | Unmatched New Sections | No defensible match in prior version (e.g. §5.3 Data Export) | `ADDED`. Generates brand new `logical_node_id`. |
| **Pass 5: Removed Sections** | Unmatched Prior Sections | Prior node has no corresponding section in new version | `REMOVED`. |

### Handling Special Structural Cases

1. **Duplicate Headings (§4.2 and §7.1 "Error Codes"):**
   Because the matcher evaluates the full structural path (`4. > 4.2` vs `7. > 7.1`), §4.2 in v2 strictly matches §4.2 in v1, and §7.1 in v2 strictly matches §7.1 in v1. They are never conflated.
2. **Out-of-Order Sections (§3.4 and §3.3):**
   Section numbering (`3.4` and `3.3`) acts as primary structural identity in Pass 1, ensuring §3.4 matches §3.4 and §3.3 matches §3.3 despite appearing out of numerical sequence in the PDF stream.
3. **Newly Added Section (§5.3 Data Export):**
   Recognized as `ADDED` with 1.0 confidence score and assigned a new `logical_node_id` that does not exist in v1.

---

## 5. Actual CT-200 v1 vs. v2 Ingestion and Lineage Statistics

Ingesting both official manuals against an empty database yields:

```
V1 Manual Ingestion:
  - Document ID : 9d4696be-302b-4cd9-b8da-89c55d778bbc
  - Version ID  : 4ca7cd2f-c911-423e-abe0-2090b06a1c76 (v1)
  - SHA-256     : 0504d713306e99e722d03cd763a0a743e9459bc2763dfd5d53dd6d0f7b18ea22
  - Page Count  : 6 pages
  - Total Nodes : 27 baseline nodes

V2 Manual Ingestion:
  - Version ID  : 795c07e1-9f09-4fcc-acfd-8cbb691266ec (v2)
  - SHA-256     : b0c7aa72f11c6a32fa305e9a1756c16dd5e538c637e1061d86c03bd02910444f
  - Page Count  : 7 pages
  - Total Nodes : 28 nodes

Lineage Match Classification Breakdown:
  - UNCHANGED   : 23 sections (Identical content hashes)
  - MODIFIED    : 4 sections:
      * §2.1.1.1 Battery Life (300 -> 250 cycles, 15% -> 10%)
      * §3.2 Cuff Inflation Sequence (40 -> 30 mmHg increment)
      * §4.2 Error Codes (E6 added, E3 auto-deflate 2s -> 1.5s)
      * §4.3 Alarm Thresholds (E1-E5 -> E1-E6)
  - ADDED       : 1 section:
      * §5.3 Data Export (Brand new conceptual section and logical identity)
  - REMOVED     : 0 sections
  - MOVED       : 0 sections
  - AMBIGUOUS   : 0 sections
```

---

## 6. API Reference and Usage

### Endpoint Summary

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/v1/documents/ingest?version=v1\|v2` | Ingests a manual revision atomically with lineage |
| `GET` | `/api/v1/documents` | Lists all documents and their ingested revisions |
| `GET` | `/api/v1/documents/{document_id}/sections?version=v1` | Retrieves the section hierarchy tree for a revision |
| `GET` | `/api/v1/nodes/{node_version_id}` | Fetches full immutable details, tables, and diagnostics |
| `GET` | `/api/v1/search?q=...&version=v1` | Cross-version search with text and table snippets |
| `GET` | `/api/v1/nodes/{logical_node_id}/changes?from_version=v1&to_version=v2` | Compares revisions of a conceptual section with unified diff |
| `GET` | `/health` | Service health and manual file availability |
| `GET` | `/api/v1/documents/preview?version=v1` | In-memory parser preview (Stage 2 preserved) |

### Sample Requests & Responses

#### 1. Ingest Document
```bash
curl -X POST "http://localhost:8000/api/v1/documents/ingest?version=v1"
```
```json
{
  "status": "success",
  "document_id": "9d4696be-302b-4cd9-b8da-89c55d778bbc",
  "version_id": "4ca7cd2f-c911-423e-abe0-2090b06a1c76",
  "version_label": "v1",
  "source_sha256": "0504d713306e99e722d03cd763a0a743e9459bc2763dfd5d53dd6d0f7b18ea22",
  "page_count": 6,
  "total_nodes": 27,
  "is_idempotent_replay": false,
  "match_summary": {"UNCHANGED": 0, "MODIFIED": 0, "ADDED": 27, "REMOVED": 0, "MOVED": 0, "AMBIGUOUS": 0},
  "diagnostics_count": 5,
  "message": "Successfully ingested v1 (27 nodes)."
}
```

#### 2. Cross-Version Section Diff
```bash
curl -s "http://localhost:8000/api/v1/nodes/64be6f9b-1784-4494-8914-a37d3b71627d/changes?from_version=v1&to_version=v2"
```
```json
{
  "logical_node_id": "64be6f9b-1784-4494-8914-a37d3b71627d",
  "canonical_section_number": "3.2",
  "canonical_heading": "3.2 Cuff Inflation Sequence",
  "change_classification": "MODIFIED",
  "is_content_changed": true,
  "from_version": {
    "exists": true,
    "version_label": "v1",
    "node_version_id": "1291a477-4811-48b1-8642-7d07f91f087e",
    "content_hash": "547758b53703d0eb47157789fd1da56c3a768cb98d19926eeca74eaaacbe5a6e",
    "page_range": "P3-P3"
  },
  "to_version": {
    "exists": true,
    "version_label": "v2",
    "node_version_id": "fdd4e4ef-4acf-4198-aa6b-0c7146e3ee75",
    "content_hash": "ad8e038d720a90c2ed0608d05540c15a06480a58db1aa5873a62fd2778e57c90",
    "page_range": "P3-P3"
  },
  "diff_summary": "--- v1:3.2\n+++ v2:3.2\n@@ -1 +1 @@\n-On starting a measurement, the device inflates the cuff to an initial target of 180 mmHg. If the user's pulse is not detected by 180 mmHg, the device inflates in 40 mmHg increments up to a maximum of 299 mmHg before aborting with an error. Deflation occurs in controlled steps of approximately 3 mmHg to capture oscillometric pulse data.\n+On starting a measurement, the device inflates the cuff to an initial target of 180 mmHg. If the user's pulse is not detected by 180 mmHg, the device inflates in 30 mmHg increments up to a maximum of 299 mmHg before aborting with an error. Deflation occurs in controlled steps of approximately 3 mmHg to capture oscillometric pulse data. Increment size was reduced from the original 40 mmHg to improve pulse-detection reliability in field testing."
}
```

---

## 7. Automated Test Suite Results

Test suite expanded from 17 to **30 automated tests**, all passing in **3.29 seconds**:

```
tests/test_api.py (4 tests)                                   PASSED
tests/test_parser_edge_cases.py (7 tests)                     PASSED
tests/test_pdf_parser.py (6 tests)                            PASSED
tests/test_versioning_and_ingestion.py (8 tests)              PASSED
tests/test_versioning_api.py (5 tests)                        PASSED

======================== 30 passed in 3.29s =========================
```

---

## 8. CLI Ingestion & Demonstration Tools

- **CLI Ingestion Tool:** `python -m scripts.ingest_document --version v1` (or `--version v2`, `--summary`)
- **End-to-End Demonstration:** `python -m scripts.demo_e2e_versioning`
