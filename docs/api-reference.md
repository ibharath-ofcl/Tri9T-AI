# Tri9T AI Document Intelligence & QA Generation — API Reference

This reference documents the complete REST API interface implemented across the CardioTrack CT-200 Document Intelligence system.
All endpoints run on FastAPI and provide automatic interactive documentation at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

---

## 1. System Endpoints

### `GET /health`
Returns system liveness, active environment, version label, and manual PDF asset presence.

#### Response Example (`200 OK`)
```json
{
  "status": "healthy",
  "app_name": "CardioTrack CT-200 Document Intelligence & QA Test Generator",
  "environment": "development",
  "version": "0.3.0",
  "assets_status": {
    "v1_manual_present": true,
    "v2_manual_present": true,
    "data_dir": "/path/to/data"
  }
}
```

---

## 2. Ingestion & Document Browsing

### `POST /api/v1/documents/ingest`
Atomically ingests a manual revision from `data/`, establishes cross-version node lineage, computes cryptographic SHA-256 hashes, and records immutable snapshots.

#### Query Parameters
- `version`: Version label to ingest (`v1` or `v2`, required).

#### Response Example (`200 OK`)
```json
{
  "status": "success",
  "document_id": "c0fcd1e6-a7f5-4b25-838e-9dab60f8853a",
  "version_id": "a327ba00-843a-4467-bc32-1b1e427142b7",
  "version_label": "v1",
  "source_sha256": "4b6da1553531a7c5c0d51ec12e84d4fa71ca2a818e974e1e0750fc901968593a",
  "page_count": 6,
  "total_nodes": 27,
  "is_idempotent_replay": false,
  "match_summary": {
    "total_nodes": 27,
    "matched_nodes": 0,
    "new_nodes": 27,
    "deleted_nodes": 0
  },
  "diagnostics_count": 0,
  "message": "Successfully ingested CardioTrack CT-200 Technical Manual version v1 (27 nodes across 6 pages)."
}
```

#### Error Responses
- `400 Bad Request`: Invalid version label parameter.
- `409 Conflict`: Attempting to re-ingest an already ingested version without force replay.

---

### `GET /api/v1/documents`
Lists all registered conceptual documents and all their ingested revisions.

#### Response Example (`200 OK`)
```json
[
  {
    "document_id": "c0fcd1e6-a7f5-4b25-838e-9dab60f8853a",
    "document_key": "ct200_manual",
    "title": "CardioTrack CT-200 Technical Manual",
    "latest_version_id": "3965b182-411a-4d2b-91cc-7182da91cf54",
    "versions": [
      {
        "version_id": "a327ba00-843a-4467-bc32-1b1e427142b7",
        "version_label": "v1",
        "source_filename": "ct200_manual.pdf",
        "source_sha256": "4b6da15535...",
        "page_count": 6,
        "total_nodes": 27,
        "ingested_at": "2026-10-23T01:00:00Z",
        "status": "INGESTED"
      }
    ]
  }
]
```

---

### `GET /api/v1/documents/{document_id}/sections`
Retrieves the hierarchical section tree for a specific document version.

#### Query Parameters
- `version`: Version label (`v1` or `v2`, default: `v1`).

---

### `GET /api/v1/nodes/{node_version_id}`
Retrieves full snapshot details for an immutable section node, including heading, body text, tables, level, page range, and content hashes.

#### Response Example (`200 OK`)
```json
{
  "node_version_id": "4dcdb9c2-5e67-4288-a764-f98b18ec4920",
  "logical_node_id": "8ad036df-b9a1-4328-971c-43df890a56fe",
  "document_version_id": "a327ba00-843a-4467-bc32-1b1e427142b7",
  "version_label": "v1",
  "heading": "4.2 Error Codes",
  "section_number": "4.2",
  "level": 2,
  "parent_node_version_id": "5fa23d11...",
  "body_text": "The CT-200 provides deterministic error code diagnostics in Table 4.1...",
  "content_hash": "96be26dc07b58c1ea817cfaee1a7a0b329c2ea55811c79a970e5b745ce9b61d2",
  "heading_hash": "3f98ba71...",
  "body_hash": "88a1cd22...",
  "page_start": 4,
  "page_end": 4,
  "source_order": 12,
  "tables": [],
  "diagnostics": [],
  "children": []
}
```

---

### `GET /api/v1/search`
Executes full-text keyword search across headings, bodies, and tables within an optional version filter.

#### Query Parameters
- `q`: Search query string (min length 1, required).
- `version`: Optional version filter (`v1` or `v2`).

---

### `GET /api/v1/nodes/{logical_node_id}/changes`
Compares an individual logical node across two document revisions and outputs unified diffs.

#### Query Parameters
- `from_version`: Base revision label (`v1`, default).
- `to_version`: Target revision label (`v2`, default).

---

## 3. Version-Pinned Named Selections

### `POST /api/v1/selections`
Creates a named selection pinned to an exact document version. Selection nodes are strictly validated to belong to the pinned version.

