# Requirements Traceability Matrix (RTM)

**Project:** CardioTrack CT-200 Medical Device Document Intelligence and QA Test Generation  
**Target Repository:** `https://github.com/ibharath-ofcl/Tri9T-AI.git`  
**Branch:** `main`  
**Evaluation Date:** 2026-10-23  

---

## 1. Traceability Methodology

Every core requirement of the Tri9T AI assignment is mapped bidirectionally across:
1. **Requirement / Capability**: The stated specification or functional invariant.
2. **Implementation Module**: The concrete Python module and class implementing the logic.
3. **API / Script Interface**: The REST endpoint or CLI runner exposing the capability.
4. **Verification Evidence**: Automated test case, red-team vector, or execution command.
5. **Status**: `PASS`, `PARTIAL`, `FAIL`, or `NOT VERIFIED`.
6. **Documented Limitations**: Transparent statement of boundaries or assumptions.

---

## 2. Comprehensive Traceability Matrix

| # | Requirement / Capability | Implementation Module | API / Script Interface | Automated Test / Verification Evidence | Status | Documented Limitation |
| :---: | :--- | :--- | :--- | :--- | :---: | :--- |
| **1** | **PDF Extraction** | `app/services/pdf_parser.py` (`CT200PDFParser`) | `POST /api/v1/documents/ingest`, `scripts/evaluator_demo.py` Step 2 & 3 | `tests/test_pdf_parser.py::test_document_metadata_and_pages` (PASS) | `PASS` | Tailored to digital CT-200 typography; does not perform OCR on scanned images. |
| **2** | **Hierarchy Reconstruction** | `app/services/pdf_parser.py` | `GET /api/v1/documents/{id}/sections` | `tests/test_pdf_parser.py::test_top_level_sections_count` (PASS) | `PASS` | 6 hierarchy levels supported (`DEVICE`, `SECTION`, `SUBSECTION`, `SUBSUBSECTION`, `PARAGRAPH`, `TABLE_ROW`). |
| **3** | **Structural Irregularities Handling** | `app/services/pdf_parser.py` (IR-1 to IR-7 logic) | `tests/test_parser_edge_cases.py` | `tests/test_parser_edge_cases.py` (7/7 tests passing) | `PASS` | Deterministically handles confirmed edge cases; new edge cases would require rule updates. |
| **4** | **Immutable Versioned Snapshots** | `app/db/models.py`, `app/services/document_ingestion.py` | `POST /api/v1/documents/ingest` | `tests/test_versioning_and_ingestion.py::test_ingest_v1_and_v2_lineage` (PASS) | `PASS` | Once ingested, `NodeVersion` rows are read-only; re-ingestion returns HTTP 409 or idempotent replay. |
| **5** | **Cross-Version Change Detection** | `app/services/version_matcher.py` | `GET /api/v1/nodes/{id}/changes` | `tests/test_versioning_api.py::test_api_compare_node_versions_and_diff` (PASS) | `PASS` | Multi-signal matching on title + section number + hierarchy position. |
| **6** | **Named Selections & Version Pinning** | `app/db/models.py`, `app/repositories/document_repository.py` | `POST /api/v1/selections`, `GET /api/v1/selections/{id}` | `tests/test_selections.py::test_create_and_get_selection_pinned_to_v1` (PASS) | `PASS` | Selection cannot span multiple document versions; deleting selection leaves node snapshots intact. |
| **7** | **Structured QA Test Generation** | `app/services/qa_generation_service.py` | `POST /api/v1/selections/{id}/test-suites` | `tests/test_qa_generation.py::test_schema_valid_counts_and_fields` (PASS) | `PASS` | Generates 3–5 structured test cases validating PascalCase Pydantic model (`TestCaseSchema`). |
| **8** | **5-State Grounding Categories** | `app/schemas/qa_test_case.py`, `app/services/grounding_auditor.py` | `POST /api/v1/selections/{id}/test-suites` | `tests/test_grounding_audit.py::test_suite_grounding_summary_aggregation` (PASS) | `PASS` | Classifies claims into `SUPPORTED`, `DERIVED`, `SETUP`, `UNSUPPORTED`, and `AMBIGUOUS`. |
| **9** | **Unsupported Claim Detection** | `app/services/grounding_auditor.py` | `scripts/evaluator_demo.py` Step 11 | `tests/test_grounding_red_team.py` (14/14 tests passing) | `PASS` | Flags invented tolerances (±2 mmHg), ungrounded thresholds, and invented error codes. |
| **10** | **Cryptographic Provenance Verification** | `app/services/grounding_auditor.py`, `app/schemas/qa_test_case.py` | `scripts/evaluator_demo.py` Step 9 | `test_grounding_red_team.py::test_case_11_missing_or_tampered_provenance` (PASS) | `PASS` | Binds `source_node_version_id`, `source_content_hash`, and section numbers; catches hash drift. |
| **11** | **Human-Review Gate Handling** | `app/services/grounding_auditor.py`, `app/services/staleness_classifier.py` | `GET /api/v1/selections/{id}/staleness` | `test_grounding_red_team.py::test_case_02_unsupported_tolerance` (PASS) | `PASS` | Automatically sets `human_review_required: true` on any ungrounded claim or parameter delta. |
| **12** | **Idempotency & Retry Limits** | `app/services/qa_generation_service.py` | `POST /api/v1/selections/{id}/test-suites` | `tests/test_qa_generation.py::test_idempotent_replay_and_conflict` (PASS) | `PASS` | Bounded to max 3 attempts; replaying key returns identical suite; altered params raise HTTP 409. |
| **13** | **Document Store Persistence** | `app/repositories/json_test_suite_store.py` | `GET /api/v1/test-suites/{generation_id}` | `tests/test_persistence.py` (11/11 tests passing) | `PASS` | Atomic file write (`.tmp` write + `os.replace`) with `fcntl.flock` concurrency locking. |
| **14** | **Staleness & Impact Analysis** | `app/services/staleness_classifier.py`, `app/services/impact_analyzer.py` | `GET /api/v1/selections/{id}/staleness`, `GET /api/v1/documents/{id}/impact` | `tests/test_staleness_classifier.py` (8/8 tests passing) | `PASS` | 11 granular classifications (`NUMERIC_CHANGE`, `TIMING_CHANGE`, `TABLE_ROW`); unchanged nodes stay `CURRENT`. |
| **15** | **API Contract Consistency** | `app/main.py` | `http://localhost:8000/docs`, OpenAPI 3.1.0 | `python3 -c "from app.main import app; assert len(app.openapi()['paths']) == 18"` (PASS) | `PASS` | 18 operational routes matching declared Pydantic schemas and documented status codes. |
| **16** | **Offline Reproducibility** | `requirements.txt`, `app/services/llm_provider.py` | `python3 -m scripts.stage7_final_verification` | Fresh environment execution without API tokens (PASS) | `PASS` | 100% offline self-contained runner; remote OpenAI and MongoDB are optional extensions. |

---

## 3. RTM Summary

- **Total Requirements Evaluated:** 16
- **PASS:** 16 (100%)
- **PARTIAL:** 0
- **FAIL:** 0
- **NOT VERIFIED:** 0

All 16 capabilities are directly verified by automated tests, runtime scripts, and inspected source implementations.
