# Stage 1 — Repository Audit & Local CT-200 Dataset Analysis

**Project:** Tri9T AI Internship Assignment — Document Intelligence for CT-200 Medical Device Manual  
**Date:** 2026-10-22  
**Author:** Automated analysis  
**Status:** Stage 1 Complete

---

## 1. Executive Summary

This report documents the complete Stage 1 inspection of the Tri9T-AI repository and the CT-200 blood-pressure-monitor technical manuals (v1 and v2). Both PDFs are digitally generated, fully text-extractable without OCR, and contain **seven confirmed structural irregularities** that the parser must handle. The v2 manual introduces **eight distinct changes** spanning safety-critical numeric thresholds, a new error code, a new section, and timing parameter modifications. The architecture proposed uses FastAPI + SQLAlchemy/SQLite for versioned document trees with MongoDB for LLM-generated output, font-based heading detection for hierarchy reconstruction, and structural-path + content-hash matching for cross-version traceability.

---

## 2. Repository Audit (Task A)

### 2.1 Project Root and Structure

```
Tri9T-AI/
├── .git/
├── .DS_Store
└── data/
    ├── ct200_manual.pdf          (v1 manual)
    ├── ct200_manual_v2.pdf       (v2 manual)
    └── IMPORTANT_ASSIGNMENT_UPDATE (Read to check MD).txt
```

### 2.2 Git Status

| Property | Value |
|---|---|
| Branch | `main` |
| Commits | **None** (empty repo — no commits yet) |
| Remote | `origin` → `https://github.com/ibharath-ofcl/Tri9T-AI.git` |
| Working tree | Untracked files: `.DS_Store`, `data/` |
| Existing code | **None** — no application code, README, dependencies, tests, or `.env` files |
| Push access | Remote configured; push not yet tested (no commits exist) |

### 2.3 Key Findings

- The repository is a clean, empty initialization — no prior implementation to preserve.
- Git remote is correctly configured for `ibharath-ofcl/Tri9T-AI`.
- No `.gitignore`, `requirements.txt`, `pyproject.toml`, `README.md`, or environment files exist yet.
- No secrets, credentials, or sensitive files detected.

---

## 3. Input Inventory (Task B)

### 3.1 Complete File Listing

| Relative Path | Extension | Size | Type | Readable |
|---|---|---|---|---|
| `data/ct200_manual.pdf` | `.pdf` | 433 KB | **CT-200 v1 manual** (primary input) | ✅ Yes |
| `data/ct200_manual_v2.pdf` | `.pdf` | 437 KB | **CT-200 v2 manual** (primary input) | ✅ Yes |
| `data/IMPORTANT_ASSIGNMENT_UPDATE (Read to check MD).txt` | `.txt` | 821 B | Assignment instruction update | ✅ Yes |

### 3.2 SHA-256 Checksums

```
0504d713306e99e722d03cd763a0a743e9459bc2763dfd5d53dd6d0f7b18ea22  data/ct200_manual.pdf
b0c7aa72f11c6a32fa305e9a1756c16dd5e538c637e1061d86c03bd02910444f  data/ct200_manual_v2.pdf
```

### 3.3 Assignment Update Note

The update file clarifies that the assignment requires **parsing PDF directly** (not Markdown), reconstructing document hierarchy using PDF parsing and/or OCR techniques to simulate real-world regulatory document processing.

### 3.4 Exact Manual Paths

- **v1:** `data/ct200_manual.pdf` — 6 pages, 433 KB
- **v2:** `data/ct200_manual_v2.pdf` — 7 pages, 437 KB

---

## 4. Text Extraction and OCR Assessment

### 4.1 Extraction Method Evaluation

| Property | v1 | v2 |
|---|---|---|
| Pages | 6 | 7 |
| Total characters (pdfplumber) | ~6,022 | ~6,579 |
| Empty/near-empty pages | None | Page 7 (80 chars — sentence overflow from page 6) |
| Font type | Nimbus Sans (Regular + Bold), Noto Serif Regular (dash/special chars) | Same |
| Generation method | **Digitally generated** (not scanned) | **Digitally generated** |
| OCR required | **No** | **No** |
| Text extraction reliability | **High** — clean Unicode, no ligatures/artifacts | **High** |

### 4.2 Font Hierarchy Discovered