#### Request Body
```json
{
  "name": "CT200-Core-Safety-Critical-Suite",
  "description": "High-risk safety requirements: battery capacity, inflation pressure, error deflation.",
  "document_id": "c0fcd1e6-a7f5-4b25-838e-9dab60f8853a",
  "version_label": "v1",
  "node_version_ids": [
    "a2aec38a-cf21-4f08-b196-857c3da89ff0",
    "2a25c9aa-062e-4cb8-8f85-30bb622f9889",
    "4dcdb9c2-5e67-4288-a764-f98b18ec4920"
  ]
}
```

#### Response Example (`201 Created`)
```json
{
  "id": "b7f5a653-f728-4ef6-81cf-67f0b5d564fa",
  "document_id": "c0fcd1e6-a7f5-4b25-838e-9dab60f8853a",
  "document_version_id": "a327ba00-843a-4467-bc32-1b1e427142b7",
  "version_label": "v1",
  "name": "CT200-Core-Safety-Critical-Suite",
  "description": "High-risk safety requirements: battery capacity, inflation pressure, error deflation.",
  "created_at": "2026-10-23T01:00:00Z",
  "updated_at": "2026-10-23T01:00:00Z",
  "total_nodes": 3,
  "nodes": [...]
}
```

---

### `GET /api/v1/selections`
Lists all registered selections with optional filtering by document ID or version label.

---

### `GET /api/v1/selections/{selection_id}`
Retrieves selection details and all pinned node snapshots.

---

### `PATCH /api/v1/selections/{selection_id}`
Updates selection metadata or node membership within the pinned version. Cannot move the pinned version.

---

### `DELETE /api/v1/selections/{selection_id}`
Deletes a selection without modifying underlying document history or node snapshots.

---

### `GET /api/v1/selections/{selection_id}/staleness`
Evaluates selection staleness against a target version (e.g. `v2`), detecting numerical, timing, or structural shifts.

#### Query Parameters
- `target_version`: Version label to assess against (defaults to `v2`).

---

### `GET /api/v1/selections/{selection_id}/impact`
Partitions selection nodes into affected and unaffected sets when compared to a target version.

---

### `GET /api/v1/documents/{document_id}/impact`
Performs document-wide impact analysis across all pinned selections for a document.

---

## 4. Grounded QA Test Generation & Grounding Audit

### `POST /api/v1/selections/{selection_id}/test-suites`
Generates 3 to 5 structured QA test cases from a version-pinned selection, validates schema constraints, binds cryptographic provenance, and executes the deterministic source-grounding audit.

#### Query Parameters / Request Body
- `requested_count`: Number of test cases to generate (integer between 3 and 5, default: 3).
- `idempotency_key`: Optional client idempotency key to prevent duplicate executions.

#### Response Example (`201 Created`)
```json
{
  "generation_id": "9b62e229-411a-4288-971c-43df890a56fe",
  "selection_id": "b7f5a653-f728-4ef6-81cf-67f0b5d564fa",
  "document_id": "c0fcd1e6-a7f5-4b25-838e-9dab60f8853a",
  "document_version_id": "a327ba00-843a-4467-bc32-1b1e427142b7",
  "document_version_label": "v1",
  "requested_count": 4,
  "generated_count": 4,
  "provider_name": "mock",
  "model_name": "deterministic-mock-v1",
  "validation_status": "VALIDATED",
  "human_review_required": false,
  "grounding_summary": {
    "total_claims_audited": 33,
    "source_supported_claims": 27,
    "derived_claims": 0,
    "proposed_setup_claims": 6,
    "unsupported_claims": 0,
    "ambiguous_claims": 0,
    "human_review_required": false
  },
  "test_cases": [...]
}
```

#### Error Responses
- `400 Bad Request`: Requested count outside allowable 3–5 range.
- `404 Not Found`: Selection ID not found.
- `409 Conflict`: Re-using an existing idempotency key with different parameters.
- `422 Unprocessable Entity`: LLM output failed Pydantic validation after maximum retries.

---

### `POST /api/v1/nodes/{node_version_id}/test-suites`
Generates structured QA test cases from an individual node version snapshot.

---

### `GET /api/v1/test-suites/{generation_id}`
Retrieves a persisted test suite by generation UUID from the document store.

---

### `GET /api/v1/selections/{selection_id}/test-suites`
Lists all generated test suites for a specific selection.

---

### `GET /api/v1/nodes/{node_version_id}/test-suites`
Lists all test suites referencing an exact source node snapshot.

---

### `GET /api/v1/test-suites/{generation_id}/staleness`
Evaluates staleness of all test cases in a generated suite against a target document revision (e.g. `v2`).

#### Query Parameters
- `target_version`: Version label to assess against (default: `v2`).

---

### `GET /api/v1/documents/{document_id}/test-suite-impact`
Performs document-wide test suite impact analysis across all generated suites for a document.
