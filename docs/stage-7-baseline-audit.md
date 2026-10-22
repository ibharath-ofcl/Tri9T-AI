# Stage 7 Baseline Verification & Repository Audit

**Date:** October 2026  
**Auditor:** Skeptical Assignment Reviewer & Senior AI/QA Backend Architect  
**Repository:** [https://github.com/ibharath-ofcl/Tri9T-AI.git](https://github.com/ibharath-ofcl/Tri9T-AI.git)  
**Branch:** `main`  
**Verified Commit:** `b61b733b5841f14daaeb26398a9b54dbf7942bb6` (`b61b733`)  
**Remote Tracking:** `origin/main` (Synchronized, 0 commits ahead/behind)  
**Working Tree Status:** Clean (`nothing to commit, working tree clean`)

---

## 1. Executive Summary & Verification Findings

Before modifying any code in Stage 7, the entire repository was subjected to an independent pre-flight audit.

### Verified Baseline Metrics
- **Git HEAD**: `b61b733` matches `origin/main`.
- **Pytest Suite**: **76 passed / 0 failed** in 6.81 seconds.
- **Acceptance Demo**: `scripts/final_acceptance_demo.py` executed successfully (**14/14 milestones passed**, clean exit code 0).
- **FastAPI OpenAPI Schema**: 18 active routes documented and validated.
- **Source Manuals**: Both authentic PDFs are present in `data/` (`ct200_manual.pdf` at 6 pages, `ct200_manual_v2.pdf` at 7 pages).

---

## 2. Component Inspection & Codebase Review

| Subsystem | File Location | Architectural Findings | Audit Notes |
|---|---|---|---|
| **PDF Extraction Engine** | `app/services/pdf_parser.py` | Extracts typography, headings, tables, and page boundaries using `pdfplumber`. Deterministic, non-LLM based. | Resolves all 7 structural irregularities (IR-1 to IR-7). |
| **Relational Storage** | `app/db/models.py`, `app/services/document_ingestion.py` | SQLAlchemy 2.0 models: `Document`, `DocumentVersion`, `LogicalNode`, `NodeVersion`, `Selection`, `SelectionNode`. | Enforces foreign keys and hash immutability via unique constraints. |
| **Lineage & Diff** | `app/services/node_matcher.py`, `app/services/staleness_classifier.py` | Matches logical sections across versions; classifies differences into 11 granular categories. | Precedence rules place timing and numerical changes over wording changes. |
| **Named Selections** | `app/services/selection_service.py` | Named verification scopes pinned to a single immutable document version. | Rejects cross-version node mixing and prevents silent retargeting. |
| **LLM QA Generation** | `app/services/qa_generation_service.py`, `app/services/llm_provider.py` | Pydantic validation with bounded retries (max 3), corrective prompts, and SHA-256 idempotency. | Includes `MockLLMProvider` and `OpenAICompatibleProvider`. |
| **Document Persistence** | `app/repositories/json_test_suite_store.py`, `mongo_test_suite_store.py` | Concurrency-safe atomic filesystem store using write-rename pattern and advisory file locks. | Decoupled optional MongoDB store available lazily. |
| **Source-Grounding Auditor** | `app/services/grounding_auditor.py` | Classifies claims into `SOURCE_SUPPORTED`, `DERIVED_WITH_EXPLANATION`, `PROPOSED_SETUP`, `UNSUPPORTED`, `AMBIGUOUS`. | Flags ungrounded claims and requires human review. |

---

## 3. Pre-Flight Test & Demonstration Evidence

### A. Pytest Baseline Execution
```text
============================= test session starts ==============================
platform darwin -- Python 3.13.7, pytest-9.1.1, pluggy-1.7.0
rootdir: /Users/bharathbodduvenkata/PROJECTS/Tri9T-AI
configfile: pytest.ini
collected 76 items

tests/test_api.py (4 tests) ................ PASSED
tests/test_grounding_audit.py (9 tests) ..... PASSED
tests/test_impact_and_selection_api.py (3 tests) PASSED
tests/test_parser_edge_cases.py (7 tests) ... PASSED
tests/test_pdf_parser.py (6 tests) .......... PASSED
tests/test_qa_generation.py (15 tests) ...... PASSED
tests/test_selections.py (7 tests) .......... PASSED
tests/test_staleness_classifier.py (11 tests) PASSED
tests/test_versioning_and_ingestion.py (8 tests) PASSED
tests/test_versioning_api.py (6 tests) ...... PASSED

======================== 76 passed, 1 warning in 6.81s =========================
```

### B. Final Acceptance Demo Output
```text
[Step 1/14] Setting up isolated, disposable test storage... [OK]
[Step 2/14] Ingesting CT-200 Technical Manual v1 (27 nodes across 6 pages)... [OK]
[Step 3/14] Ingesting CT-200 Technical Manual v2 (28 nodes across 7 pages)... [OK]
[Step 4/14] Verifying v1 snapshot immutability after v2 ingestion... [OK] Zero mutation detected.
[Step 5/14] Resolving target sections from v1 hierarchy (2.1.1.1, 3.2, 4.2, 1.1)... [OK]
[Step 6/14] Creating named selection pinned to v1 (4 nodes)... [OK]
[Step 7/14] Generating 4 QA test cases from pinned selection... [OK]
[Step 8/14] Validating test case schema & cryptographic provenance... [OK]
[Step 9/14] Reviewing Deterministic Source-Grounding Audit results... [OK] (21 supported, 6 proposed setup, 0 unsupported)
[Step 10/14] Verifying atomic persistence and retrieval from JSON document store... [OK]
[Step 11/14] Verifying duplicate-submission policy & idempotency... [OK]
[Step 12/14] Evaluating test suite staleness against CT-200 v2... [OK] (Status: IMPACTED)
[Step 13/14] Verifying exact detected source changes (cycles 300->250, threshold 15->10%, pressure 40->30 mmHg, timing 2->1.5s, E6 added)... [OK]
[Step 14/14] Verifying unchanged control case (§1.1) & provenance immutability... [OK]
FINAL ACCEPTANCE DEMO VERDICT: [PASS]
```

---

## 4. Identified Areas for Adversarial Grounding Red-Teaming (Phase 2 Focus)

While the baseline implementation passes all 76 tests, a rigorous reviewer must probe deeper into the grounding auditor:
1. **Semantic Phrasing & Unit Variations**: Can the auditor handle alternative notations (`1.5 s` vs `1.5 seconds`, `2.0 s` vs `2 seconds`, `22 cm` vs `22cm`)?
2. **Conflicting Version Values**: What happens if an assertion claims a v2 threshold (`10%`) while citing a v1-pinned section (`15%`)? Does it detect the version mismatch?
3. **Mixed Sentences**: If an assertion blends a supported claim (`180 mmHg`) with an unsupported tolerance (`±2 mmHg`) or invented limit (`350 mmHg`), does it flag the claim as `UNSUPPORTED`?
4. **Negated Claims & Inverted Logic**: If an assertion states "The device does NOT auto-deflate upon overpressure", does it detect contradiction with Table 4.1?
5. **Wrong Section Binding**: If a valid value from Section 1.1 (e.g. `42 cm`) is cited under Section 4.2 Error Codes, does it detect that the value is not in the cited section?
6. **Provenance Integrity**: If a test case omits or tampers with the `source_node_version_id` or `source_content_hash`, does the auditor reject or flag it?

These adversarial scenarios will be tested systematically in Phase 2.