| Font | Size (pt) | Role |
|---|---|---|
| Nimbus Sans Bold | 22.0 | Document title (page 1 only) |
| Nimbus Sans Bold | 16.5 | **Level-1 section headings** (e.g., "1. Device Overview") |
| Nimbus Sans Bold | 12.9 | **Level-2 subsection headings** (e.g., "1.1 Intended Use") |
| Nimbus Sans Bold | 11.0 | **Anomalous headings** + table headers + bold inline text |
| Nimbus Sans Regular | 11.0 | Body text |
| Noto Serif Regular | 11.0 | Special characters (en-dashes, em-dashes, ≤/≥) |

### 4.3 Table Detection

| Location | Table Content | Extraction Quality |
|---|---|---|
| v1 Page 2 / v2 Page 2 | 2.1 General Specifications (7 rows, 2 columns) | **Primary table extracts correctly.** 6 phantom sub-tables also detected (fragments) |
| v1 Page 4 / v2 Page 4 | 4.2 Error Codes (5 rows v1, 6 rows v2, 3 columns) | **Primary table extracts correctly.** 2-4 phantom sub-tables also detected |

**Key finding:** pdfplumber detects phantom tables from cell-internal text boundaries. The parser must use the primary table (largest bounding box with header row) and discard fragment tables.

---

## 5. CT-200 v1 Manual — Complete Structural Inspection (Task C)

### 5.1 Document Hierarchy (v1)

```
CardioTrack CT-200 Home Blood Pressure Monitor — Technical & User Manual
├── 1. Device Overview
│   ├── 1.1 Intended Use
│   └── 1.2 Indications and Contraindications
├── 2. Physical and Electrical Specifications
│   ├── 2.1 General Specifications
│   │   └── 2.1.1.1 Battery Life Under Typical Use  ⚠️ ANOMALY
│   └── 2.2 Cuff Specifications
├── 3. Device Operation
│   ├── 3.1 Powering On and Profile Selection
│   ├── 3.2 Cuff Inflation Sequence  ⚠️ ANOMALY (font size)
│   ├── 3.4 Auto Shutoff  ⚠️ ANOMALY (out of order)
│   └── 3.3 Result Display and Classification  ⚠️ ANOMALY (out of order)
├── 4. Alarms and Safety Behavior
│   ├── 4.1 Overpressure Protection
│   ├── 4.2 Error Codes
│   └── 4.3 Alarm Thresholds
├── 5. Data Management
│   ├── 5.1 Local Storage
│   └── 5.2 Bluetooth Sync
├── 6. Maintenance and Cleaning
│   ├── 6.1 Cleaning Instructions
│   └── 6.2 Calibration
├── 7. Troubleshooting
│   ├── 7.1 Error Codes  ⚠️ ANOMALY (duplicate heading text)
│   └── 7.2 Inconsistent Readings
└── 8. Regulatory Information
    └── 8.1 Classification
```

### 5.2 Confirmed Structural Irregularities (v1)

#### IR-1: Section Numbering Gap — 2.1.1.1 (Missing 2.1.1)

| Field | Detail |
|---|---|
| **PDF page** | 2 |
| **Section** | 2.1.1.1 Battery Life Under Typical Use |
| **Evidence** | Subsection "2.1.1.1" exists under "2.1", but there is no "2.1.1" parent. The numbering jumps from level-2 (2.1) directly to level-4 (2.1.1.1). |
| **Font** | Nimbus Sans Bold @ **11.0pt** (body text size), NOT the expected 12.9pt for subsections |
| **Impact** | Parser must decide: Is this a level-3 or level-4 heading? Where does it nest? The missing intermediate levels create ambiguity in parent assignment. |
| **Recommended handling** | Treat as child of 2.1 (the nearest ancestor with a valid section number). Flag the missing 2.1.1 and 2.1.1 levels as a structural anomaly. Assign low confidence. |
| **Test** | Verify parser places 2.1.1.1 under 2.1. Verify a warning is emitted about the numbering gap. |

#### IR-2: Heading Font Size Inconsistency — Section 3.2

| Field | Detail |
|---|---|
| **PDF page** | 3 |
| **Section** | 3.2 Cuff Inflation Sequence |
| **Evidence** | Section 3.2 uses Nimbus Sans Bold @ **11.0pt** (body text size), while all other x.y sections use 12.9pt. |
| **Impact** | A font-size-only heading detector would miss this heading entirely, collapsing its content into 3.1. |
| **Recommended handling** | Heading detection must combine font analysis with section-number regex patterns (e.g., `^\d+\.\d+`). When a line matches a section-number pattern and is bold, it should be classified as a heading regardless of font size. |
| **Test** | Verify 3.2 is detected as a heading. Verify its content is not merged into 3.1. |

