# Stage 8 Submission Plan: Professional Packaging & Release Readiness

**Project:** CardioTrack CT-200 Medical Device Document Intelligence and QA Test Generation  
**Target Repository:** `https://github.com/ibharath-ofcl/Tri9T-AI.git`  
**Current Baseline Commit:** `5a44ece`  
**Evaluation Target Branch:** `main`  
**Evaluator Perspective:** Senior Software Architect, Technical Documentation Engineer, QA Lead, Skeptical Reviewer  
**Audit Date:** 2026-10-23  

---

## 1. Baseline State & Pre-Flight Verification

The repository baseline was inspected and verified prior to initiating Stage 8:
- **Git Branch:** `main`
- **Verified Commit:** `5a44ece` (`test: harden final grounding and submission verification`)
- **Remote Synchronization:** In sync with `origin/main` (clean working tree)
- **Pytest Suite:** 90 tests passing (10 modules, 0 failures, 6.00s)
- **Acceptance Demo:** 14/14 milestones passing (0.63s)
- **Adversarial Red-Team:** 14/14 adversarial tests passing (0.35s)
- **OpenAPI Schema:** 18 REST routes verified and schema-valid (0.45s)

---

## 2. What an Evaluator Needs to Understand in the First 5 Minutes

1. **System Identity & Core Mission:**
   This is a high-reliability Document Intelligence and QA Test Generation system designed specifically for the CardioTrack CT-200 blood pressure monitor manuals (`ct200_manual.pdf` v1 and `ct200_manual_v2.pdf` v2). It provides deterministic typography-based PDF parsing, immutable versioned relational snapshots, cross-version change detection, version-pinned test selections, explainable staleness classification, and a 5-state deterministic source-grounding auditor.

2. **Immediate Execution Path (One Command):**
   ```bash
   python3 -m scripts.evaluator_demo
   ```
   Or the full test suite:
   ```bash
   pytest -v
   ```
   Zero network requests, zero external API keys, zero cloud dependencies. Works 100% offline via local SQLite, atomic JSON storage, and deterministic `MockLLMProvider`.

3. **Key Architectural Differentiators:**
   - **No OCR/LLM in the Parser Loop:** Uses geometric character extraction via `pdfplumber` to eliminate stochastic text hallucinations and lossy OCR artifacts.
   - **Deterministic Document Versioning:** Dual-layer architecture: SQLite handles immutable relational lineage and metadata; JSON store handles complete test suite trees with advisory file locking and atomic rename replacement (`os.replace`).
   - **Explainable Staleness Hierarchy:** Categorizes specification shifts (`NUMERIC_CHANGE`, `TIMING_CHANGE`, `TABLE_ROW`) and automatically flags `human_review_required: true`.
   - **5-State Grounding Auditor:** Distinguishes verified manual specs (`SOURCE_SUPPORTED`) from arithmetic progressions (`DERIVED_WITH_EXPLANATION`), test fixtures (`PROPOSED_SETUP`), and ungrounded claims (`UNSUPPORTED`).

4. **Honest Scope & Disclaimers:**
   - Prototype developed for an engineering assignment.
   - **Not** FDA/CE certified or clinically validated.
   - All test cases require human-in-the-loop review by a qualified biomedical engineer before bench execution.

---

## 3. Identified Gaps & Stage 8 Work Plan

| Area | Current State | Required Stage 8 Polish |
| :--- | :--- | :--- |
| **README.md** | Comprehensive but chronological across stages 1–7. | Reorganize into a clean, evaluator-first layout: Overview, Problem, Solution, Architecture, Tech Stack, Quickstart, Demo, API docs, Limitations, Safety. |
| **Architecture Documentation** | Scattered across stage reports (`docs/stage-1` to `stage-7`). | Create unified `docs/architecture.md` with Mermaid system architecture and end-to-end sequence diagrams reflecting real code paths. |
| **Evaluator Demo Experience** | `run_acceptance_demo.py` is thorough (14 steps) but verbose. | Create `scripts/evaluator_demo.py` tailored for a concise 2-minute live walkthrough, accompanied by `docs/evaluator-demo-guide.md`. |
| **Sample JSON Outputs** | Outputs exist in logs and tests, not standalone files. | Create `docs/examples/` containing verified, valid JSON samples for ingestion, diff, selection, QA test case, audit, and staleness. |
| **Evaluator Checklist** | Instructions split across README sections. | Create `docs/evaluator-checklist.md` with prerequisites, setup, commands, expected results, and troubleshooting. |
| **Release Hygiene** | Clean git state with 90 tests. | Create `docs/stage-8-release-checklist.md` confirming zero uncommitted artifacts, tracked PDFs, and offline reproducibility. |

---

## 4. Execution Sequence

1. **Phase 2:** Revise `README.md` to be polished, structured, and reviewer-friendly.
2. **Phase 3:** Create `docs/architecture.md` with Mermaid architecture and sequence diagrams.
3. **Phase 4:** Create `scripts/evaluator_demo.py` and `docs/evaluator-demo-guide.md`.
4. **Phase 5:** Generate `docs/examples/*.json` sample files and `docs/evaluator-checklist.md`.
5. **Phase 6:** Review OpenAPI and schema discovery.
6. **Phase 7:** Audit release hygiene and create `docs/stage-8-release-checklist.md`.
7. **Phase 8:** Run full regression suite (pytest, stage 7 verification, evaluator demo, OpenAPI check, JSON validation).
8. **Phase 9:** Stage, commit with descriptive message, push to `origin/main`, and report evidence.
