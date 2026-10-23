# System Architecture & Technical Data Flow

**CardioTrack CT-200 Medical Device Document Intelligence and QA Test Generation Engine**

---

## 1. Architectural Overview

The system is a deterministic, version-aware Document Intelligence and Automated QA Traceability Engine built for technical medical device manuals. It processes digital PDF manuals, constructs immutable hierarchical document trees, tracks cross-version requirement modifications, generates structured QA test cases, and deterministically audits generated assertions against authoritative manual text.

### Architectural Tenets
1. **Deterministic Foundations:** Core PDF extraction, hierarchy construction, cryptographic hashing, version diffing, and source-grounding checks use deterministic algorithms rather than stochastic LLM calls or lossy OCR.
2. **Immutability & Provenance:** Ingested document revisions and source nodes are immutable once created. QA test cases are cryptographically bound via SHA-256 hashes to specific source snapshots.
3. **Transparent Failure & Explainability:** The system classifies requirement changes into granular categories (`NUMERIC_CHANGE`, `TIMING_CHANGE`, `TABLE_ROW`), clearly identifies unsupported assertions, and flags `human_review_required: true`.
4. **Offline First & Zero Cloud Lock-in:** Operates fully offline with zero external network calls using SQLite, atomic JSON file storage, and `MockLLMProvider`. Pluggable to remote LLM APIs (`OpenAICompatibleProvider`) and MongoDB when configured.

---

## 2. System Architecture Diagram

```mermaid
graph TD
    subgraph ClientLayer["Client & Evaluation Layer"]
        CLI["CLI Scripts<br/>(scripts/evaluator_demo.py)"]
        REST["HTTP REST API Client<br/>(Swagger / ReDoc / cURL)"]
        TEST["Automated Pytest Suite<br/>(tests/)"]
    end

    subgraph APILayer["FastAPI Application (app/main.py)"]
        DocRoutes["/api/v1/documents<br/>(Ingest, List, Sections, Impact)"]
        NodeRoutes["/api/v1/nodes<br/>(Inspect, Diff, Changes)"]
        SelRoutes["/api/v1/selections<br/>(CRUD, Pinning, Staleness, Impact)"]
        QARoutes["/api/v1/test-suites<br/>(Generate, Retrieve, Audit, Staleness)"]
    end

    subgraph ParsingLayer["Deterministic PDF Engine (app/services/pdf_parser.py)"]
        PDF["PDF Manuals<br/>(data/ct200_manual.pdf v1/v2)"] -->|pdfplumber geometry| Lines["Line Aggregation & Font Metrics"]
        Lines -->|Typography Rules| Hierarchy["Hierarchy Reconstruction<br/>(DEVICE → SEC → SUB → ROW)"]
        Hierarchy -->|Edge Case Handler| CleanTree["Clean Document Tree<br/>(Applies IR-1 through IR-7)"]
    end

    subgraph CoreServices["Domain Intelligence Services"]
        IngestSvc["Document Ingestion Service<br/>(app/services/document_ingestion.py)"]
        Matcher["Version Matcher<br/>(app/services/version_matcher.py)"]
        StalenessSvc["Staleness & Impact Analyzer<br/>(app/services/staleness_classifier.py)"]
        QASvc["QA Generation Service<br/>(app/services/qa_generation_service.py)"]
        Auditor["Grounding Auditor<br/>(app/services/grounding_auditor.py)"]
    end

    subgraph PersistenceLayer["Dual-Storage Persistence Layer"]
        subgraph RelationalDB["Relational Metadata (SQLite via SQLAlchemy)"]
            DocModel["Document & DocumentVersion"]
            NodeModel["LogicalNode & NodeVersion"]
            SelModel["Selection & SelectionNode"]
        end
        subgraph DocStore["Document Store (app/repositories/)"]
            JSONStore["JsonTestSuiteStore<br/>(Atomic replace, flock concurrency)"]
            MongoStore["MongoTestSuiteStore<br/>(Optional remote cluster)"]
        end
    end

    subgraph LLMAbstraction["LLM Provider Abstraction (app/services/llm_provider.py)"]
        MockLLM["MockLLMProvider<br/>(Deterministic, Offline, Zero-Cost)"]
        OpenAILLM["OpenAICompatibleProvider<br/>(Remote endpoint, Bounded Backoff)"]
    end

    CLI --> IngestSvc
    CLI --> QASvc
    REST --> APILayer
    TEST --> APILayer
    APILayer --> CoreServices

    IngestSvc --> PDF
    IngestSvc --> ParsingLayer
    IngestSvc --> RelationalDB

    Matcher --> RelationalDB
    StalenessSvc --> Matcher
    StalenessSvc --> RelationalDB

    QASvc --> LLMAbstraction
    QASvc --> Auditor
    QASvc --> DocStore
    QASvc --> RelationalDB

    Auditor --> RelationalDB
```