#### IR-3: Out-of-Order Section Numbering — 3.4 Before 3.3

| Field | Detail |
|---|---|
| **PDF page** | 3 |
| **Sections** | 3.4 Auto Shutoff appears **before** 3.3 Result Display and Classification |
| **Evidence** | In the PDF reading order, section 3.4 (top=211) precedes 3.3 (top=303). Both are correctly formatted as 12.9pt bold headings. |
| **Impact** | A parser that enforces ascending section order would either reorder them (changing document fidelity) or flag an error. The document's actual reading order must be preserved. |
| **Recommended handling** | Preserve the original document order. Store both the document-order position and the section-number for each node. Emit a warning about the sequencing anomaly. Do not silently reorder. |
| **Test** | Verify 3.4 appears before 3.3 in the tree. Verify both are children of section 3. Verify a warning is emitted. |

#### IR-4: Duplicate Heading Text — "Error Codes" (4.2 and 7.1)

| Field | Detail |
|---|---|
| **PDF pages** | 4 (section 4.2) and 6 (section 7.1) |
| **Evidence** | Both sections are titled "Error Codes" but have different parent sections (4. Alarms vs. 7. Troubleshooting) and different content (4.2 is a table of codes; 7.1 is troubleshooting guidance). |
| **Impact** | Heading-text-only matching across versions would create false matches. The logical identity must incorporate the structural path (parent section), not just the heading text. |
| **Recommended handling** | Use full structural path (`4.2 > 4 > root` vs `7.1 > 7 > root`) and section number as primary identity. Heading text alone is insufficient. |
| **Test** | Verify 4.2 and 7.1 are distinct nodes. Verify version-matching does not conflate them. |

#### IR-5: Table Extraction Phantoms

| Field | Detail |
|---|---|
| **PDF pages** | 2 (7 tables detected, 1 real) and 4 (5 tables detected, 1 real) |
| **Evidence** | pdfplumber detects phantom sub-tables from individual cells of the specification and error-code tables. For example, `['Pressure', 'range']` is detected as a separate table. |
| **Impact** | Naively trusting `find_tables()` results would produce duplicate, fragmented data. |
| **Recommended handling** | Filter tables: accept only those with ≥2 rows AND a plausible header row. Discard single-row fragments and tables whose bounding box is fully contained within another table's bounds. |
| **Test** | Verify exactly 1 table is extracted from page 2 (specs) and 1 from page 4 (error codes). Verify phantom tables are discarded. |

#### IR-6: Numbered List Within Section 3.3

| Field | Detail |
|---|---|
| **PDF page** | 3 |
| **Section** | 3.3 Result Display and Classification |
| **Evidence** | Contains a numbered list (1–5) for blood pressure classifications. These numbers must not be confused with section numbers. |
| **Impact** | A parser that treats any `N.` pattern as a section number could create spurious child nodes. |
| **Recommended handling** | Section-number detection must require bold formatting AND context (not indented paragraph text). List items should be captured as body content of 3.3, not as separate nodes. |
| **Test** | Verify the 5 classification items are body content of 3.3, not child sections. |

#### IR-7: Cross-Page Content Continuation

| Field | Detail |
|---|---|
| **PDF pages** | Multiple (2→3, 3→4, 4→5, 5→6) |
| **Evidence** | Section 3.1 starts on page 2 and continues on page 3. Section 4.3 starts on page 4 and continues on page 5. Section 6.1 starts on page 5 and continues on page 6. |
| **Impact** | Page-at-a-time extraction will split paragraphs. The parser must stitch content across page boundaries. |
| **Recommended handling** | After page-level extraction, merge text for sections that span page boundaries. Detect continuation by checking if a page ends mid-sentence (no terminal heading) and the next page begins with continuation text (lowercase, no section number). |
| **Test** | Verify section 3.1's body text includes content from both pages 2 and 3. |

---

## 6. CT-200 v2 Manual — Complete Structural Inspection (Task D)

### 6.1 Document Hierarchy (v2)

The v2 hierarchy is identical to v1 except:
- **Added:** Section 5.3 (Data Export)
- **Added:** Error code E6 in section 4.2 table
- All seven v1 structural irregularities (IR-1 through IR-7) are **reproduced identically** in v2.

### 6.2 V2-Specific Observations

- v2 has **7 pages** (v1 has 6) — the added 5.3 section and E6 table row push content to a 7th page.
- Page 7 contains only the final sentence of section 8.1 Classification (80 chars) — an extreme cross-page continuation.
- The v2 page 3 has no Level-1 heading (section 4 moved to page 4), while v1 page 3 has section 4's heading at bottom.

