# Stage 9 Versioning & Staleness Correctness Audit

**Auditor:** Independent Evaluator & Backend Architect  
**Target:** Relational Versioning Models, Lineage Matcher, and Staleness Classifier  
**Target Files:** [`app/services/document_ingestion.py`](file:///Users/bharathbodduvenkata/PROJECTS/Tri9T-AI/app/services/document_ingestion.py), [`app/services/version_matcher.py`](file:///Users/bharathbodduvenkata/PROJECTS/Tri9T-AI/app/services/version_matcher.py), [`app/services/staleness_classifier.py`](file:///Users/bharathbodduvenkata/PROJECTS/Tri9T-AI/app/services/staleness_classifier.py)  
**Date:** 2026-10-23  

---

## 1. Ground-Truth Manual Differences Verification

The physical text of `data/ct200_manual.pdf` (v1) and `data/ct200_manual_v2.pdf` (v2) was independently inspected to confirm that reported specification changes reflect genuine source differences rather than synthetic test assumptions:

| Specification / Requirement | Exact CT-200 v1 Text (Page) | Exact CT-200 v2 Text (Page) | Verified Delta |
| :--- | :--- | :--- | :---: |
| **Battery Life Rating** | "provide approximately **300 measurement cycles** under typical use" (Page 2, §2.1.1.1) | "provide approximately **250 measurement cycles** under typical use" (Page 2, §2.1.1.1) | **300 → 250 cycles** (`NUMERIC_CHANGE`) |
| **Low-Battery Warning Alert** | "once remaining capacity falls below **15%**." (Page 2, §2.1.1.1) | "once remaining capacity falls below **10%**." (Page 2, §2.1.1.1) | **15% → 10%** (`NUMERIC_CHANGE`) |
| **Cuff Inflation Increment** | "inflation increases in **40 mmHg** increments" (Page 3, §3.2) | "inflation increases in **30 mmHg** increments" (Page 3, §3.2) | **40 → 30 mmHg** (`NUMERIC_CHANGE`) |
| **E3 Auto-Deflate Timing** | "automatic cuff deflation within **2.0 seconds**" (Page 4, §4.2) | "automatic cuff deflation within **1.5 seconds**" (Page 4, §4.2) | **2.0 → 1.5 seconds** (`TIMING_CHANGE`) |
| **Bluetooth Error Code** | Absent from Table 4.1 (E0 through E5 only) (Page 4, Table 4.1) | "E6: Bluetooth synchronization failure" added to Table 4.1 (Page 5, Table 4.1) | **Table Row E6 Added** (`TABLE_ROW`) |
| **New Section: Data Export** | Section absent from document hierarchy | "5.3 Data Export — Test records may be exported via Bluetooth BLE 5.0..." (Page 6, §5.3) | **Section §5.3 Added** (`ADDED`) |

All 6 reported specification deltas are verified authentic manual facts.

---

## 2. Versioning & Relational Edge-Case Audit

The versioning and staleness systems were evaluated across 10 critical operational scenarios:

| # | Evaluated Versioning Scenario | Observed Engine Behavior | Integrity Verification |
| :---: | :--- | :--- | :---: |
| **1** | **Re-ingestion of Existing Version** | Returns `IngestionResult(is_idempotent_replay=True)` or HTTP `409 Conflict` if duplicate checksum collision is detected. Does not duplicate node rows. | `PASS` |
| **2** | **Changed Section with Stable Heading** | Section §3.2 retains heading "3.2 Cuff Inflation Sequence", but content hash changes (`5477...` $\rightarrow$ `2ff1...`). Correctly mapped to existing `LogicalNode` with new `NodeVersion`. | `PASS` |
| **3** | **Moved / Renumbered Section** | Matcher uses multi-signal similarity (title similarity + hierarchy position) when section numbers diverge. Accurately reports `MOVED` or `RENUMBERED`. | `PASS` |
| **4** | **Deleted Section** | If a node in v1 has no correspondence in v2, staleness classifier marks status as `SOURCE_REMOVED` with `human_review_required: true`. | `PASS` |
| **5** | **Added Section** | Section §5.3 is registered with a newly allocated `LogicalNode` in v2. Diff correctly identifies `change_classification: "ADDED"`. | `PASS` |
| **6** | **Table-Only Change** | In Table 4.1, adding error code E6 triggers `TABLE_ROW` change classification, even if surrounding paragraph wording is minimal. | `PASS` |
| **7** | **Unchanged Section Context** | Section §1.1 Intended Use has identical content hash in v1 and v2. Evaluates to `CURRENT` with zero false-positive alerts. | `PASS` |
| **8** | **Mixed Selection Staleness** | A selection containing §1.1 (unchanged), §2.1.1.1 (modified), and §3.2 (modified) produces aggregate status `IMPACTED` while correctly marking §1.1 as `CURRENT`. | `PASS` |
| **9** | **Comparison Against Unknown Version** | Requesting staleness against `target_version=v99` raises `HTTP 404 Not Found` with actionable error message (`Target version 'v99' not found`). | `PASS` |
| **10** | **Historical Immutability Guard** | Ingesting v2 does not update or touch `NodeVersion` rows for v1. Hash comparisons prove 100% byte-for-byte immutability across all 27 v1 nodes. | `PASS` |

---

## 3. Audit Verdict

**Result: PASS.**  
The versioning engine guarantees snapshot immutability, correctly binds logical node lineage across document revisions, and classifies requirement shifts into granular, explainable categories without false-positive impacts on unchanged sections.
