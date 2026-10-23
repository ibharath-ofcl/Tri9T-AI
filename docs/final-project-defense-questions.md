# CardioTrack CT-200 — Technical Defense & Question Bank

---

## Part 1: Project Pitches

### The One-Minute Pitch (Spoken Duration: ~60 seconds)
> "In medical device software engineering, translating technical manuals into verification tests is high-stakes and labor-intensive. When device revisions occur, subtle specification changes—like battery life dropping from 300 to 250 cycles or inflation steps shifting from 40 to 30 mmHg—are easily overlooked. Furthermore, using generative AI to draft test cases introduces hallucination risks, such as inventing ungrounded tolerances like $\pm2\text{ mmHg}$.
>
> To solve this, we built the CardioTrack CT-200 Document Intelligence and QA Generation Engine. Our system deterministically parses complex device manuals into structured document hierarchies, maintains immutable version lineage in SQLite, and generates structured QA test candidates. Crucially, it binds every assertion to cryptographic source hashes and audits claims through a deterministic 5-state grounding engine.
>
> When revisions are released, our staleness classifier automatically flags impacted test cases and highlights exact parameter deltas. All 90 automated tests, 14 demo milestones, and 18 API endpoints pass with 100% offline reproducibility. Our principal limitation is that our grounding auditor relies on deterministic rules for numerical parameters and units rather than deep natural language inference, ensuring conservative routing to human engineers for final review."

---

### The Three-Minute Pitch (Spoken Duration: ~180 seconds)
> "Good morning. I am presenting the CardioTrack CT-200 Document Intelligence and QA Generation Engine, an engineering solution designed to establish strict, explainable traceability between medical device manuals and automated QA test suites.
>
> In regulated medical software verification, QA engineers face three major challenges when working with technical PDF manuals:
> First, PDFs are unstructured display artifacts. They contain typography irregularities such as numbering gaps—for example, Section 2.1.1.1 jumping directly under Section 2.1 without a parent—body-sized section headings, split tables, and duplicate titles.
> Second, device revisions create silent requirement drift. Between CT-200 v1 and v2, six safety-critical changes occur: battery cycles drop from 300 to 250, low-battery alerts change from 15% to 10%, cuff inflation steps drop from 40 to 30 mmHg, overpressure auto-deflation accelerates from 2.0 to 1.5 seconds, error code E6 is added, and Section 5.3 Data Export is introduced. Without machine-readable lineage, test suites written for v1 are mistakenly run against v2 hardware.
> Third, LLMs hallucinate. When drafting test cases, LLMs frequently invent unsupported tolerances or confuse operating modes.
>
> Our platform addresses these hurdles through a five-stage deterministic pipeline:
> 1. A typography-aware parser built on `pdfplumber` character geometry extracts the document hierarchy and deterministically resolves all seven identified structural edge cases.
> 2. An immutable relational versioning model in SQLite stores version snapshots, tracks logical node lineage, and computes SHA-256 cryptographic hashes over normalized content.
> 3. QA engineers curate version-pinned named selections that lock test scopes to specific immutable snapshots, preventing them from silently sliding across revisions.
> 4. Our QA generation engine produces structured PascalCase test cases, binding every single assertion to the source node UUID and content hash.
> 5. A deterministic grounding auditor evaluates every claim into five explicit states: Source Supported, Derived with Explanation, Proposed Setup, Unsupported, or Ambiguous. When an assertion includes fabricated tolerances or altered error codes, it is immediately caught and routed for human review.
>
> Finally, our staleness classifier evaluates pinned test suites against new document versions, automatically identifying modified requirements and explaining the exact deltas.
>
> The entire engine is verified by 90 automated unit tests, a 14-milestone acceptance demo, 18 documented OpenAPI endpoints, and runs 100% offline with zero external dependencies. While our grounding is rule-based and requires human engineering sign-off, it provides a trustworthy, version-safe foundation for regulated QA automation."

---

## Part 2: Technical Defense Questions & Answers

### Group 1: Problem Statement & Motivation