---

## 7. Preliminary V1 → V2 Change Inventory (Task D continued)

### 7.1 Change Summary

| # | Location | Section | Category | V1 Value | V2 Value | Safety Impact |
|---|---|---|---|---|---|---|
| **C-1** | §2.1.1.1 | Battery Life | **Numeric threshold** | 300 measurement cycles | 250 measurement cycles | Low — usability |
| **C-2** | §2.1.1.1 | Battery Life | **Added text** | (not present) | "— revised downward from earlier estimates after extended field testing" | Low — informational |
| **C-3** | §2.1.1.1 | Battery Icon | **Numeric threshold** | falls below 15% | falls below 10% | **Medium** — later warning |
| **C-4** | §3.2 | Inflation Increment | **Numeric threshold** | 40 mmHg increments | 30 mmHg increments | **High** — device behavior change |
| **C-5** | §3.2 | Inflation | **Added text** | (not present) | "Increment size was reduced from the original 40 mmHg to improve pulse-detection reliability in field testing." | Medium — explains C-4 |
| **C-6** | §4.2 | E3 Deflation Time | **Safety-critical timing** | within 2 seconds | within 1.5 seconds | **High** — safety improvement |
| **C-7** | §4.2 | Error Code E6 | **Added row** | (not present) | E6 — Bluetooth sync failure | Medium — new error code |
| **C-8** | §4.3 | Alarm Range | **Scope change** | E1–E5 | E1–E6 | Medium — reflects C-7 |
| **C-9** | §5.3 | Data Export | **Added section** | (not present) | Entire 5.3 section on CSV export | Low — new feature |

### 7.2 Unchanged Sections

All other sections are **textually identical** between v1 and v2:
- §1 Device Overview (1.1, 1.2)
- §2.1 General Specifications table
- §2.2 Cuff Specifications
- §3.1 Powering On
- §3.3 Result Display (including numbered list)
- §3.4 Auto Shutoff
- §4.1 Overpressure Protection
- §5.1 Local Storage
- §5.2 Bluetooth Sync
- §6.1 Cleaning Instructions
- §6.2 Calibration
- §7.1 Error Codes (troubleshooting)
- §7.2 Inconsistent Readings
- §8.1 Classification

### 7.3 Classification Notes

- **C-4 and C-6 are safety-critical**: They change device behavior parameters for inflation increment and emergency deflation timing. Any QA test case derived from §3.2 or §4.2 must be flagged as stale when transitioning from v1 to v2.
- **C-3 is behaviorally significant**: The low-battery warning threshold change from 15% to 10% means users get later warnings in v2.
- **C-7/C-8** are structurally significant: A new error code means the error-code table and alarm-threshold section both change, even though the alarm-threshold text change is minimal.
- **C-9** is a pure addition: No v1 content is modified or deleted.

---

## 8. Parser and Hierarchy Reconstruction Strategy (Task E)

### 8.1 Recommended Approach

Given that both PDFs are **digitally generated** with consistent fonts and no scanned content, the parser should use:

1. **pdfplumber** for primary text extraction + character-level font metadata.
2. **No OCR** — not needed for these documents.
3. **Font-based heading detection** as the primary signal, augmented by section-number regex patterns.

### 8.2 Heading Detection Rules

```
Priority 1: Font size 22.0pt + Bold → Document title
Priority 2: Font size 16.5pt + Bold → Level-1 section heading
Priority 3: Font size 12.9pt + Bold → Level-2 subsection heading
Priority 4: Font size 11.0pt + Bold + matches section-number regex → Level-3+ heading (anomalous)
Priority 5: Font size 11.0pt + Bold + table header context → Table header row (not a heading)
Priority 6: Font size 11.0pt + Regular → Body text
```

**Section-number regex:** `^\d+(\.\d+)+\s` — matches `3.2`, `2.1.1.1`, etc.

### 8.3 Hierarchy Construction Algorithm

1. Extract all text with character-level font metadata (fontname, size, bold).
2. Group characters into words, then into lines by vertical position.
3. Classify each line as heading (by rules above) or body text.
4. Parse section numbers from heading lines.
5. Build tree by comparing section-number depth:
   - `N.` → Level 1, child of root
   - `N.M` → Level 2, child of matching `N.`
   - `N.M.X.Y` → Level 4, child of nearest valid ancestor
6. Attach body text to the most recently opened heading.
7. Handle tables separately: detect primary tables, extract as structured data, attach to parent section.
8. Merge cross-page continuations before heading classification.

