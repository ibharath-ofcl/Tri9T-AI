# Tri9T AI Document Intelligence & QA Generation — API Reference

This reference documents the complete REST API interface implemented across Stages 2–6.
All endpoints run on FastAPI and provide automatic interactive documentation at:
- **Swagger UI**: `http://localhost:8000/docs`
- **ReDoc**: `http://localhost:8000/redoc`
- **OpenAPI JSON**: `http://localhost:8000/openapi.json`

---

## 1. System Health

### `GET /health`
Returns system liveness, active parser version, database status, and LLM provider configuration.

#### Response Example
```json
{
  "status": "healthy",
  "app_name": "Tri9T Medical Device Document Intelligence & QA Generator",
  "version": "0.6.0",
  "parser_version": "0.2.0",
  "database": "sqlite",
  "document_store": "json",
  "llm_provider": "mock"
}
```

---

## 2. Ingestion & Version Management

### `POST /api/v1/documents/ingest`
Ingests a technical manual PDF into the relational store, builds the document hierarchy AST, hashes all nodes, and matches logical lineage across revisions.

#### Request (Multipart Form)
- `file`: `ct200_manual.pdf` (binary PDF)
- `version_label`: `v1` (string, e.g. `v1`, `v2`)

#### Response Example
```json
{
  "document_id": "<document_uuid>",
  "version_id": "<version_uuid>",
  "version_label": "v1",
  "page_count": 6,
  "total_nodes": 27,
  "sha256": "4307a01c80...",
  "status": "SUCCESS"
}
```

### `GET /api/v1/documents`
Lists all ingested documents and their available immutable revisions.

#### Response Example
```json
[
  {
    "id": "<document_uuid>",
    "title": "CardioTrack CT-200 Technical Manual",
    "versions": [
      { "id": "<version_v1_uuid>", "version_label": "v1", "page_count": 6, "total_nodes": 27 },
      { "id": "<version_v2_uuid>", "version_label": "v2", "page_count": 7, "total_nodes": 28 }
    ]
  }
]
```

### `GET /api/v1/documents/{document_id}/sections`
Retrieves the hierarchical section tree for a specific document version.

#### Query Parameters
- `version_label`: Version label (`v1` or `v2`, defaults to `v1`).

---

## 3. Section Detail, Search & Diff

### `GET /api/v1/nodes/{node_version_id}`
Retrieves full snapshot details for an immutable section node, including heading, body text, tables, level, page range, and content hashes.

#### Response Example
```json
{
  "id": "<node_version_uuid>",
  "logical_node_id": "<logical_node_uuid>",
  "section_number": "2.1.1.1",
  "heading": "Battery Life Specifications",
  "level": 3,
  "page_start": 2,
  "page_end": 2,
  "content_hash": "dec9f4eebc56...",
  "body_text": "The internal battery operates for approximately 300 measurement cycles...",
  "tables": []
}
```

### `GET /api/v1/documents/{document_id}/search`
Searches extracted text within a version-isolated scope.

#### Query Parameters
- `q`: Search keyword (e.g. `inflation`, `battery`, `deflate`)
- `version_label`: Version label (e.g. `v1`, `v2`)

### `GET /api/v1/documents/{document_id}/diff`
Computes structural, numerical, and textual differences between two document revisions.

#### Query Parameters
- `base_version`: Base revision (e.g. `v1`)
- `target_version`: Target revision (e.g. `v2`)

#### Response Example
```json
{
  "document_id": "<document_uuid>",
  "base_version": "v1",
  "target_version": "v2",
  "summary": {
    "unchanged_nodes": 23,
    "modified_nodes": 4,
    "added_nodes": 1,
    "removed_nodes": 0
  },
  "changes": [
    {
      "section_number": "2.1.1.1",
      "change_type": "MODIFIED",
      "category": "NUMERIC_CHANGE",
      "explanation": "Numerical value modified from 300 measurement cycles to 250 measurement cycles."
    }
  ]
}
```

---

## 4. Version-Pinned Named Selections

### `POST /api/v1/selections`
Creates a named selection pinned to an exact document version. Selection nodes are strictly validated to belong to the pinned version.

#### Request Body
```json
{
  "document_id": "<document_uuid>",
  "document_version_id": "<version_v1_uuid>",
  "name": "Safety Critical Operations Selection",
  "description": "Pinned to v1 battery and pressure control requirements",
  "node_version_ids": [
    "<node_battery_uuid>",
    "<node_inflation_uuid>",
    "<node_errors_uuid>"
  ]
}
```

### `GET /api/v1/selections/{selection_id}`
Retrieves a named selection with its pinned version and selected node versions.

### `GET /api/v1/selections/{selection_id}/staleness`
Evaluates staleness of all selected nodes against a newer revision (e.g., `v2`).

#### Query Parameters
- `target_version_label`: `v2`

#### Response Example
```json
{
  "selection_id": "<selection_uuid>",
  "pinned_version_label": "v1",
  "target_version_label": "v2",
  "aggregate_status": "STALE",
  "summary": { "total": 3, "current": 0, "stale": 3 },
  "node_evaluations": [
    {
      "section_number": "2.1.1.1",
      "status": "STALE",
      "category": "NUMERIC_CHANGE",
      "deltas": [
        { "delta_type": "NUMERIC", "old_value": "300", "new_value": "250", "unit": "cycles" },
        { "delta_type": "NUMERIC", "old_value": "15", "new_value": "10", "unit": "%" }
      ]
    }
  ]
}
```

