# Stage 7 QA Generation, Failure Recovery & Persistence Audit

**Date:** October 2026  
**Auditor:** Skeptical Assignment Reviewer & Senior Backend Engineer  
**Subsystems Audited:**
- `app/services/qa_generation_service.py`
- `app/services/llm_provider.py`
- `app/repositories/json_test_suite_store.py`
- `app/repositories/mongo_test_suite_store.py`
- `app/schemas/qa_test_case.py`
- `app/prompts/qa_generation.py`

---

## 1. LLM Generation & Validation Invariants

### A. Strict Schema Contracts
- **Pydantic Validation**: Every generated test case is parsed into `TestCaseSchema`, enforcing exact field presence: `TestCaseId`, `Title`, `Prerequisites`, `Steps`, `ExpectedResult`, `PassFailCriteria`, and `StandardRef`.
- **Count Enforcement**: The generator strictly rejects request counts outside the 3 to 5 range (`ValueError: Requested test case count must be between 3 and 5`).
- **Duplicate Detection**: Validates that all generated `TestCaseId` values and `Title` values within a suite are unique.

### B. Bounded Corrective Retries
- **Bound**: Exactly 3 total model attempts (`max_attempts = 3`).
- **Corrective Feedback**: If an attempt fails Pydantic validation (e.g. malformed JSON, missing fields, duplicate IDs), `build_retry_prompt` feeds the specific Pydantic errors back to the model for correction.
- **Exhaustion Behavior**: If the model fails 3 consecutive times, `GenerationValidationError` is raised. No corrupted or incomplete suite is ever recorded as successful.

### C. Idempotency & Request Fingerprinting
- **Deterministic SHA-256 Fingerprinting**: Combines sorted source node hashes, requested count, prompt version, provider name, model name, and optional focus topic into a single cryptographic hash.
- **Idempotent Replay**: Repeating a request with the same `idempotency_key` and matching fingerprint returns the previously persisted suite immediately without invoking the LLM provider.
- **Conflict Enforcement**: Reusing an `idempotency_key` with differing generation parameters (e.g., changed count or different source nodes) immediately raises `IdempotencyConflictError` (`HTTP 409 Conflict`).

### D. Offline Mock Provider vs Live Integration
- **Default Offline Mock**: `MockLLMProvider` generates 100% deterministic, source-grounded synthetic cases adhering to CT-200 specifications with explicit `[PROPOSED SETUP]` tags for lab fixtures. It requires no network access and zero paid API keys.
- **Live Integration Provider**: `OpenAICompatibleProvider` connects to any standard OpenAI-compatible API, using exponential backoff (1s, 2s, 4s) on transient HTTP 429/5xx errors while failing immediately without retry on HTTP 401 Unauthorized. API keys are loaded via environment variables and never logged or serialized.

---

## 2. Document Store Persistence & Failure Behavior

### A. Atomic Filesystem JSON Store (`JsonTestSuiteStore`)
- **Write-Rename Pattern**: Suites are serialized to a temporary `.tmp` file in the store directory, synced to disk, and atomically renamed to `<generation_id>.json`. This guarantees that partial or interrupted writes never produce corrupt documents.
- **Concurrency Locking**: Multi-process writes use platform advisory locking (`fcntl.flock` on POSIX systems) to synchronize index catalog writes.
- **Corrupt File Resilience**: If an individual document file is corrupted, the store logs a warning, skips the damaged file, and rebuilds its in-memory index from valid files without crashing.

### B. Decoupled MongoDB Store (`MongoTestSuiteStore`)
- **Lazy Initialization**: MongoDB connection is established only when explicitly configured (`DOCUMENT_STORE_BACKEND=mongodb`).
- **Graceful Fallback**: If `pymongo` is not installed or the MongoDB server is unreachable, initialization raises an informative configuration error without impacting the default JSON store.

### C. Cross-Store Failure Recovery Model
- **Honest Decoupled Transaction Model**: SQLite stores relational metadata (documents, versions, nodes, selections), while the document store holds generated QA test suites. Because these two systems do not share a two-phase commit coordinator, `QAGenerationService` enforces that the document store write must complete successfully before returning.
- **Failure Behavior**: If `store.save_test_suite` fails (e.g. disk full, permission denied), `QAGenerationService` catches the error, logs the failure, and raises `RuntimeError("Document store persistence failed: ...")`. It does NOT return a false successful response.