### 8.4 Explicit Ambiguity Handling

| Ambiguity | Resolution | Confidence |
|---|---|---|
| Heading at body-text font size (IR-2) | Accept if bold + section-number regex matches | Medium — flag for review |
| Missing intermediate levels (IR-1) | Insert as child of nearest valid ancestor | Low — emit warning |
| Out-of-order numbering (IR-3) | Preserve document order; record both sequence position and section number | High — intentional document structure |
| Numbered list vs. section number (IR-6) | Require bold formatting for section numbers; list items in body text are not bold | High |
| Phantom tables (IR-5) | Accept only tables with ≥2 rows and a header row; discard contained fragments | High |

### 8.5 Node Data Model

Each extracted node should carry:

```
- node_id: UUID
- section_number: str (e.g., "3.2")
- heading_text: str (e.g., "Cuff Inflation Sequence")
- body_text: str
- parent_section_number: str
- heading_font_size: float
- heading_is_bold: bool
- source_pages: list[int]
- extraction_confidence: float (0.0–1.0)
- warnings: list[str]
- content_hash: str (SHA-256 of normalized body text)
- child_section_numbers: list[str]
- table_data: optional structured table content
```

---

## 9. Version Matching and Staleness Logic (Task F)

### 9.1 Matching Strategy

Nodes are matched across versions using a **cascading match pipeline**:

| Step | Signal | Weight | Notes |
|---|---|---|---|
| 1 | Section number exact match | **Primary** | `3.2` in v1 ↔ `3.2` in v2 |
| 2 | Normalized heading text | **Secondary** | Case-insensitive, whitespace-normalized |
| 3 | Structural path (parent chain) | **Tertiary** | Disambiguates duplicate headings (e.g., "Error Codes" at 4.2 vs 7.1) |
| 4 | Content hash | **Verification** | Confirms whether matched nodes have identical content |
| 5 | Text similarity (Levenshtein or difflib ratio) | **Fuzzy fallback** | For nodes with changed headings or restructured content |

### 9.2 Match Classifications

| Classification | Criteria |
|---|---|
| **Unchanged** | Section number + heading match + content hash identical |
| **Modified** | Section number + heading match + content hash differs |
| **Added** | Exists in v2 but no section-number or heading match in v1 |
| **Removed** | Exists in v1 but no match in v2 |
| **Ambiguous** | Partial match (heading matches but section number differs, or vice versa) — requires human review |

### 9.3 Staleness Detection

When a node is classified as **Modified**, the system must further classify the change:

| Staleness Level | Detection Method | Example |
|---|---|---|
| **Formatting-only** | Content hash differs but normalized text (strip whitespace, punctuation) is identical | Line rewrap |
| **Wording change** | Normalized text differs but no numeric/unit tokens change | Added explanatory clause (C-2, C-5) |
| **Numeric threshold change** | Regex detects changed numbers adjacent to unit tokens (mmHg, %, seconds, bpm) | C-1 (300→250), C-3 (15%→10%), C-4 (40→30 mmHg), C-6 (2→1.5 sec) |
| **Safety-critical change** | Numeric change in a section tagged as safety-relevant (§4.x, error codes, overpressure) | C-6 (E3 deflation timing) |
| **Structural addition** | New section number with no v1 counterpart | C-9 (§5.3) |
| **Table row addition** | Table has additional rows vs. previous version | C-7 (E6) |

### 9.4 Safety Rule

> **The system must NOT declare a QA test case "current" or "safe" merely because a similarity score is high.** Any numeric change in a safety-tagged section (§4.x, error codes, overpressure limits) automatically flags all derived test cases as **stale** regardless of text similarity.

---

## 10. Backend Architecture (Task G)

### 10.1 Technology Stack

| Component | Technology | Justification |
|---|---|---|
| Web framework | FastAPI | Assignment requirement; async-ready, Pydantic-native |
| Data validation | Pydantic v2 | Assignment requirement; strict schema validation |
| Relational DB | SQLAlchemy + SQLite | Assignment requirement; versioned document trees, selections |
| Document store | MongoDB (or JSON file fallback) | LLM output storage; flexible schema for generated content |
| PDF extraction | pdfplumber | Best balance of text extraction + font metadata + table detection |
| LLM integration | OpenAI/Anthropic API with structured output | QA test case generation with Pydantic validation |
| Testing | pytest | Assignment requirement |

### 10.2 Database Schema (SQLite)

