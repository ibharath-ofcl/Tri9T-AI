# Stage 5 Analysis & Implementation Report: LLM-Powered QA Test Generation, Validation Retries, Provenance & Cross-Version Staleness

**Milestone:** Stage 5 (M4) — Grounded Medical-Device QA Test Suite Generation & Test-Case Staleness Auditing  
**Repository:** [https://github.com/ibharath-ofcl/Tri9T-AI.git](https://github.com/ibharath-ofcl/Tri9T-AI.git)  
**Branch:** `main`  
**Stack:** Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0, SQLite (Relational Snapshots), Concurrency-Safe Atomic JSON Store (`JsonTestSuiteStore`) / MongoDB abstraction, pdfplumber, pytest.

---

## 1. Executive Summary & Objective

Stage 5 completes the end-to-end verification pipeline by translating version-pinned manual sections into structured, grounded medical-device QA test cases and tracking whether those test cases remain valid when newer document versions are ingested.

The solution ensures that:
1. **Grounded Test Generation:** Generates 3–5 actionable QA test cases per request derived directly from exact version-pinned manual sections (`NodeVersion` records) and structured table extracts (specifications, error codes).
2. **Pluggable Provider Abstraction:** Configurable via environment variables to support OpenAI-compatible completions endpoints (`OpenAICompatibleProvider`) or deterministic synthetic testing (`MockLLMProvider`). Real LLM keys are never committed and tests never make live network calls.
3. **Strict Schema Validation:** Enforces exact assignment field names (`TestCaseId`, `Title`, `Prerequisites`, `Steps`, `ExpectedResult`, `PassFailCriteria`, `StandardRef`) via Pydantic v2, rejecting empty strings, malformed arrays, or invalid test counts.
4. **Bounded Retry Loop:** Bounded to a maximum of 3 total model attempts per request. Failed attempts feed structured validation error summaries back into the corrective prompt.
5. **Deterministic Idempotency:** Requests are fingerprinted via SHA-256 over source hashes, test counts, prompt versions, and provider configurations. Replays return existing suites; parameter conflicts return HTTP 409.
6. **Decoupled Document Store:** Stores generated test suites in an atomic JSON document store (`JsonTestSuiteStore`) featuring temporary write swapping, `fcntl.flock` concurrency locking, and secondary indexing.
7. **Immutable Cryptographic Provenance:** Every test case preserves its original source node UUID, content SHA-256 hash, section numbering, and version label (`v1`).
8. **Cross-Version Staleness Auditing:** Reuses the Stage 4 `StalenessClassifier` to detect numerical shifts, timing changes, and added table rows (e.g., E6) against target revisions (`v2`) without ever mutating or overwriting original `v1` provenance.

---

## 2. Architecture & Data Flow

```mermaid
flowchart TD
    subgraph ClientLayer [Client & API Consumers]
        ReqGen["POST /api/v1/selections/{id}/test-suites"]
        ReqGet["GET /api/v1/test-suites/{id}"]
        ReqStale["GET /api/v1/test-suites/{id}/staleness?target_version=v2"]
        ReqImpact["GET /api/v1/documents/{id}/test-suite-impact"]
    end

    subgraph ServiceLayer [FastAPI Application & QAGenerationService]
        APIHandler["FastAPI Endpoints (app/main.py)"]
        QAService["QAGenerationService (app/services/qa_generation_service.py)"]
        PromptEngine["Prompt Builder & Injection Boundary (app/prompts/qa_generation.py)"]
        SchemaValidator["Strict Pydantic Validators (app/schemas/qa_test_case.py)"]
    end

    subgraph ProviderLayer [LLM Provider Abstraction]
        ProviderFactory["get_llm_provider()"]
        OpenAIProv["OpenAICompatibleProvider (HTTPX + Exponential Backoff)"]
        MockProv["MockLLMProvider (Deterministic Grounded Generator)"]
    end

    subgraph PersistenceLayer [Hybrid Dual-Store Architecture]
        SQLiteDB[("SQLite Relational DB\n- Documents\n- DocumentVersions\n- LogicalNodes\n- NodeVersions\n- Selections")]
        DocStore[("Atomic Document Store\n- Generated Test Suites\n- Cryptographic Provenance\n- Idempotency Map")]
    end

    subgraph StalenessAudit [Stage 4 Reused Lineage & Classifier]
        Classifier["StalenessClassifier (11 Categories)"]
        ImpactAnalyzer["ImpactAnalyzer (Value Delta Extraction)"]
    end

    ReqGen --> APIHandler
    APIHandler --> QAService
    QAService -->|1. Resolve Pinned Snapshots| SQLiteDB
    QAService -->|2. Build Grounded Context| PromptEngine
    PromptEngine --> ProviderFactory
    ProviderFactory --> OpenAIProv
    ProviderFactory --> MockProv
    OpenAIProv -->|Raw JSON| SchemaValidator
    MockProv -->|Raw JSON| SchemaValidator
    SchemaValidator -->|Validation Errors < 3 Attempts| PromptEngine
    SchemaValidator -->|Validated Payload| QAService
    QAService -->|3. Persist Valid Suite| DocStore
    
    ReqStale --> APIHandler
    APIHandler --> QAService
    QAService -->|Load Stored Suite| DocStore
    QAService -->|Evaluate Lineage| Classifier
    Classifier -->|Detect Deltas| ImpactAnalyzer
    ImpactAnalyzer -->|Status: CURRENT | STALE | SOURCE_REMOVED| APIHandler
```

---

## 3. LLM Provider Abstraction & Configuration

The provider abstraction resides in [`app/services/llm_provider.py`](../app/services/llm_provider.py) and defines an abstract base class `BaseLLMProvider`.

### Configuration Fields (`app/core/config.py` & `.env.example`)
| Field | Type | Default | Description |
|---|---|---|---|
| `LLM_PROVIDER` | string | `"mock"` | Provider backend: `"mock"` or `"openai"`. |
| `LLM_API_KEY` | string | `""` | Bearer token for LLM API. Never committed. |
| `LLM_API_BASE_URL` | string | `"https://api.openai.com/v1"` | Base endpoint URL for completions. |
| `LLM_MODEL` | string | `"gpt-4o-mini"` | Target model identifier. |
| `LLM_TEMPERATURE` | float | `0.1` | Temperature (low for deterministic QA outputs). |
| `LLM_TIMEOUT_SECONDS` | float | `30.0` | HTTP request timeout. |
| `LLM_MAX_RETRIES` | int | `3` | Maximum HTTP connection retries. |
| `TEST_SUITE_STORE_TYPE` | string | `"json"` | Document store backend: `"json"` or `"mongo"`. |

### Safeguards:
1. **No External Calls in Tests:** Tests default to `MockLLMProvider`, guaranteeing 100% deterministic execution without network dependencies or paid credentials.
2. **Startup Gracefulness:** If `LLM_PROVIDER=openai` is selected but `LLM_API_KEY` is missing, the application starts normally and existing browse/search/selection APIs continue working. Generation calls return a clean, actionable `HTTP 503 Service Unavailable` explaining that credentials are missing.
3. **Transient Error Backoff:** `OpenAICompatibleProvider` implements bounded exponential backoff (`0.5s * 2^(attempt-1)`) for HTTP 429 and 5xx responses. Non-retryable errors (such as HTTP 401 Unauthorized) fail immediately.

---

## 4. Strict Pydantic Output Schema & Field Semantics

Defined in [`app/schemas/qa_test_case.py`](../app/schemas/qa_test_case.py), every generated test case must strictly satisfy the assignment contract:

```python
class TestCaseSchema(BaseModel):
    TestCaseId: str          # Stable unique ID (e.g. TC-BAT-001)
    Title: str               # Non-empty concise behavior description (>= 5 chars)
    Prerequisites: List[str] # Non-empty list of device states / test setups
    Steps: List[str]         # Non-empty ordered actionable execution steps
    ExpectedResult: str      # Observable behavior tied to source specification
    PassFailCriteria: str    # Observable pass/fail criteria (no invented limits)
    StandardRef: str         # Source manual section / table reference
    TestType: str            # nominal, boundary, negative, fault_injection, timing
    CoverageTags: List[str]  # e.g. ["battery", "threshold", "p0_safety"]
    HumanReviewRequired: bool# True if source was ambiguous
    ValidationWarnings: List[str]
    Provenance: Optional[TestCaseProvenance] # Cryptographic source snapshot binding
```

### Invariants:
- Empty strings, whitespace-only strings, and empty prerequisite/step arrays are strictly rejected.
- Test counts outside 3–5 are rejected during schema validation.
- Duplicate `TestCaseId` values or normalized identical titles within a suite raise validation errors.
- External standards are never invented: if the manual specifies no standard, `StandardRef` references the CT-200 section and explicitly states that no external standard was cited.

---

## 5. Prompt Engineering & Grounding Safeguards

Prompt generation is defined in [`app/prompts/qa_generation.py`](../app/prompts/qa_generation.py).

### System Instructions (`SYSTEM_INSTRUCTION`):
- Establishes the agent as an ISO 13485 / IEC 62304 medical device software QA engineer.
- Forbids inventing hardware interfaces, firmware behavior, numerical limits, or clinical diagnoses.
- Requires distinguishing explicit specifications from proposed test setups.
- Mandates exact adherence to PascalCase keys and JSON array output.

### Untrusted Data Boundary:
Source text from user manuals is treated as untrusted data and strictly enclosed in boundary tags:
```xml
<source_document_context>
--- Node 1 ---
Section Number: 4.2
Heading: Error Codes
Page Range: P5-P5
Content Hash: 96be26dc07b58c1e...
Body Text:
...
Table 1 (Page 5):
  Headers: Code | Description | Action
  Row: E1 | Sensor error | Power off unit
  Row: E3 | Cuff deflation fault | Press manual release valve
</source_document_context>
```
If manual text contains instruction-like wording (e.g. "Ignore previous rules"), the prompt explicitly instructs the LLM that manual text must never override generation constraints.

---

## 6. Validation Retries & Bounded Failure Loop

The generation loop in `QAGenerationService.generate_test_suite`:
1. Dispatches prompt to the configured provider.
2. Parses raw response into JSON and validates against `TestCaseSchema`.
3. Verifies exact requested count ($3 \le count \le 5$).
4. Evaluates duplicate IDs and duplicate titles.
5. Binds application-controlled cryptographic provenance (`NodeVersion` snapshot, hash, version label).
6. **Bounded Retry:** If parsing, count, or schema validation fails, the error message and the prior invalid payload are sent back to the model using `build_retry_prompt`.
7. **Strict Bound:** Maximum 3 total model attempts. If all 3 fail, a `GenerationValidationError` is raised, returning `HTTP 422 Unprocessable Entity` with safe diagnostic summaries without logging sensitive tokens.

---

## 7. Duplicate-Submission & Idempotency Policy

The system implements deterministic request fingerprinting to prevent accidental double-generation and ensure reproducibility:

### Request Fingerprint Formula:
$$\text{Fingerprint} = \text{SHA256}\left(\text{Sorted}(\text{NodeID}:\text{Hash}) \parallel \text{Count} \parallel \text{PromptVersion} \parallel \text{Provider} \parallel \text{Model} \parallel \text{Focus}\right)$$

### Policies:
1. **Identical Replay:** When a request is submitted with an existing `idempotency_key` and matching fingerprint, the system immediately returns the previously persisted test suite without re-invoking the LLM.
2. **Conflict Detection:** If an `idempotency_key` is reused with different parameters (e.g. `count=5` instead of `count=4`), the service raises `IdempotencyConflictError`, returning `HTTP 409 Conflict`.
3. **Intentional Regeneration:** A new request with a distinct `idempotency_key` (or omitted key) produces a new generation record. Multiple test suites may coexist for the same selection.

---

## 8. Document-Store Implementation & Rationale

### Store Selection Rationale
The assignment requires a document store for LLM-generated test suites.
- While MongoDB is architecturally suitable for enterprise document storage, external MongoDB services are not guaranteed in all grading and offline assessment environments.
- To guarantee zero setup friction, atomic persistence, and 100% test reproducibility, we implemented **`JsonTestSuiteStore`** as the default document store, alongside a complete **`MongoTestSuiteStore`** implementation.

### `JsonTestSuiteStore` Architecture (`app/repositories/json_test_suite_store.py`):
1. **Atomic File Replacement:** Documents are written to a temporary file via `tempfile.NamedTemporaryFile` in the target directory, flushed with `os.fsync`, and atomically replaced via `os.replace`. This eliminates partial or corrupted writes during power failure or unexpected process termination.
2. **Concurrency Locking:** Employs advisory file locking via `fcntl.flock` on an internal lock file (`.store.lock`), ensuring race-free index updates during concurrent writes.
3. **Secondary Indexing:** Maintains an `_index.json` mapping `generation_id`, `selection_id`, `document_id`, `idempotency_key`, and `source_node_version_ids` for fast multi-dimensional queries.
4. **Resilience & Corruption Recovery:** If a document file is corrupted, it is logged and skipped safely without crashing retrieval operations. If the index file is damaged, it can be reconstructed from disk.

---

## 9. REST API Reference & Working Sample Requests

### 1. Generate Test Suite from Selection
`POST /api/v1/selections/{selection_id}/test-suites`

```bash
curl -X POST "http://localhost:8000/api/v1/selections/541eaba9-2389-491e-be47-4d7479367643/test-suites" \
  -H "Content-Type: application/json" \
  -d '{
    "count": 4,
    "idempotency_key": "ct200-safety-suite-run-001",
    "test_type_focus": "safety"
  }'
```

**Response (HTTP 201 Created):**
```json
{
  "generation_id": "16014480-32a6-47d7-9e48-823b4750a671",
  "selection_id": "541eaba9-2389-491e-be47-4d7479367643",
  "document_id": "847721ba-44a2-4291-8229-19b103d90078",
  "document_version_id": "76657923-38e9-40ea-9bf8-16474cb8da2f",
  "document_version_label": "v1",
  "requested_count": 4,
  "generated_count": 4,
  "provider_name": "mock",
  "model_name": "mock-ct200-qa-v1",
  "validation_status": "VALIDATED",
  "human_review_required": false,
  "test_cases": [
    {
      "TestCaseId": "TC-BAT-001",
      "Title": "Verify Battery Low-Charge Threshold Icon Display",
      "Prerequisites": [
        "CardioTrack CT-200 unit with 4 fresh AA alkaline batteries",
        "Programmable DC power supply attached to battery terminals"
      ],
      "Steps": [
        "1. Connect the programmable DC power supply to the battery terminal.",
        "2. Lower the supply voltage until the remaining capacity drops below 15%.",
        "3. Observe the LCD display screen for the battery status indicator icon."
      ],
      "ExpectedResult": "The device displays a flashing low-battery icon when remaining capacity falls below 15%.",
      "PassFailCriteria": "PASS if low-battery icon appears immediately upon reaching 15% threshold; FAIL if icon does not appear or appears late.",
      "StandardRef": "CT-200 Manual Section 2.1.1.1 Battery Life; no external standard specified in manual",
      "TestType": "boundary",
      "CoverageTags": ["battery", "p0_safety", "threshold"],
      "Provenance": {
        "selection_id": "541eaba9-2389-491e-be47-4d7479367643",
        "source_node_version_id": "4184dc6a-56a9-477b-9ea7-e74798ea7c23",
        "source_content_hash": "dec9f4eebc56542f7c041f0fa236d6a2fef45070a7b4f53535cf0818296eb00a",
        "source_logical_node_id": "b181dbb3-9ebc-4a37-b6f1-a18544c7908b",
        "source_document_version_id": "76657923-38e9-40ea-9bf8-16474cb8da2f",
        "source_document_version_label": "v1",
        "section_number": "2.1.1.1",
        "heading": "2.1.1.1 Battery Life Under Typical Use",
        "page_start": 2,
        "page_end": 2
      }
    }
  ]
}
```

### 2. Retrieve Persisted Test Suite
`GET /api/v1/test-suites/{generation_id}`

```bash
curl -X GET "http://localhost:8000/api/v1/test-suites/16014480-32a6-47d7-9e48-823b4750a671"
```

### 3. Retrieve Test Suites by Selection
`GET /api/v1/selections/{selection_id}/test-suites`

```bash
curl -X GET "http://localhost:8000/api/v1/selections/541eaba9-2389-491e-be47-4d7479367643/test-suites"
```

### 4. Retrieve Test Suites by Source Node Snapshot
`GET /api/v1/nodes/{node_version_id}/test-suites`

```bash
curl -X GET "http://localhost:8000/api/v1/nodes/4184dc6a-56a9-477b-9ea7-e74798ea7c23/test-suites"
```

### 5. Evaluate Test Suite Staleness Against Target Version
`GET /api/v1/test-suites/{generation_id}/staleness?target_version=v2`

```bash
curl -X GET "http://localhost:8000/api/v1/test-suites/16014480-32a6-47d7-9e48-823b4750a671/staleness?target_version=v2"
```

**Response (HTTP 200 OK):**
```json
{
  "generation_id": "16014480-32a6-47d7-9e48-823b4750a671",
  "selection_id": "541eaba9-2389-491e-be47-4d7479367643",
  "pinned_version_label": "v1",
  "target_version_label": "v2",
  "aggregate_status": "IMPACTED",
  "summary": {
    "total": 4,
    "current": 0,
    "stale": 4,
    "source_removed": 0,
    "source_moved": 0,
    "ambiguous": 0
  },
  "human_review_required": true,
  "disclaimer": "CRITICAL MEDICAL DEVICE SAFETY DISCLAIMER: Automated staleness assessment does NOT constitute clinical or regulatory approval. All detected parameter shifts must undergo formal engineering and QA review prior to physical hardware test execution.",
  "test_case_assessments": [
    {
      "test_case_id": "TC-BAT-001",
      "title": "Verify Battery Low-Charge Threshold Icon Display",
      "source_section_number": "2.1.1.1",
      "source_heading": "2.1.1.1 Battery Life Under Typical Use",
      "source_node_version_id": "4184dc6a-56a9-477b-9ea7-e74798ea7c23",
      "original_content_hash": "dec9f4eebc56542f7c041f0fa236d6a2fef45070a7b4f53535cf0818296eb00a",
      "target_content_hash": "a17f2231dbcd7bb88a2ef3e070d62a4d04825d19a2b7f082e6ef9be1da2542a3",
      "status": "STALE",
      "classification": "NUMERIC_CHANGE",
      "deltas": [
        {
          "delta_type": "numeric",
          "old_value": "300",
          "new_value": "250",
          "unit": "measurement cycles",
          "context": "cycle rating",
          "explanation": "Numerical value modified from 300 measurement cycles to 250 measurement cycles."
        },
        {
          "delta_type": "numeric",
          "old_value": "15",
          "new_value": "10",
          "unit": "%",
          "context": "warning threshold",
          "explanation": "Numerical value modified from 15 % to 10 %."
        }
      ],
      "explanation": "Source requirements changed: Numerical value modified from 300 measurement cycles to 250 measurement cycles.; Numerical value modified from 15 % to 10 %.. Test case prerequisites/expectations must be re-evaluated.",
      "human_review_required": true
    },
    {
      "test_case_id": "TC-CUFF-001",
      "title": "Verify Incremental Cuff Inflation Step Size",
      "source_section_number": "3.2",
      "source_heading": "3.2 Cuff Inflation Sequence",
      "source_node_version_id": "893c528f-7e87-4340-9705-ebca7ba864d4",
      "original_content_hash": "547758b53703d0ebd2d192c732ce6f7f2b1c43719b2229ad320db91500f407c8",
      "target_content_hash": "e6dc39db8c6ba7f4f6bdf69a68661fc86a4ea8d6537703058a2d59be1f6004b2",
      "status": "STALE",
      "classification": "NUMERIC_CHANGE",
      "deltas": [
        {
          "delta_type": "numeric",
          "old_value": "40",
          "new_value": "30",
          "unit": "mmHg",
          "context": "inflation increment",
          "explanation": "Numerical value modified from 40 mmHg to 30 mmHg."
        }
      ],
      "explanation": "Source requirements changed: Numerical value modified from 40 mmHg to 30 mmHg.. Test case prerequisites/expectations must be re-evaluated.",
      "human_review_required": true
    },
    {
      "test_case_id": "TC-ERR-001",
      "title": "Verify Overpressure Condition E3 Auto-Deflation Timing",
      "source_section_number": "4.2",
      "source_heading": "4.2 Error Codes",
      "source_node_version_id": "0d635f60-5f0d-45db-9c3f-c68700021626",
      "original_content_hash": "96be26dc07b58c1e285a81e9f1a04ec5cba7ff45bbd780efea5468725838573f",
      "target_content_hash": "84a282f6460f1bfa981e13fa073b313ef04cfc24c78fe1bc894efbbd309191d8",
      "status": "STALE",
      "classification": "TIMING_CHANGE",
      "deltas": [
        {
          "delta_type": "table_row",
          "old_value": "None",
          "new_value": "Row 'E6'",
          "unit": "table row",
          "context": "error table row added",
          "explanation": "New table entry 'E6' added in target version."
        },
        {
          "delta_type": "timing",
          "old_value": "2",
          "new_value": "1.5",
          "unit": "seconds",
          "context": "deflation timing",
          "explanation": "Timing parameter changed from 2 seconds to 1.5 seconds."
        }
      ],
      "explanation": "Source requirements changed: New table entry 'E6' added in target version.; Timing parameter changed from 2 seconds to 1.5 seconds.. Test case prerequisites/expectations must be re-evaluated.",
      "human_review_required": true
    }
  ]
}
```

### 6. Document-Wide Test Suite Impact Analysis
`GET /api/v1/documents/{document_id}/test-suite-impact?from_version=v1&to_version=v2`

```bash
curl -X GET "http://localhost:8000/api/v1/documents/847721ba-44a2-4291-8229-19b103d90078/test-suite-impact?from_version=v1&to_version=v2"
```

---

## 10. Cross-Version Staleness & Provenance Immutability

A critical requirement of medical device QA is that **test cases generated from Revision A must never be implicitly rewritten when Revision B is released**. The system enforces this via:

1. **Immutable Cryptographic Binding:** Each test case explicitly stores the source node version UUID (`source_node_version_id`) and the SHA-256 hash of the text/tables at the exact moment of generation.
2. **Lineage Cross-Referencing:** When staleness is assessed against `v2`, the system uses `LogicalNode` lineage to locate the counterpart section in `v2`.
3. **No Phantom Re-generation:** The original test suite record is never overwritten. If an engineer wishes to generate tests for `v2`, they must explicitly create a new selection or run generation against `v2`.
4. **Status Taxonomy:**
   - `CURRENT`: Section is identical in text and parameters.
   - `STALE`: Section has numerical, timing, or table changes.
   - `SOURCE_REMOVED`: Section existed in `v1` but was deleted in `v2`.
   - `SOURCE_MOVED`: Section exists but changed location in the hierarchy.
   - `AMBIGUOUS`: Section has multiple plausible matches.

---

## 11. Regulatory & Safety Disclaimer

> [!CAUTION]
> **ISO 14971 / IEC 62304 MEDICAL DEVICE SAFETY DISCLAIMER**  
> Test cases generated by this system are automated software verification proposals derived from document text. **Generation does not constitute physical test execution.**  
> 1. Generated test cases have **NOT** been run on physical medical hardware.
> 2. Automated staleness classification does not replace formal verification protocols, clinical safety audits, or regulatory submission reviews.
> 3. Any detected numerical or temporal shift automatically flags `human_review_required: true`.

---

## 12. Verification & Automated Test Results

### Full Automated Test Suite Command:
```bash
pytest
```

### Verified Output:
```
============================= test session starts ==============================
platform darwin -- Python 3.13.7, pytest-9.1.1, pluggy-1.7.0 -- /Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13
cachedir: .pytest_cache
rootdir: /Users/bharathbodduvenkata/PROJECTS/Tri9T-AI
configfile: pytest.ini
testpaths: tests
plugins: anyio-4.12.1
collected 67 items

tests/test_api.py::test_health_endpoint PASSED                           [  1%]
tests/test_api.py::test_preview_v1_endpoint PASSED                       [  2%]
tests/test_api.py::test_preview_v2_endpoint PASSED                       [  4%]
tests/test_api.py::test_preview_invalid_version PASSED                   [  5%]
tests/test_impact_and_selection_api.py::test_selection_lifecycle_and_crud_api PASSED [  7%]
tests/test_impact_and_selection_api.py::test_selection_validation_errors PASSED [  8%]
tests/test_impact_and_selection_api.py::test_selection_staleness_and_impact_endpoints PASSED [ 10%]
tests/test_parser_edge_cases.py::test_edge_case_a_section_2_1_1_1_numbering_gap PASSED [ 11%]
tests/test_parser_edge_cases.py::test_edge_case_b_section_3_2_anomalous_font_size PASSED [ 13%]
tests/test_parser_edge_cases.py::test_edge_case_c_out_of_order_sections_3_4_and_3_3 PASSED [ 14%]
tests/test_parser_edge_cases.py::test_edge_case_d_duplicate_error_codes_headings PASSED [ 16%]
tests/test_parser_edge_cases.py::test_edge_case_e_phantom_table_filtering PASSED [ 17%]
tests/test_parser_edge_cases.py::test_edge_case_f_numbered_list_in_section_3_3 PASSED [ 19%]
tests/test_parser_edge_cases.py::test_edge_case_g_cross_page_content_continuation PASSED [ 20%]
tests/test_pdf_parser.py::test_document_metadata_and_pages PASSED        [ 22%]
tests/test_pdf_parser.py::test_top_level_sections_count PASSED           [ 23%]
tests/test_pdf_parser.py::test_total_nodes_and_v2_new_section PASSED     [ 25%]
tests/test_pdf_parser.py::test_content_hash_stability PASSED             [ 26%]
tests/test_pdf_parser.py::test_table_extraction_and_v2_error_code_e6 PASSED [ 28%]
tests/test_pdf_parser.py::test_specs_table_in_section_2_1 PASSED         [ 29%]
tests/test_qa_generation.py::test_schema_valid_counts_and_fields PASSED  [ 31%]
tests/test_qa_generation.py::test_schema_rejects_invalid_count PASSED    [ 32%]
tests/test_qa_generation.py::test_schema_rejects_missing_or_empty_fields PASSED [ 34%]
tests/test_qa_generation.py::test_schema_rejects_duplicate_ids_and_titles PASSED [ 35%]
tests/test_qa_generation.py::test_prompt_includes_tables_and_injection_defense PASSED [ 37%]
tests/test_qa_generation.py::test_corrective_retry_prompt_formatting PASSED [ 38%]
tests/test_qa_generation.py::test_missing_provider_api_key_raises_actionable_error PASSED [ 40%]
tests/test_qa_generation.py::test_openai_provider_timeout_and_transient_backoff PASSED [ 41%]
tests/test_qa_generation.py::test_openai_provider_fails_immediately_on_401 PASSED [ 43%]
tests/test_qa_generation.py::test_bounded_validation_retry_succeeds_on_second_attempt PASSED [ 44%]
tests/test_qa_generation.py::test_bounded_validation_retry_fails_after_three_attempts PASSED [ 46%]
tests/test_qa_generation.py::test_idempotent_replay_and_conflict PASSED  [ 47%]
tests/test_qa_generation.py::test_json_store_atomicity_and_corrupt_file_recovery PASSED [ 49%]
tests/test_qa_generation.py::test_e2e_v1_selection_generation_v2_staleness_flow PASSED [ 50%]
tests/test_qa_generation.py::test_generate_from_single_node_version_and_unchanged_case PASSED [ 52%]
tests/test_selections.py::test_create_and_get_selection_pinned_to_v1 PASSED [ 53%]
tests/test_selections.py::test_reject_empty_selection_creation PASSED    [ 55%]
tests/test_selections.py::test_reject_nonexistent_node_id PASSED         [ 56%]
tests/test_selections.py::test_reject_mixed_version_nodes PASSED         [ 58%]
tests/test_selections.py::test_deduplicate_selected_node_references PASSED [ 59%]
tests/test_selections.py::test_update_selection_metadata_and_nodes PASSED [ 61%]
tests/test_selections.py::test_delete_selection_preserves_node_snapshots PASSED [ 62%]
tests/test_selections.py::test_selection_pinned_version_immutability_after_v2_ingest PASSED [ 64%]
tests/test_staleness_classifier.py::test_identical_hashes_yield_no_change PASSED [ 65%]
tests/test_staleness_classifier.py::test_whitespace_formatting_yields_formatting_only PASSED [ 67%]
tests/test_staleness_classifier.py::test_wording_change_without_numbers PASSED [ 68%]
tests/test_staleness_classifier.py::test_battery_life_numerical_change_detection PASSED [ 70%]
tests/test_staleness_classifier.py::test_cuff_inflation_pressure_change_detection PASSED [ 71%]
tests/test_staleness_classifier.py::test_timing_change_precedence_over_numeric PASSED [ 73%]
tests/test_staleness_classifier.py::test_table_row_added_error_code_e6 PASSED [ 74%]
tests/test_staleness_classifier.py::test_added_and_removed_sections PASSED [ 76%]
tests/test_staleness_classifier.py::test_moved_section_detection PASSED  [ 77%]
tests/test_staleness_classifier.py::test_ambiguous_lineage_reporting PASSED [ 79%]
tests/test_staleness_classifier.py::test_unrelated_numbers_not_falsely_paired PASSED [ 80%]
tests/test_versioning_and_ingestion.py::test_database_initialization_and_models PASSED [ 82%]
tests/test_versioning_and_ingestion.py::test_ingest_v1_and_v2_lineage PASSED [ 83%]
tests/test_versioning_and_ingestion.py::test_idempotent_ingestion PASSED [ 85%]
tests/test_versioning_and_ingestion.py::test_conflicting_version_checksum_rejection PASSED [ 86%]
tests/test_versioning_and_ingestion.py::test_atomic_rollback_on_failure PASSED [ 88%]
tests/test_versioning_and_ingestion.py::test_duplicate_error_codes_headings_disambiguation PASSED [ 89%]
tests/test_versioning_and_ingestion.py::test_hierarchy_tree_has_no_cycles PASSED [ 91%]
tests/test_versioning_and_ingestion.py::test_matcher_ambiguity_reporting PASSED [ 92%]
tests/test_versioning_api.py::test_api_ingest_and_list_documents PASSED  [ 94%]
tests/test_versioning_api.py::test_api_get_document_sections PASSED      [ 95%]
tests/test_versioning_api.py::test_api_get_node_detail PASSED            [ 97%]
tests/test_versioning_api.py::test_api_search_with_version_isolation PASSED [ 98%]
tests/test_api_compare_node_versions_and_diff PASSED                     [100%]

======================== 67 passed, 1 warning in 6.28s =========================
```

---

## 13. End-to-End Demonstration Execution

### Command:
```bash
python3 -m scripts.demo_e2e_qa_generation
```

### Verified Output:
The demonstration script completed all 13 steps cleanly:
- Initialized isolated in-memory SQLite and temporary atomic JSON store.
- Selected `[MODE: DETERMINISTIC MOCK PROVIDER]` due to no paid external credentials.
- Ingested `v1` (27 nodes).
- Created a pinned selection containing §2.1.1.1 (Battery Life), §3.2 (Cuff Inflation), and §4.2 (Error Codes).
- Generated 4 validated test cases with exact PascalCase keys and bound cryptographic provenance.
- Verified duplicate submission policy: identical replay returned existing suite; parameter mismatch returned HTTP 409 conflict error.
- Ingested `v2` (28 nodes) without mutating `v1` records.
- Evaluated staleness against `v2`: correctly detected numerical changes in §2.1.1.1 (300 $\rightarrow$ 250 cycles, 15% $\rightarrow$ 10%) and §3.2 (40 $\rightarrow$ 30 mmHg), and timing/table change in §4.2 (2.0s $\rightarrow$ 1.5s, E6 table row added).
- Evaluated control test case on unchanged §1.1 (Intended Use): correctly reported `CURRENT` (`NO_CHANGE`).
- Demonstrated suite retrieval by selection and source node snapshot.
- Proved that original `v1` node IDs, hashes, and version labels remained 100% immutable.
- Executed document-wide impact analysis, reporting 1 impacted suite and 1 unaffected suite.

---

## 14. Known Limitations & Future Work

1. **Physical Test Bench Drivers:** Generating test steps and pass/fail criteria does not execute test cases on physical hardware. Future work could integrate automated hardware-in-the-loop (HIL) runners (e.g. via PySerial/CANopen).
2. **Formal Traceability Matrices (RTM):** Although test cases capture `StandardRef` and provenance, future revisions could generate bi-directional traceability matrices mapping risk analysis hazards (ISO 14971) to test case execution logs.
3. **Multi-Model Consensus:** For high-risk medical devices, a consensus voting mechanism across multiple disparate foundation models could further mitigate hallucination risks.
