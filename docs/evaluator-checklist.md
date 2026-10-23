# Evaluator Review Checklist

**Project:** CardioTrack CT-200 Medical Device Document Intelligence and QA Test Generation  
**Target Repository:** `https://github.com/ibharath-ofcl/Tri9T-AI.git`  
**Branch:** `main`  
**Evaluation Time Required:** ~3 to 5 minutes  

---

## 1. Prerequisites Check

Ensure the host environment meets these minimum specifications:
- **Operating System:** macOS, Linux, or Windows (WSL recommended)
- **Python Version:** Python 3.10, 3.11, 3.12, or 3.13 (`python3 --version`)
- **Git:** Git 2.30+ (`git --version`)
- **Disk Space:** ~150 MB (virtual environment and dependencies)
- **Network / Cloud Services:** **None required.** The system is 100% self-contained and operates completely offline with the included `MockLLMProvider` and SQLite/JSON stores.

---

## 2. Setup Commands

Execute the following commands in an empty working directory:

```bash
# 1. Clone the repository and navigate to root
git clone https://github.com/ibharath-ofcl/Tri9T-AI.git
cd Tri9T-AI

# 2. Confirm branch and clean baseline
git checkout main
git status

# 3. Create and activate a clean Python virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt
```

---

## 3. Recommended Verification Commands

Reviewers can verify the entire project through three primary commands:

### Command A: Single-Command Comprehensive Verification (Recommended)
Runs the full test suite, acceptance demo, red-team checks, and OpenAPI validation in one pass:
```bash
python3 -m scripts.stage7_final_verification
```
- **Expected Duration:** ~6 to 8 seconds
- **Expected Result:** `ALL STAGE 7 VERIFICATION CHECKS PASSED (4/4)`.

### Command B: Evaluator Walkthrough Demo
Visibly demonstrates all 14 core milestones with color-coded terminal cards:
```bash
python3 -m scripts.evaluator_demo
```
- **Expected Duration:** ~0.6 seconds
- **Expected Result:** `EVALUATOR DEMONSTRATION VERDICT: [PASS]` (14/14 milestones passed).

### Command C: Full Pytest Regression Suite
Executes all unit, integration, and red-team tests across 10 test modules:
```bash
pytest -v
```
- **Expected Result:** `90 passed in ~6.00s` (0 failed, 0 warnings).

---

## 4. REST API Exploration & Swagger UI

To explore the live HTTP REST API and OpenAPI contracts:

```bash
# Start the FastAPI server locally
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

1. Open your web browser and navigate to:  
   **Interactive Swagger UI:** `http://localhost:8000/docs`  
   **ReDoc:** `http://localhost:8000/redoc`  
   **Health Telemetry:** `http://localhost:8000/health`
2. **Key API Endpoints to Test in Swagger:**
   - `POST /api/v1/documents/ingest?version=v1`: Ingest CT-200 v1 manual.
   - `POST /api/v1/documents/ingest?version=v2`: Ingest CT-200 v2 manual.
   - `GET /api/v1/documents`: List ingested revisions and metadata.
   - `GET /api/v1/documents/{document_id}/sections?version=v1`: View hierarchical document tree.
   - `GET /api/v1/search?q=cuff&version=v1`: Full-text search across manual nodes.
   - `POST /api/v1/selections`: Create a version-pinned named selection.
   - `POST /api/v1/selections/{selection_id}/test-suites`: Generate grounded QA test cases.
   - `GET /api/v1/test-suites/{generation_id}/staleness?target_version=v2`: Evaluate cross-version impact.

---

## 5. Expected High-Level Results

| Requirement / Milestone | Expected Output | Status |
| :--- | :--- | :---: |
| **CT-200 v1 Document Hierarchy** | 27 hierarchical nodes across 6 pages | Verified |
| **CT-200 v2 Document Hierarchy** | 28 hierarchical nodes across 7 pages (added §5.3) | Verified |
| **All 7 Structural Irregularities** | Handled deterministically (IR-1 through IR-7) | Verified |
| **Ground-Truth Spec Changes** | Battery: 300→250 cycles, 15→10%; Cuff: 40→30 mmHg; E3: 2.0→1.5s; E6 row | Verified |
| **Automated Test Suite** | 90 tests passing (10 modules, 100% pass rate) | Verified |
| **Grounding Auditor** | Classifies 33 claims across 5 categories; catches unsupported claims | Verified |
| **Adversarial Red-Team Suite** | 14/14 adversarial vectors passed | Verified |
| **OpenAPI Schema Contract** | 18 paths documented and schema-valid | Verified |

---

## 6. Troubleshooting Guidance

1. **Port 8000 in use:**  
   If port 8000 is occupied, run uvicorn on another port:
   ```bash
   uvicorn app.main:app --port 8080
   ```
2. **Missing Manual PDFs:**  
   Ensure `data/ct200_manual.pdf` (6 pages) and `data/ct200_manual_v2.pdf` (7 pages) exist in the root `data/` folder.
3. **Database Reset:**  
   If you wish to reset the local SQLite database used by the REST server, delete `ct200_documents.db` in the project root; it will be automatically recreated on the next startup.

---

## 7. Known Boundaries & Limitations

1. **Medical Device Prototype Disclaimer:** This system is an engineering assignment submission. It has **not** been certified under FDA 21 CFR Part 820 or IEC 62304.
2. **Human-in-the-Loop Gate:** All test cases flagged with `human_review_required: true` (e.g. ungrounded claims, parameter shifts, proposed fixtures) must be verified by a biomedical test engineer.
3. **Mock Provider Default:** The system defaults to `MockLLMProvider` for deterministic offline evaluation. Live cloud LLM evaluation can be enabled via `.env` (`LLM_PROVIDER=openai_compatible`).