#### Q1: What core problem does this project solve?
**Answer:** It automates the extraction of structured technical specifications from medical device PDF manuals, binds generated QA test suites to immutable document snapshots via cryptographic hashes, and automatically identifies test cases that become stale or invalid when product revisions are released.

#### Q2: Why is ordinary PDF text extraction or standard RAG insufficient?
**Answer:** Standard PDF extractors discard typographic layout, merging headings into body text and garbling split tables. Standard RAG uses vector similarity search, which cannot guarantee that an assertion like `30 mmHg` is cited against the correct version or section, often blending v1 and v2 specifications due to semantic closeness.

#### Q3: Who are the intended users, and what is the system's operational boundary?
**Answer:** Intended users are medical device Software Verification and Validation (V&V) engineers and QA architects. The system is strictly an engineering verification tool; it does not perform clinical diagnosis, patient care, or hardware firmware modification.

---

### Group 2: Architecture & Design Decisions

#### Q4: What are the principal components of the system architecture?
**Answer:** 
1. **PDF Ingestion Engine:** Typography and character layout parser (`pdfplumber`).
2. **Relational Version Store:** SQLAlchemy ORM models with SQLite backing.
3. **Version Matcher & Lineage Engine:** Multi-signal node matcher across document revisions.
4. **Selection Repository:** Pinned requirements subset manager.
5. **QA Generation Service:** Pluggable LLM abstraction with bounded retries.
6. **Deterministic Grounding Auditor:** 5-state claim verification engine.
7. **Document Store:** Atomic JSON store with flock concurrency protection.
8. **REST Interface:** FastAPI application with 18 OpenAPI endpoints.

#### Q5: Why is the pipeline split between deterministic parsing/grounding and generative LLM generation?
**Answer:** Generative models are creative and suited for synthesizing test steps and preconditions, but they are stochastic and prone to hallucinating safety numbers. Deterministic code, by contrast, is completely reproducible and verifiable. We use LLMs only to draft candidate structures, while all document parsing, version matching, provenance checks, and grounding audits are 100% deterministic code.

#### Q6: Why did you choose SQLite and local atomic JSON storage rather than a cloud database?
**Answer:** To ensure 100% reproducibility in academic, evaluator, and air-gapped test environments. SQLite requires zero daemon configuration, enforces foreign keys, and provides ACID compliance. The atomic JSON store uses temporary file writes followed by atomic `os.replace` and `fcntl.flock`, guaranteeing zero corrupted records without requiring MongoDB or PostgreSQL services.

---

### Group 3: PDF Parsing & Document Hierarchy

#### Q7: How does the PDF parser reconstruct a multi-level document hierarchy?
**Answer:** It extracts text characters with font family, size, coordinates, and bounding boxes via `pdfplumber`. It identifies structural headings through regular expressions and font-size clustering, maintaining an active hierarchy stack (from Level 0 `DEVICE` to Level 5 `TABLE_ROW`) to build an Abstract Syntax Tree (AST) representing the document.

#### Q8: How does the parser handle typography edge case IR-1 (the Section 2.1.1.1 numbering gap)?
**Answer:** In CT-200 v1, Section 2.1 jumps directly to 2.1.1.1 without a Section 2.1.1. Rather than throwing an orphaned node error or fabricating a phantom section, the parser detects that the parent prefix `2.1` matches an existing ancestor, attaches 2.1.1.1 directly under 2.1, and emits an explanatory diagnostic warning.

#### Q9: How are body-sized headings (like Section 3.2 in 11pt font) identified?
**Answer:** Heading detection does not rely solely on font size. The parser combines typographic weight (boldness), leading numbering syntax (`^\d+\.\d+`), and preceding/trailing whitespace to correctly classify Section 3.2 as a Level-2 section heading despite sharing the 11pt size of body text.

#### Q10: How does the system prevent phantom tables and cross-page text continuation errors?
**Answer:** Phantom tables caused by decorative border rectangles are filtered out using geometric enclosure thresholds (requiring distinct multi-cell line intersections). Multi-page sections are handled by checking whether a page starts with a continuation paragraph rather than a new heading; if continuation is detected, the body text is appended to the active section node.