---

## 5. Grounded QA Test Generation & Source-Grounding Audit

### `POST /api/v1/qa/generate`
Generates 3 to 5 structured, validated QA test cases from a version-pinned selection or single node snapshot, executes a deterministic source-grounding audit, and persists the suite atomically into the document store.

#### Request Body
```json
{
  "selection_id": "<selection_uuid>",
  "requested_count": 4,
  "idempotency_key": "user-request-key-001"
}
```

#### Response Example (with Stage 6 Grounding Audit)
```json
{
  "generation_id": "<generation_uuid>",
  "selection_id": "<selection_uuid>",
  "document_id": "<document_uuid>",
  "document_version_id": "<version_v1_uuid>",
  "document_version_label": "v1",
  "requested_count": 4,
  "generated_count": 4,
  "provider_name": "mock",
  "model_name": "deterministic-mock-v1",
  "validation_status": "VALIDATED",
  "human_review_required": false,
  "grounding_summary": {
    "total_claims_audited": 27,
    "source_supported_claims": 21,
    "derived_claims": 0,
    "proposed_setup_claims": 6,
    "unsupported_claims": 0,
    "ambiguous_claims": 0,
    "human_review_required": false
  },
  "test_cases": [
    {
      "TestCaseId": "TC-BAT-001",
      "Title": "Verify Battery Low-Charge Threshold Icon Display",
      "Prerequisites": [
        "CT-200 blood pressure monitor installed with 4 fresh AA alkaline batteries",
        "[PROPOSED SETUP] Digital programmable DC power supply connected"
      ],
      "Steps": [
        "1. Connect power supply simulating nominal battery voltage (6.0 V DC).",
        "2. Decrease simulated voltage to 15% remaining capacity.",
        "3. Observe LCD display status indicator."
      ],
      "ExpectedResult": "The device displays a low-battery icon once remaining capacity falls below 15%.",
      "PassFailCriteria": "PASS if low-battery indicator appears at 15%; FAIL otherwise.",
      "StandardRef": "CT-200 Manual Section 2.1.1.1 Battery Life Under Typical Use",
      "CoverageTags": ["battery", "power", "display"],
      "HumanReviewRequired": false,
      "Provenance": {
        "source_node_version_id": "<node_battery_uuid>",
        "source_content_hash": "dec9f4eebc56...",
        "source_logical_node_id": "<logical_battery_uuid>",
        "source_document_version_id": "<version_v1_uuid>",
        "source_document_version_label": "v1",
        "section_number": "2.1.1.1",
        "heading": "2.1.1.1 Battery Life Under Typical Use",
        "page_start": 2,
        "page_end": 2
      },
      "GroundingAudit": {
        "test_case_id": "TC-BAT-001",
        "overall_grounding_status": "PROPOSED_SETUP_PRESENT",
        "claims_count": 3,
        "source_supported_count": 2,
        "derived_count": 0,
        "proposed_setup_count": 1,
        "unsupported_count": 0,
        "ambiguous_count": 0,
        "human_review_required": false
      }
    }
  ]
}
```

### `GET /api/v1/qa/suites/{generation_id}`
Retrieves a previously generated and persisted test suite by its generation UUID.

### `GET /api/v1/qa/suites`
Lists persisted test suites with optional filtering.

#### Query Parameters
- `selection_id`: Filter by parent selection UUID
- `node_version_id`: Filter by referenced source node snapshot UUID

### `GET /api/v1/qa/suites/{generation_id}/staleness`
Evaluates cross-version staleness and specification deltas of a persisted test suite against a newer manual revision.

#### Query Parameters
- `target_version_label`: Version to compare against (e.g. `v2`)

#### Response Example
```json
{
  "generation_id": "<generation_uuid>",
  "pinned_version_label": "v1",
  "target_version_label": "v2",
  "aggregate_status": "IMPACTED",
  "summary": { "total": 4, "current": 0, "stale": 4, "source_removed": 0, "source_moved": 0, "ambiguous": 0 },
  "human_review_required": true,
  "test_case_assessments": [
    {
      "test_case_id": "TC-BAT-001",
      "status": "STALE",
      "classification": "NUMERIC_CHANGE",
      "source_section_number": "2.1.1.1",
      "explanation": "Source requirements changed: Numerical value modified from 300 measurement cycles to 250 measurement cycles.; Numerical value modified from 15 % to 10 %.",
      "deltas": [
        { "delta_type": "NUMERIC", "old_value": "300", "new_value": "250", "unit": "cycles" },
        { "delta_type": "NUMERIC", "old_value": "15", "new_value": "10", "unit": "%" }
      ]
    }
  ]
}
```

### `GET /api/v1/documents/{document_id}/qa-impact`
Performs document-wide impact analysis across all generated QA test suites for a revision upgrade.

#### Query Parameters
- `from_version_label`: `v1`
- `to_version_label`: `v2`