```
documents
├── id (PK)
├── filename
├── version_label (e.g., "v1", "v2")
├── sha256
├── page_count
├── ingested_at

document_nodes
├── id (PK, UUID)
├── document_id (FK → documents)
├── logical_node_id (FK → logical_nodes, nullable)
├── section_number
├── heading_text
├── body_text
├── parent_node_id (FK → document_nodes, self-ref)
├── depth
├── document_order
├── source_pages (JSON array)
├── heading_font_size
├── extraction_confidence
├── warnings (JSON array)
├── content_hash
├── table_data (JSON, nullable)

logical_nodes
├── id (PK, UUID)
├── canonical_section_number
├── canonical_heading
├── created_at

node_versions
├── id (PK)
├── logical_node_id (FK → logical_nodes)
├── document_node_id (FK → document_nodes)
├── document_id (FK → documents)
├── match_confidence
├── match_method

selections
├── id (PK, UUID)
├── name
├── document_id (FK → documents)  ← version-pinned
├── created_at

selection_nodes
├── selection_id (FK → selections)
├── document_node_id (FK → document_nodes)
```

### 10.3 MongoDB Collections (LLM Output)

```
generated_qa_tests
├── _id
├── selection_id (ref)
├── document_node_id (ref)
├── logical_node_id (ref)
├── document_version
├── llm_model
├── llm_prompt_hash
├── generated_at
├── test_cases: [
│     { title, description, preconditions, steps, expected_result, priority }
│   ]
├── validation_status (valid / rejected / error)
├── validation_errors (if rejected)
├── source_content_hash (for staleness check)
├── is_stale (boolean)
├── staleness_reason (nullable)
```

### 10.4 API Endpoints

| Method | Endpoint | Purpose |
|---|---|---|
| `POST` | `/documents/ingest` | Upload and parse a PDF, build version tree |
| `GET` | `/documents` | List all ingested documents |
| `GET` | `/documents/{id}/tree` | Return the full section tree |
| `GET` | `/documents/{id}/nodes/{node_id}` | Get a single node with content |
| `GET` | `/documents/{id}/nodes?search=` | Search nodes by heading or body text |
| `GET` | `/documents/diff?v1={id1}&v2={id2}` | Cross-version diff |
| `POST` | `/selections` | Create a version-pinned named selection |
| `GET` | `/selections/{id}` | Retrieve a selection with its nodes |
| `POST` | `/selections/{id}/generate` | Generate 3–5 QA test cases via LLM |
| `GET` | `/selections/{id}/qa-tests` | Retrieve generated test cases |
| `GET` | `/selections/{id}/staleness` | Check staleness against latest version |
| `GET` | `/qa-tests/{id}` | Retrieve by test ID |

### 10.5 LLM Integration Design

- **Prompt:** Include the node's heading, body text, parent context, and section number. Request 3–5 test case ideas in a defined JSON schema.
- **Validation:** Parse LLM response with Pydantic. Reject and retry (up to 3 attempts) if the response doesn't conform.
- **Duplicate policy:** Before generating, check if a generation exists for the same `(selection_id, document_node_id, source_content_hash)`. If so, return cached result.
- **Staleness:** When a new document version is ingested, compare `source_content_hash` of each generated test's source node against the matched node in the new version. Flag as stale if hashes differ.

### 10.6 Key Architecture Diagram

```
┌─────────────┐     ┌───────────────┐     ┌──────────────┐
│   PDF File  │────▶│  Parser       │────▶│  SQLite DB   │
│  (v1 / v2)  │     │  (pdfplumber  │     │  (documents, │
└─────────────┘     │   + font      │     │   nodes,     │
                    │   analysis)   │     │   versions,  │
                    └───────────────┘     │   selections)│
                                          └──────┬───────┘
                                                 │
                    ┌───────────────┐             │
                    │  Version      │◀────────────┘
                    │  Matcher      │
                    │  (structural  │     ┌──────────────┐
                    │   path +      │────▶│  Staleness   │
                    │   content     │     │  Detector    │
                    │   hash)       │     └──────────────┘
                    └───────────────┘
                                          ┌──────────────┐
                    ┌───────────────┐     │  MongoDB     │
                    │  LLM Service  │────▶│  (qa_tests,  │
                    │  (structured  │     │   generated  │
                    │   output +    │     │   content)   │
                    │   validation) │     └──────────────┘
                    └───────────────┘
                           ▲
                    ┌──────┴────────┐
                    │  FastAPI      │
                    │  Endpoints    │
                    └───────────────┘
```

---

## 11. Parser Validation Matrix (Task H)