---

### Group 4: Versioning, Snapshots & Staleness

#### Q11: How are document versions and logical nodes represented in the database?
**Answer:** We separate identity from state:
- `DocumentModel` represents the conceptual device manual.
- `DocumentVersionModel` represents an immutable revision (v1, v2).
- `LogicalNodeModel` represents a conceptual section that persists across revisions.
- `NodeVersionModel` represents the exact snapshot of that section in a specific version, storing normalized title, body, tables, and a SHA-256 content hash.

#### Q12: How do you guarantee the immutability of historical snapshots when a new version is ingested?
**Answer:** Ingestion of v2 inserts new `DocumentVersionModel` and `NodeVersionModel` rows. Existing v1 rows are strictly read-only and are never updated or overwritten. If an identical document version is ingested again, the engine either replays the existing record idempotently or rejects conflicting checksums with `HTTP 409 Conflict`.

#### Q13: How does cross-version logical node matching work?
**Answer:** The `VersionMatcher` applies a multi-signal scoring algorithm: exact section number match, exact title match, fuzzy title similarity, and hierarchical parent alignment. If confidence is high, a `NodeLineageModel` link is created. If matching is ambiguous, it is flagged as `AMBIGUOUS_LINEAGE` rather than falsely pairing unrelated sections.

#### Q14: What is the difference between a stale selection and an unsupported claim?
**Answer:** 
- An **unsupported claim** is an assertion that has no factual basis in its *pinned* source snapshot (e.g., claiming $\pm2\text{ mmHg}$ when v1 specifies no tolerance).
- A **stale selection** occurs when a test case was valid against its pinned version (v1), but the underlying requirement has modified, moved, or been removed in a *subsequent* target version (v2).

---

### Group 5: Grounding, Hashes & Provenance

#### Q15: How are source-node UUIDs and cryptographic content hashes bound to generated test cases?
**Answer:** Every test case includes a `provenance` dictionary containing `source_node_version_id`, `section_number`, and `source_content_hash`. The content hash is the SHA-256 digest of the normalized text and table data of that specific node snapshot.

#### Q16: What happens when a source hash is tampered with or points to a differing version?
**Answer:** During the grounding audit, the auditor fetches the actual `NodeVersionModel` by UUID from the database, recomputes the SHA-256 hash, and compares it to the assertion's claimed hash. If they do not match, the claim is flagged as `UNSUPPORTED` with a tamper alert, and `human_review_required` is set to `true`.

#### Q17: What are the 5 grounding categories, and why is this granularity necessary?
**Answer:** 
1. `SOURCE_SUPPORTED`: Number, unit, and condition directly found in authoritative section text.
2. `DERIVED_WITH_EXPLANATION`: Arithmetic step progression with explicit formula and base value.
3. `PROPOSED_SETUP`: External laboratory fixture/equipment (distinguished from device requirement).
4. `UNSUPPORTED`: Hallucinated tolerance, invented error code, or wrong unit.
5. `AMBIGUOUS`: Unresolved cross-references or conflicting thresholds.
This granularity prevents false rejections of legitimate lab equipment setups (e.g. pressure calibrators) while preventing them from being confused with manufacturer specifications.

#### Q18: How does the auditor distinguish a manufacturer specification from a proposed laboratory test fixture?
**Answer:** It inspects prerequisite apparatus and setup equipment tags (e.g., calibrated manometers, stopwatch, Fluke simulators). If an equipment parameter is marked as a test fixture and does not contradict manual operating ranges, it is categorized as `PROPOSED_SETUP` rather than being falsely rejected as an ungrounded device specification.

---

### Group 6: QA Test Generation & Mock LLM Provider

#### Q19: Why does the project use a mock LLM provider by default?
**Answer:** For deterministic, 100% reproducible evaluation. Live LLMs introduce non-deterministic wording variations, API rate limits, network latency, and billing costs. The `MockLLMProvider` generates structured test cases grounded in actual CT-200 specifications without requiring internet connectivity or API keys. Live OpenAI models can be enabled by setting `LLM_PROVIDER=openai`.

