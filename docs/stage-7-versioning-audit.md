# Stage 7 Versioning, Immutability & Staleness Audit

**Date:** October 2026  
**Auditor:** Skeptical Assignment Reviewer & Senior Database Architect  
**Subsystems Audited:**
- `app/services/document_ingestion.py`
- `app/services/node_matcher.py`
- `app/services/staleness_classifier.py`
- `app/services/selection_service.py`
- `app/repositories/document_repository.py`
- `app/db/models.py`

---

## 1. CT-200 v1 vs v2 Ground-Truth Source Facts Verification

The following differences were extracted and verified directly from the actual PDF files (`data/ct200_manual.pdf` and `data/ct200_manual_v2.pdf`), rather than relying on prior documentation:

| Specification Delta | v1 Manual Value | v2 Manual Value | Source Section / Table | Extracted Evidence |
|---|---|---|---|---|
| **Battery Measurement Cycles** | 300 cycles | 250 cycles | §2.1.1.1 (Battery Life) | Text: "...approximately 300 measurement cycles..." $\rightarrow$ "...approximately 250 measurement cycles..." |
| **Low-Battery Warning Threshold** | 15% | 10% | §2.1.1.1 (Battery Life) | Text: "...falls below 15%." $\rightarrow$ "...falls below 10%." |
| **Cuff Inflation Increment** | 40 mmHg | 30 mmHg | §3.2 (Cuff Inflation) | Text: "...increases in 40 mmHg increments..." $\rightarrow$ "...increases in 30 mmHg increments..." |
| **E3 Auto-Deflate Timing** | 2.0 seconds | 1.5 seconds | §4.2 (Table 4.1) | Row text: "Auto-deflate within 2.0s" $\rightarrow$ "Auto-deflate within 1.5s" |
| **New Error Code Addition** | Absent (E1–E5 only) | Present (`E6`) | §4.2 (Table 4.1) | New Row: `["E6", "Bluetooth synchronization failure", "Retry sync or repair device"]` |
| **New Section Added** | Absent (27 total nodes) | Present (28 total nodes) | §5.3 (Data Export) | AST: `CanonicalSectionNumber="5.3"`, `CanonicalHeading="Data Export"` |

---

## 2. Invariants & Lifecycle Verification

### 1. Ingestion Idempotency & Conflict Policy
- **Verified by:** `tests/test_versioning_and_ingestion.py::test_idempotent_ingestion`, `test_conflicting_version_checksum_rejection`
- **Behavior:** Re-ingesting an identical PDF with matching SHA-256 returns the existing record immediately without duplicating nodes. Ingesting different content under an already-registered version label raises `ValueError` and rolls back atomically.

### 2. Immutability of Prior Version Snapshots
- **Verified by:** `tests/test_selections.py::test_selection_pinned_version_immutability_after_v2_ingest`, `scripts/final_acceptance_demo.py` (Step 4 & 14)
- **Behavior:** Every node version has a permanent `NodeVersion.id` and immutable `content_hash`. After ingesting v2, all 27 v1 node version rows, content hashes, and parent references remained 100% identical.

### 3. Node Lineage & Disambiguation
- **Verified by:** `tests/test_versioning_and_ingestion.py::test_duplicate_error_codes_headings_disambiguation`, `test_ingest_v1_and_v2_lineage`
- **Behavior:** Duplicate section headings (such as "4.2 Error Codes" vs "7.1 Error Codes") are disambiguated by their structural ancestry (`parent_node_version_id`) and assigned separate `LogicalNode` identities.

### 4. Selection Pinning & Prevention of Silent Drift
- **Verified by:** `tests/test_selections.py::test_create_and_get_selection_pinned_to_v1`, `test_reject_mixed_version_nodes`
- **Behavior:** Selections are pinned to a single `document_version_id`. Selection creation validates that all selected nodes belong strictly to that version. Ingesting a newer document version never alters the selection's pinned version.

### 5. Staleness Classification Accuracy
- **Verified by:** `tests/test_staleness_classifier.py` (11 tests)
- **Behavior:** Numerical and timing changes take precedence over generic wording changes. Whitespace-only changes are classified as `FORMATTING_ONLY` and do not require human review. Parameter modifications extract old and new values with units and require human review.

### 6. Test Case Provenance Stability
- **Verified by:** `tests/test_grounding_red_team.py::test_case_11_missing_or_tampered_provenance`, `scripts/final_acceptance_demo.py` (Step 14)
- **Behavior:** Evaluating a generated test suite against v2 produces a staleness assessment, but the test case's original `Provenance` record (pointing to v1 `source_node_version_id` and v1 `content_hash`) is preserved completely without mutation.