| # | Observed Issue | PDF Page/Section | Expected Behavior | Potential Failure | Proposed Test | Verification Method |
|---|---|---|---|---|---|---|
| **V-1** | Section numbering gap (2.1 → 2.1.1.1) | P2, §2.1.1.1 | Parser places 2.1.1.1 as child of 2.1 | Misassignment to wrong parent; orphan node | `test_numbering_gap_parent_assignment` | Assert parent of 2.1.1.1 is 2.1; assert warning emitted |
| **V-2** | Heading at body-text font size | P3, §3.2 | Parser detects 3.2 as heading via bold + section-number pattern | 3.2 missed entirely; content merged into 3.1 | `test_small_font_heading_detection` | Assert node 3.2 exists; assert it has its own body text |
| **V-3** | Out-of-order sections (3.4 before 3.3) | P3, §3.4/§3.3 | Parser preserves document order | Sections reordered silently; content misassigned | `test_out_of_order_sections_preserved` | Assert 3.4 appears before 3.3 in tree traversal order |
| **V-4** | Duplicate heading text ("Error Codes") | P4 §4.2 / P6 §7.1 | Parser creates two distinct nodes with different parents | Nodes conflated; version-matching crosses sections | `test_duplicate_heading_distinct_identity` | Assert 4.2 and 7.1 are separate nodes; assert different parent_ids |
| **V-5** | Phantom table detection | P2, P4 | Parser extracts exactly 1 real table per page | Phantom tables create duplicate/fragmented data | `test_phantom_table_filtering` | Assert exactly 1 table from specs page, 1 from error codes page |
| **V-6** | Numbered list confused with sections | P3, §3.3 | List items 1–5 are body content, not child sections | Spurious child nodes under 3.3 | `test_numbered_list_not_sections` | Assert 3.3 has no child nodes; assert body contains "Normal", "Elevated" |
| **V-7** | Cross-page paragraph continuation | P2→P3 (§3.1), P5→P6 (§6.1) | Content stitched across pages | Truncated body text; duplicate partial paragraphs | `test_cross_page_content_merge` | Assert 3.1 body contains text from both pages |
| **V-8** | E6 error code (v2 only) | V2 P4, §4.2 | Parser extracts E6 row in v2; absent in v1 | Missing row; table structure misaligned | `test_v2_error_code_e6` | Assert v2 error table has 6 rows; v1 has 5 |
| **V-9** | Version matching — modified numeric value | §2.1.1.1 | 300→250 detected as numeric threshold change | Marked as formatting-only due to high similarity | `test_numeric_change_detection` | Assert change classified as "numeric_threshold_change" |
| **V-10** | Version matching — added section | §5.3 | 5.3 classified as "added" in v2 | Missed entirely or matched to wrong v1 section | `test_added_section_detection` | Assert 5.3 is classified as "added" with no v1 match |
| **V-11** | Safety-critical timing change | §4.2 (E3) | 2s→1.5s detected as safety-critical change | Marked as minor wording change | `test_safety_critical_timing_change` | Assert staleness level is "safety_critical" |
| **V-12** | Table header row as heading | P2 "Parameter Value" | Table header not treated as section heading | False heading node created | `test_table_header_not_heading` | Assert no node exists with heading "Parameter Value" |

### 11.1 Priority Unit Tests (Minimum 3)

1. **`test_small_font_heading_detection`** (V-2) — The most dangerous parser failure: missing a real heading silently merges content.
2. **`test_out_of_order_sections_preserved`** (V-3) — Validates document fidelity over assumed ordering.
3. **`test_duplicate_heading_distinct_identity`** (V-4) — Validates that version-matching logic doesn't conflate nodes with identical heading text.

---

## 12. Git Workflow and Incremental Delivery Plan (Task I)

### 12.1 Current Repository State

- Branch: `main` (no commits)
- Remote: `origin` → `https://github.com/ibharath-ofcl/Tri9T-AI.git`
- No existing code to preserve

### 12.2 Proposed Milestones