#### Q20: How does the system enforce schema conformity and handle LLM generation retries?
**Answer:** Responses are parsed through strict Pydantic models (`TestCaseSchema`, `QAUnitTestSuiteSchema`) requiring PascalCase fields, bounded test case counts (3–5), and non-empty prerequisites/steps. If validation fails, the service performs bounded corrective retries (up to 3 attempts), feeding the validation errors back into the prompt.

#### Q21: How is idempotency enforced during test generation?
**Answer:** Clients can supply an `idempotency_key`. The service hashes the key along with the selection ID and generation parameters. Replaying the identical key returns the cached test suite immediately. If a client attempts to submit differing parameters with an existing key, the service rejects the request with an `HTTP 409 Conflict`.

---

### Group 7: Database, API, Testing & Reproducibility

#### Q22: How are the 18 API routes structured, and how are errors handled?
**Answer:** Routes follow RESTful design across `/api/v1/documents`, `/api/v1/nodes`, `/api/v1/selections`, and `/api/v1/test-suites`. Errors return standardized HTTP status codes (400 Bad Request, 404 Not Found, 409 Conflict, 422 Unprocessable Entity) with structured JSON error details, avoiding raw tracebacks or sensitive server path leaks.

#### Q23: How do you ensure 100% offline reproducibility across test and demo runs?
**Answer:** All dependencies are local Python packages pinned in `requirements.txt`. Default configurations use in-memory SQLite and local JSON files. Test runs execute in isolated disposable scratch directories that are automatically created and cleaned up, ensuring zero residue on the host machine.

#### Q24: What test suites exist, and what evidence proves that the system works?
**Answer:** 90 automated tests across 11 test modules:
- Parser Edge Cases: 7 tests (IR-1 through IR-7).
- PDF Parser: 6 tests (typography, geometry, tables).
- Versioning & Ingestion: 8 tests (models, lineage, rollbacks).
- Versioning API: 5 tests (REST endpoints, search, diff).
- Selections: 8 tests (CRUD, pinning, immutability).
- Impact & Selection API: 3 tests (lifecycle, validation, staleness).
- Staleness Classifier: 11 tests (precedence hierarchy, deltas).
- QA Generation: 15 tests (Pydantic schema, retries, idempotency, persistence).
- Grounding Audit: 9 tests (5-state categorization, cross-store audit).
- Adversarial Red-Team: 14 tests (14 attack vectors).
- Base API: 4 tests (health, previews, errors).

---

### Group 8: Security, Medical Safety Boundaries & Limitations

#### Q25: How does the system handle prompt-injection attacks embedded within PDF text?
**Answer:** Extracted text is stored strictly as passive string data inside AST nodes and database records. When constructing prompts, document content is enclosed in delimited data blocks, and prompt injection tokens (e.g. `<SYSTEM>Ignore previous instructions</SYSTEM>`) are treated as literal text content, neutralizing execution attacks.

#### Q26: Why are generated test cases classified as candidates rather than certified verification evidence?
**Answer:** Medical device software verification must comply with formal quality management systems (e.g., FDA 21 CFR Part 820.30 and IEC 62304). AI tools cannot legally or ethically replace qualified human verification engineers. Generating candidate test cases accelerates engineering productivity, but human engineers must review and sign off before tests are run on physical hardware.

#### Q27: What are the known technical limitations, and what is the future roadmap?
**Answer:** 
1. **Rule-Based Grounding:** Canonicalizes numbers, units, and tolerances, but subtle semantic shifts in unstructured natural language require human engineering review.
2. **Typography-Bound Parsing:** Does not perform optical character recognition (OCR) on scanned bitmap PDFs.
3. **Storage Concurrency:** SQLite file locking serializes concurrent writes; multi-user production environments require PostgreSQL.
*Future roadmap:* Integrate multimodal OCR for scanned documents, implement LLM-as-judge semantic auditing with formal confidence scoring, and support distributed PostgreSQL storage.
