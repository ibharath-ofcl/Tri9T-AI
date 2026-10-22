# Stage 7 Clean-Environment Reproducibility Report

**Date:** October 2026  
**Auditor:** Skeptical Assignment Reviewer & Quality Engineer  
**Objective:** Verify that an independent reviewer or evaluator can check out and run the project from a fresh environment without external network services, paid API keys, or pre-existing databases.

---

## 1. Environment & Setup Verification Steps

The setup procedure was verified strictly using the documented instructions in `README.md`:

```bash
# 1. Clone repository
git clone https://github.com/ibharath-ofcl/Tri9T-AI.git
cd Tri9T-AI

# 2. Virtual environment setup
python3 -m venv .venv
source .venv/bin/activate

# 3. Dependency installation
pip install -r requirements.txt
```

### Dependency Audit
- All dependencies are declared in `requirements.txt`:
  - `fastapi>=0.115.0`, `uvicorn[standard]>=0.30.0`
  - `pydantic>=2.9.0`, `pydantic-settings>=2.5.0`
  - `sqlalchemy>=2.0.35`
  - `pdfplumber>=0.11.4`
  - `httpx>=0.27.0`
  - `pytest>=8.3.0`, `anyio>=4.5.0`
- No proprietary or undeclared private packages.

---

## 2. Test Suite & Verification Results

### A. Full Automated Test Execution
- **Command:** `pytest -v`
- **Total Tests Collected:** 90
- **Total Tests Passed:** 90
- **Total Tests Failed:** 0
- **Execution Time:** ~6.55 seconds
- **Network Calls:** 0 (all unit/integration tests operate completely offline).

### B. End-to-End Acceptance Demonstration
- **Command:** `python3 -m scripts.final_acceptance_demo`
- **Output:** Clean exit code `0`.
- **Milestones Demonstrated:** 14 / 14 passed.
- **Resource Cleanup:** All temporary SQLite and JSON document files were created in disposable directories via `tempfile.mkdtemp` and deleted cleanly on script termination.

### C. FastAPI Application & OpenAPI Schema
- **Command:** `python3 -c "from app.main import app; schema = app.openapi(); assert len(schema['paths']) == 18; print('OpenAPI OK')"`
- **Result:** `OpenAPI OK` (18 routes registered with complete request/response schemas).

---

## 3. Hygiene & Storage Isolation Verification

1. **No Hardcoded Machine Paths**: File resolution uses project-relative `Path("data/ct200_manual.pdf")` and `tempfile.TemporaryDirectory()`.
2. **Zero Tracked Local Databases**: Running `git status` after full test suite and demo execution confirms `working tree clean`. No `.sqlite`, `.db`, or temporary JSON files are committed.
3. **Deterministic Repeatability**: Running the test suite multiple times in succession produces identical results without test order dependencies or state contamination.
