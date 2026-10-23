# Evaluator Demonstration Guide

**Project:** CardioTrack CT-200 Medical Device Document Intelligence and QA Test Generation  
**Target Script:** [`scripts/evaluator_demo.py`](file:///Users/bharathbodduvenkata/PROJECTS/Tri9T-AI/scripts/evaluator_demo.py)  
**Execution Command:** `python3 -m scripts.evaluator_demo`  
**Execution Time:** ~0.6 seconds  
**Prerequisites:** Python 3.10+, dependencies from `requirements.txt`  
**Network/Cloud Dependency:** None (100% offline self-contained runner)  

---

## 1. Purpose of the Evaluator Demo

The Evaluator Demo provides reviewers with a transparent, verifiable, and isolated walkthrough of the complete system in under one minute. Rather than requiring evaluators to manually make API requests across multiple terminals, this script automatically executes the entire lifecycle against the actual CT-200 technical manuals (`data/ct200_manual.pdf` v1 and `data/ct200_manual_v2.pdf` v2) inside isolated, disposable storage.

---

## 2. The 14 Demonstration Milestones

| Step | Milestone Name | What It Visibly Demonstrates | Verification Evidence |
| :---: | :--- | :--- | :--- |
| **1** | **Isolated Storage Initialization** | Spins up in-memory SQLite with foreign key pragmas and a temporary POSIX filesystem JSON store. | Confirms no interference with pre-existing local data. Cleaned up upon exit. |
| **2** | **CT-200 v1 Ingestion** | Extracts text and hierarchy from `data/ct200_manual.pdf` (6 pages, 27 nodes). | Resolves headings, body text, tables, and assigns SHA-256 hashes. |
| **3** | **CT-200 v2 Ingestion** | Ingests `data/ct200_manual_v2.pdf` (7 pages, 28 nodes) and matches logical node lineage. | Discovers added Section §5.3 Data Export without modifying v1 history. |
| **4** | **Version Metadata & Immutability** | Compares node counts and verifies cryptographic hashes for all 27 v1 nodes. | Proves zero snapshot drift or mutation after v2 ingestion. |
| **5** | **Specification Change Display** | Displays the 6 confirmed ground-truth manual changes. | Verifies battery, cuff pressure, deflation timing, and error code deltas. |
| **6** | **Target Node Resolution** | Resolves high-risk sections (§2.1.1.1, §3.2, §4.2, and §1.1 control). | Matches persistent `NodeVersion` UUIDs from the relational store. |
| **7** | **Version-Pinned Selection** | Creates named verification scope `CT200-Core-Safety-Critical-Suite` pinned strictly to v1. | Selection pins immutable node version UUIDs; cannot silently slide to v2. |
| **8** | **Structured QA Generation** | Generates 4 structured test cases via `MockLLMProvider`. | Validates PascalCase schema fields (`TestCaseId`, `Steps`, `ExpectedResult`, etc.). |
| **9** | **Cryptographic Provenance** | Displays exact source bindings for each test case. | Displays `source_node_version_id`, `source_content_hash`, and section numbers. |
| **10** | **Deterministic Grounding Audit** | Audits 33 claims across 5 categories (`SUPPORTED`, `DERIVED`, `SETUP`, `UNSUPPORTED`, `AMBIGUOUS`). | Classifies manual specifications vs test equipment with zero false negatives. |
| **11** | **Adversarial Unsupported Claim** | Submits an adversarial test case with invented `±2 mmHg` tolerance and `99.9% uptime`. | Auditor flags 4 unsupported claims and sets `human_review_required: True`. |
| **12** | **Cross-Version Staleness Impact** | Audits original v1 test suite against CT-200 v2. | Status transitions to `IMPACTED` with exact numeric and timing deltas. |
| **13** | **Unchanged Control Case** | Tests Section §1.1 (Intended Use) against v2. | Status remains `CURRENT`. Proves zero false-positive alerts on unchanged text. |
| **14** | **Idempotency & Tampering Defense** | Replays request with identical key (same ID returned); alters parameters (rejected with error). | Enforces strict idempotent replay and prevents accidental duplicate runs. |

---

## 3. How to Run the Demo

### Single Command
```bash
python3 -m scripts.evaluator_demo
```

### Expected Output Summary
```
================================================================================
CARDIOTRACK CT-200 — EVALUATOR DEMONSTRATION WORKFLOW
================================================================================
[Step 1/14] Initializing Isolated Disposable Storage...
[Step 2/14] Ingesting CT-200 v1 Technical Manual (data/ct200_manual.pdf)...
[Step 3/14] Ingesting CT-200 v2 Technical Manual (data/ct200_manual_v2.pdf)...
[Step 4/14] Verifying Ingested Document Versions & Node Counts...
[Step 5/14] Displaying Verified Cross-Version Specification Changes:
[Step 6/14] Resolving Representative Nodes for QA Test Generation...
[Step 7/14] Creating Version-Pinned Named Selection...
[Step 8/14] Generating Structured QA Test Cases via MockLLMProvider...
[Step 9/14] Inspecting Cryptographic Source Provenance Bindings:
[Step 10/14] Executing Deterministic Source-Grounding Audit...
[Step 11/14] Demonstrating Adversarial Detection of Unsupported Assertion...
[Step 12/14] Evaluating Selection & Test Suite Staleness Against CT-200 v2...
[Step 13/14] Demonstrating Unchanged Control Section (§1.1 Intended Use)...
[Step 14/14] Demonstrating Idempotent Retrieval & Parameter Tampering Rejection...
================================================================================
EVALUATOR DEMONSTRATION VERDICT: [PASS]
All 14 Demonstration Milestones Successfully Verified!
================================================================================
  ✓ Temporary storage cleaned up.
```

---

## 4. Troubleshooting & Notes

- **Exit Codes:** Returns `0` if all 14 milestones complete with assertion verification; returns `1` on any assertion mismatch or failure.
- **Storage Cleanup:** The `tempfile` directory is registered in a `finally` block and is removed even if an unexpected exception occurs.
- **No Network Needed:** By utilizing `MockLLMProvider`, the demo does not make any HTTP requests or require OpenAI API tokens.