---

## 3. End-to-End Execution Sequence Diagram

The following sequence diagram traces the complete lifecycle of ingesting manuals, creating a selection, generating QA test cases, auditing claims, and evaluating staleness when a new revision is introduced.

```mermaid
sequenceDiagram
    autonumber
    actor Reviewer as Evaluator / Client
    participant API as FastAPI Router
    participant Ingest as Ingestion Service
    participant Parser as Deterministic PDF Parser
    participant DB as SQLite (SQLAlchemy)
    participant QA as QA Generation Service
    participant LLM as LLM Provider (Mock/OpenAI)
    participant Auditor as Grounding Auditor
    participant Store as JSON Document Store
    participant Classifier as Staleness Classifier

    %% Phase 1: Ingestion
    Note over Reviewer,DB: 1. Ingesting Manual Versions (v1 and v2)
    Reviewer->>API: POST /api/v1/documents/ingest?version=v1
    API->>Ingest: ingest_pdf(data/ct200_manual.pdf, version="v1")
    Ingest->>Parser: parse_pdf()
    Parser-->>Ingest: ExtractedDocument (27 nodes, 6 hierarchy levels)
    Ingest->>DB: Store Document, DocumentVersion, LogicalNodes, NodeVersions
    DB-->>API: DocumentVersion (v1, UUID=...)
    API-->>Reviewer: HTTP 201 Created (Ingestion Summary)

    Reviewer->>API: POST /api/v1/documents/ingest?version=v2
    API->>Ingest: ingest_pdf(data/ct200_manual_v2.pdf, version="v2")
    Ingest->>Parser: parse_pdf()
    Parser-->>Ingest: ExtractedDocument (28 nodes, +§5.3 Data Export)
    Ingest->>DB: Match LogicalNodes, Store v2 NodeVersions
    DB-->>API: DocumentVersion (v2, UUID=...)
    API-->>Reviewer: HTTP 201 Created (Ingestion Summary)

    %% Phase 2: Selection & Version Pinning
    Note over Reviewer,DB: 2. Pinning Requirements Scope (Selection)
    Reviewer->>API: POST /api/v1/selections (nodes=[§2.1.1.1, §3.2, §4.2], version=v1)
    API->>DB: Create Selection pinned to v1 NodeVersion snapshots
    DB-->>API: Selection (UUID=sel-001, pinned_version=v1)
    API-->>Reviewer: HTTP 201 Created

    %% Phase 3: QA Generation & Grounding Audit
    Note over Reviewer,Store: 3. Grounded QA Test Case Generation & Audit
    Reviewer->>API: POST /api/v1/selections/sel-001/test-suites
    API->>QA: generate_for_selection(sel-001, idempotency_key=...)
    QA->>DB: Fetch pinned v1 source node texts and SHA-256 hashes
    QA->>LLM: Generate QA cases (bounded 3 retries, Pydantic validation)
    LLM-->>QA: Structured QATestSuite (4 test cases)
    
    QA->>Auditor: audit_test_suite(suite, source_nodes)
    loop For each claim in test case
        Auditor->>Auditor: Canonicalize units & numbers
        Auditor->>Auditor: Check source match, derivation, or proposed setup
        Auditor->>Auditor: Detect unsupported tolerances, wrong citations, negations
    end
    Auditor-->>QA: GroundingAuditReport (33 claims: Supported, Derived, Setup, Unsupported)
    
    QA->>Store: Save full suite atomically (tmp file + os.replace)
    Store-->>QA: generation_id (UUID)
    QA-->>API: QATestSuiteResponse (suite + audit + provenance)
    API-->>Reviewer: HTTP 201 Created

    %% Phase 4: Cross-Version Staleness Analysis
    Note over Reviewer,Classifier: 4. Cross-Version Staleness & Impact Detection
    Reviewer->>API: GET /api/v1/test-suites/{generation_id}/staleness?target_version=v2
    API->>QA: evaluate_suite_staleness(generation_id, target_version=v2)
    QA->>Store: Retrieve original suite (pinned to v1 hashes)
    QA->>Classifier: Compare v1 source snapshot vs v2 target snapshot
    Classifier-->>QA: StalenessReport (4 Stale: 3 NUMERIC_CHANGE, 1 TIMING_CHANGE)
    QA-->>API: StalenessAssessment (IMPACTED, human_review_required=True)
    API-->>Reviewer: HTTP 200 OK (Detailed Parameter Shifts)
```

