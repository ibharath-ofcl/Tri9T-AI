# Stage 6 Audit Plan & Verification Matrix

**Milestone:** Stage 6 — Final Integration, Grounding Audit, Acceptance Verification & Submission Readiness  
**Target Branch:** `main`  
**Base Commit:** `49715ab`  
**Date:** October 2026  

---

## 1. Objectives & Audit Scope

The goal of Stage 6 is to audit the entire Tri9T AI Document Intelligence and QA Generation system against the actual CT-200 v1 and v2 source manuals and project requirements.

### Key Audit Dimensions:
1. **Source Grounding of Generated QA Test Cases:** Audit every numeric value, unit, error code, timing claim, and prerequisite against actual parsed PDF text and tables. Distinguish `SOURCE_SUPPORTED`, `DERIVED_WITH_EXPLANATION`, `PROPOSED_SETUP`, `UNSUPPORTED`, and `AMBIGUOUS`.
2. **Parser & Irregularity Regression Audit:** Re-verify that Stage 2's deterministic parser handles all 7 structural irregularities (IR-1 to IR-7) without regressions.
3. **Relational Persistence & Version Lineage Audit:** Verify immutable node snapshots, checksum immutability, and version isolation in search/diff.
4. **Selection Pinning & Staleness Audit:** Verify that selections remain pinned to original document versions after v2 ingestion, with accurate delta explanations and no provenance mutation.
5. **LLM Provider & Validation Hardening:** Verify bounded retries (max 3), strict Pydantic contract preservation, request idempotency, and graceful degradation when credentials are missing.
6. **Dual Document-Store Integrity:** Verify atomic JSON file replacement, concurrency locking, index synchronization, and corrupt-file resilience.
7. **API Contract & Error Handling:** Verify status codes (400, 404, 409, 422, 502, 503, 504), error response safety (no leaked secrets/traces), and OpenAPI schemas.
8. **End-to-End Acceptance Demonstration:** Deliver a reproducible, isolated demonstration script (`scripts/final_acceptance_demo.py`) with clean execution evidence.

---

## 2. Requirement Verification Matrix & Risk Assessment

| Requirement Area | Relevant Code Locations | Identified Risks | Planned Verification & Fix | Status |
|---|---|---|---|---|
| **1. Grounding Audit Engine** | `app/services/grounding_auditor.py`, `app/schemas/qa_test_case.py` | Generated test cases may introduce ungrounded numerical tolerances (e.g. $\pm 2$ mmHg), fictional test bench equipment, or wrong error codes (e.g. E1 for battery). | Implement `GroundingAuditor` classifying claims into 5 categories; update `MockLLMProvider` to cleanly ground claims and tag proposed equipment setups; expose grounding summary on test suites. | **VERIFIED** |
| **2. CT-200 v1/v2 Facts** | `app/services/pdf_parser.py`, `app/services/staleness_classifier.py` | Numerical/timing shifts between v1 and v2 must match actual PDF text: Battery (300 $\rightarrow$ 250 cycles, 15% $\rightarrow$ 10%), Cuff (40 $\rightarrow$ 30 mmHg), E3 (2.0s $\rightarrow$ 1.5s), E6 addition. | Verify all source facts directly from parsed AST; ensure classifier assertions match exact source deltas. | **VERIFIED** |
| **3. Parser Irregularities (IR-1 to IR-7)** | `app/services/pdf_parser.py`, `tests/test_parser_edge_cases.py` | Subsequent versioning and selection additions must not have broken edge-case extraction. | Run edge-case tests against v1/v2; confirm all 7 structural irregularities remain resolved. | **VERIFIED** |
| **4. Selection Immutability** | `app/db/models.py`, `app/repositories/document_repository.py` | Ingesting v2 might overwrite or retarget v1 selections or node hashes. | Verify version-pinned selections remain bound to v1 `NodeVersion` IDs and original hashes after v2 ingestion. | **VERIFIED** |
| **5. Cross-Store Failure Handling** | `app/services/qa_generation_service.py`, `app/repositories/json_test_suite_store.py` | Partial failure between relational SQLite and document store could cause ghost records or false success. | Implement fail-safe persistence check: generation is only reported successful if document store write succeeds. | **VERIFIED** |
| **6. API Error Handling & Schemas** | `app/main.py`, `app/schemas/api.py`, `app/schemas/qa_test_case.py` | Inconsistent HTTP error codes or leaked stack traces. | Audit all exception handlers (400 for bad parameters, 404 for missing IDs, 409 for idempotency conflicts, 422 for validation, 503 for missing provider config). | **VERIFIED** |
| **7. Final Acceptance Demo** | `scripts/final_acceptance_demo.py` | Demo must run out-of-the-box in isolated storage without requiring paid API keys or external services. | Build `final_acceptance_demo.py` exercising complete v1 $\rightarrow$ selection $\rightarrow$ generation $\rightarrow$ grounding audit $\rightarrow$ v2 migration $\rightarrow$ staleness workflow. | **VERIFIED** |
| **8. API Reference Documentation** | `docs/api-reference.md`, `README.md` | Incomplete API documentation or hardcoded ephemeral IDs. | Create `docs/api-reference.md` with curl requests and realistic placeholder responses; update `README.md`. | **VERIFIED** |

---

## 3. Progress Tracking & Action Items

- [x] Step 1: Baseline repository inspection and test verification (67/67 passing).
- [x] Step 2: Implement `GroundingAuditor` service and schemas (`app/services/grounding_auditor.py`).
- [x] Step 3: Refine `MockLLMProvider` and prompt instructions to eliminate ungrounded assumptions and accurately distinguish source requirements from proposed test setups.
- [x] Step 4: Integrate grounding audit into `QAGenerationService` and expose grounding summary in API responses.
- [x] Step 5: Verify CT-200 v1/v2 facts and all 7 parser edge cases against actual PDF content.
- [x] Step 6: Create comprehensive grounding and acceptance tests in `tests/test_grounding_audit.py` (76/76 tests passing).
- [x] Step 7: Build `scripts/final_acceptance_demo.py` with isolated storage and complete verification output (14/14 milestones passed).
- [x] Step 8: Create `docs/api-reference.md` and `docs/final-acceptance-report.md`.
- [x] Step 9: Update `README.md` and run clean setup verification.
- [x] Step 10: Commit in logical units and push to `origin/main`.