| Milestone | Branch | Description | Key Deliverables |
|---|---|---|---|
| **M0** | `main` | Project baseline | `.gitignore`, `README.md`, `requirements.txt`, `pyproject.toml`, `docs/stage-1-analysis.md` |
| **M1** | `feature/parser` | Document extraction and hierarchy reconstruction | Parser module, font-based heading detection, table extraction, test suite for IR-1 through IR-7 |
| **M2** | `feature/versioning` | Persistent document versioning and node lineage | SQLite schema, document ingestion endpoint, logical node matching, version comparison |
| **M3** | `feature/api` | Browse and search APIs | Tree, node, search, diff endpoints |
| **M4** | `feature/selections` | Version-pinned selections | Selection CRUD, node association |
| **M5** | `feature/llm` | Validated LLM generation | LLM integration, Pydantic validation, retry logic, MongoDB storage, duplicate policy |
| **M6** | `feature/staleness` | Traceability and staleness detection | Staleness classifier, safety-critical detection, impact reporting |
| **M7** | `feature/tests` | Automated tests and E2E demo | pytest suite, v1→v2→staleness→retrieval demonstration |
| **M8** | `main` | Final documentation | Updated README, API docs, engineering notes |

### 12.3 Git Practices

- Each milestone produces a reviewed commit before merging to `main`.
- `.gitignore` will exclude: `.env`, `__pycache__/`, `*.pyc`, `.venv/`, `*.db` (SQLite), `node_modules/`, `.DS_Store`.
- `data/` will be committed (input files are the assignment materials, not secrets).
- No API keys or credentials will be committed.
- Push will be verified against the remote before execution.

### 12.4 GitHub Push Verification

- Remote is configured: `origin → https://github.com/ibharath-ofcl/Tri9T-AI.git`
- Push access has **not been tested** yet (no commits exist). This will be verified during M0.
- If push fails due to authentication, the user will need to configure credentials (token or SSH key).

---

## 13. Risks, Limitations, and Unresolved Questions

### 13.1 Risks

| Risk | Severity | Mitigation |
|---|---|---|
| pdfplumber phantom table detection | Medium | Filter by row count and bounding-box containment |
| Section 2.1.1.1 parent assignment ambiguity | Low | Assign to nearest ancestor; flag for review |
| LLM output instability | Medium | Pydantic validation + bounded retries (max 3) |
| MongoDB dependency complexity | Low | Offer JSON-file fallback for simpler deployments |
| Font-based heading detection assumes consistent formatting | Medium | Augment with section-number regex as fallback |

### 13.2 Limitations

- Analysis is based on **two specific PDFs**. The parser design is specialized for CT-200 manuals and may not generalize to arbitrary document formats without modification.
- No OCR pathway has been tested because it's not needed for these documents. If future versions are scanned, OCR (Tesseract) would need to be added.
- The "Anthropic recommends" text in §6.2 appears to be a document artifact (manufacturer name placeholder).

### 13.3 Unresolved Questions

1. **LLM provider selection:** Which API should be used for QA test case generation? (OpenAI, Anthropic, or local model?)
2. **MongoDB vs. JSON fallback:** Is a MongoDB instance available, or should we implement a JSON-file-based store?
3. **Push authentication:** Git push access needs to be verified with actual credentials.
4. **Confidence threshold:** What extraction confidence score should trigger human review vs. automatic acceptance?

---

## 14. Go/No-Go Criteria for Stage 2

| Criterion | Status |
|---|---|
| Repository inspected | ✅ Complete |
| Local `data/` directory inspected recursively | ✅ Complete |
| v1 and v2 manuals identified with exact paths | ✅ `data/ct200_manual.pdf` (6 pages), `data/ct200_manual_v2.pdf` (7 pages) |
| Both manuals inspected throughout (all pages) | ✅ Complete — every page analyzed |
| Structural characteristics documented | ✅ 7 confirmed irregularities (IR-1 through IR-7) |
| Confirmed irregularities with page references | ✅ All with page numbers, excerpts, and font evidence |
| Preliminary version differences evidence-based | ✅ 9 changes (C-1 through C-9) with unified diff |
| Parser strategy justified by findings | ✅ Font-based + section-number regex, specific handling for each IR |
| Versioning strategy justified | ✅ Structural-path + content-hash matching |
| Validation matrix ready | ✅ 12 test cases, 3 priority unit tests identified |
| GitHub workflow limitations known | ✅ Push access untested; no secrets in repo |
| `docs/stage-1-analysis.md` exists | ✅ This document |
| No existing work destroyed | ✅ No prior code existed; input files unchanged |
| No premature implementation | ✅ No backend code written |

### Decision: **GO** — All criteria met. Stage 2 can begin.

---

## 15. Next Action for Stage 2

**Immediate next step:** Create the project baseline (M0):

1. Create `.gitignore`, `README.md`, `requirements.txt`/`pyproject.toml`.
2. Make the initial commit with `data/` and `docs/stage-1-analysis.md`.
3. Verify Git push to `origin/main`.
4. Begin implementing the PDF parser module (M1) targeting the 7 confirmed structural irregularities.