---

## 4. Component Details & Responsibility Matrix

The system enforces clear boundaries between deterministic logic, stochastic/model-driven generation, and operations requiring human review:

| Component | Primary File | Operation Type | Key Guarantees & Constraints |
| :--- | :--- | :--- | :--- |
| **PDF Extraction Engine** | `app/services/pdf_parser.py` | **Deterministic** | Extracts font geometry, size, and boldness via `pdfplumber`. Resolves all 7 structural irregularities (IR-1 through IR-7). Zero OCR or LLM hallucination. |
| **Relational Storage** | `app/db/models.py`, `app/repositories/` | **Deterministic** | SQLite with foreign key pragmas enforced. Generates SHA-256 hashes over canonicalized text. Ingesting duplicate versions returns `409 Conflict`. |
| **Version Matcher & Diff** | `app/services/version_matcher.py` | **Deterministic** | Multi-signal logical node matching (`section_number` exact match, heading similarity, hierarchy parentage). Computes unified diffs. |
| **Staleness Classifier** | `app/services/staleness_classifier.py` | **Deterministic** | 11 granular classifications with strict precedence (`TIMING_CHANGE` > `NUMERIC_CHANGE` > `WORDING_CHANGE`). Deterministic parameter shift extractor. |
| **LLM Provider Abstraction** | `app/services/llm_provider.py` | **Configurable** | `MockLLMProvider` is 100% deterministic and offline. `OpenAICompatibleProvider` implements bounded exponential backoff (max 3 retries). |
| **QA Generation Service** | `app/services/qa_generation_service.py` | **Model + Rules** | Enforces strict PascalCase Pydantic contracts (`TestCaseId`, `Steps`, `ExpectedResult`). Injects anti-injection boundaries. Idempotency enforced via SHA-256 keys. |
| **Grounding Auditor** | `app/services/grounding_auditor.py` | **Deterministic** | 5-state claim evaluation (`SOURCE_SUPPORTED`, `DERIVED_WITH_EXPLANATION`, `PROPOSED_SETUP`, `UNSUPPORTED`, `AMBIGUOUS`). Unit/number canonicalization, negation detection. |
| **Document Store** | `app/repositories/json_test_suite_store.py` | **Deterministic** | Atomic filesystem write (`.tmp` write followed by `os.replace`). File-level advisory locking prevents write interleaving. |
| **Human Review Gate** | UI / Reviewer Step | **Human Required** | Triggered whenever `human_review_required: true` is set (e.g., numerical shifts, timing deltas, unsupported tolerances, or missing provenance). |

---

## 5. Persistence Architecture & Concurrency Model

### 1. Relational Layer (SQLite via SQLAlchemy)
- Stores structural entities: `Document`, `DocumentVersion`, `LogicalNode`, `NodeVersion`, `Selection`, `SelectionNode`.
- Preserves relational integrity through foreign key cascades (`PRAGMA foreign_keys=ON`).
- Guarantees immutability: once written, `NodeVersion` rows are read-only. Modifying a requirement produces a new `NodeVersion` associated with a new `DocumentVersion`.

### 2. Document Store Layer (JSON with Optional MongoDB)
- Stores nested, schema-rich `QATestSuite` objects containing test cases, execution steps, parameter limits, provenance dictionaries, and grounding audit reports.
- **Atomic File Writing:** Writes to `{test_suite_id}.json.tmp` and executes an atomic POSIX filesystem rename (`os.replace`) to ensure crash consistency.
- **Advisory File Locking:** Employs `fcntl.flock` (exclusive lock during write) to guard against concurrent writer collisions.
- **Corrupted File Defense:** If a JSON file is manually damaged or zero-byte truncated, the store logs a structured diagnostic and raises `TestSuiteStoreError` rather than crashing silently.

---

## 6. Safety, Intended Use & Medical Device Disclaimer

> [!CAUTION]
> **Regulatory Disclaimer:**  
> This software is an engineering assignment prototype developed for the Tri9T AI Internship Assignment. It has **not** been certified, cleared, or validated under:
> - FDA 21 CFR Part 820 (Quality System Regulation)
> - IEC 62304 (Medical Device Software Lifecycle)
> - ISO 13485 (Medical Devices Quality Management)
> - ISO 14971 (Application of Risk Management to Medical Devices)
>
> All test assertions, parameter tolerances, and safety classifications generated by this system must be verified and approved by a qualified biomedical verification engineer prior to physical execution on test bench hardware or clinical instruments.
