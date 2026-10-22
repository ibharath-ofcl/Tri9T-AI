# Stage 2 — CT-200 PDF Extraction Engine & Hierarchy Parser Documentation

**Project:** Tri9T AI Internship Assignment — CT-200 Medical Device Manual Document Intelligence  
**Component:** PDF Extraction & Deterministic Hierarchy Engine (`app/services/pdf_parser.py`)  
**Status:** Stage 2 Complete (Milestone M0 + Parser Foundation)  
**Date:** 2026-10-22  

---

## 1. Overview and Architecture

The Stage 2 extraction engine is a deterministic, multi-pass document intelligence parser specialized for the CardioTrack CT-200 Technical and User Manuals (v1 and v2).

Rather than relying on ungrounded LLM guessing or expensive and lossy OCR for clean digital PDFs, the parser directly leverages native character layout, bounding boxes, font attributes (font name, size, weight), and section numbering patterns.

```
┌─────────────────────────────────┐
│     Input PDF (v1 or v2)        │
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ Pass 1: Table Extraction &       │  Detects candidates, filters cell-fragment
│ Phantom Filtering               │  phantoms via geometry and sparsity checks.
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ Pass 2: Typography & Layout     │  Groups words into vertical lines, determines
│ Line Aggregation                │  dominant font/size/weight, excludes table text.
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ Pass 3: Heading Classification  │  Multi-rule classification: title (22pt),
│ & Hierarchy Stack Engine        │  L1 (16.5pt), L2 (12.9pt), anomalous (11pt).
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ Pass 4: Cross-Page Stitching &  │  Merges multi-page paragraphs and binds
│ Table Association               │  verified tables to owning section nodes.
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ Pass 5: Content Normalization   │  Calculates deterministic SHA-256 hashes
│ & Cryptographic Hashing         │  for heading, body, and full node content.
└────────────────┬────────────────┘
                 │
                 ▼
┌─────────────────────────────────┐
│ Reconstructed DocumentTree      │  Returns typed Pydantic models with
│ & Relational Flat Nodes         │  provenance, metadata, and diagnostics.
└─────────────────────────────────┘
```

---

## 2. Heading Detection Rules and Typography Hierarchy

The parser classifies document elements according to the verified font taxonomy identified in Stage 1:

| Element Type | Primary Font / Attributes | Regex Pattern | Action Taken |
|---|---|---|---|
| **Document Title** | Nimbus Sans Bold @ 22.0pt | `^CardioTrack CT-200.*` | Stored as document title on Page 1 |
| **Level-1 Section** | Nimbus Sans Bold @ 16.5pt | `^([1-9])\.\s+(.*)$` | Root-level section (Level 1) |
| **Level-2 Subsection** | Nimbus Sans Bold @ 12.9pt | `^(\d+\.\d+)\s+(.*)$` | Child of matching Level-1 section |
| **Anomalous Level-2** | Nimbus Sans Bold @ 11.0pt | `^(\d+\.\d+)\s+(.*)$` | Classified as Level 2; emits `IR-2` warning |
| **Anomalous Level-4** | Nimbus Sans Bold @ 11.0pt | `^(\d+(\.\d+){2,})\s+(.*)$` | Resolved to nearest ancestor; emits `IR-1` warning |
| **Numbered List** | Nimbus Sans Regular @ 11.0pt | `^[1-5]\.\s+[A-Z]` | Kept as section body text; NOT a heading |
| **Table Header** | Nimbus Sans Bold @ 11.0pt | Inside table bounding box | Filtered out of text stream into `TableData` |

---

## 3. Handling of the 7 Confirmed Structural Irregularities

### Edge Case A: Section 2.1.1.1 (Missing Intermediate Parent 2.1.1)
- **Observed:** Subsection `2.1.1.1 Battery Life Under Typical Use` jumps from level 2 (`2.1`) to level 4 without a `2.1.1` section existing. Furthermore, its font size is 11.0pt (matching body text).
- **Engine Handling:** The parser recognizes the multi-dot numbering `2.1.1.1` with bold weight. When resolving parents from the hierarchy stack, it determines that `2.1.1` does not exist. Rather than fabricating a fictitious `2.1.1` node or incorrectly promoting it to root, the parser attaches `2.1.1.1` directly to `2.1` as the nearest valid ancestor.
- **Diagnostic Emitted:** `IR-1_NUMBERING_GAP` (Warning).

### Edge Case B: Section 3.2 (Body-Sized Bold Heading Font)
- **Observed:** Section `3.2 Cuff Inflation Sequence` uses 11.0pt bold font instead of the standard 12.9pt bold font used by sibling sections (3.1, 3.3, 3.4).
- **Engine Handling:** The parser applies a joint typography + regex rule: any line matching `^\d+\.\d+\s+` with bold weight (`Nimbus Sans Bold`) and font size $\ge 10.5\text{pt}$ is classified as a Level-2 heading. The heading is not merged into 3.1 body text.
- **Diagnostic Emitted:** `IR-2_ANOMALOUS_HEADING_FONT` (Info).

### Edge Case C: Out-of-Order Section Numbering (3.4 Precedes 3.3)
- **Observed:** On Page 3, Section `3.4 Auto Shutoff` appears at vertical position `top=211`, while Section `3.3 Result Display and Classification` appears below it at `top=303`.
- **Engine Handling:** The parser strictly preserves source reading order. Section 3.4 is assigned `document_order=11`, and Section 3.3 is assigned `document_order=12`. The parser detects that `3.3 < 3.4` under parent Section 3 and emits a diagnostic warning rather than silently rearranging the document.
- **Diagnostic Emitted:** `IR-3_OUT_OF_ORDER_SECTION` (Warning).

### Edge Case D: Duplicate Heading Text ("Error Codes" in 4.2 and 7.1)
- **Observed:** Both Section 4.2 and Section 7.1 share the exact title `"Error Codes"`.
- **Engine Handling:** Node occurrence IDs are generated deterministically using version label, section number, and document sequence order (`tri9t_{version}_{sec}_{order}`). Section 4.2 is parented to Section 4 ("Alarms and Safety Behavior") and carries the error table; Section 7.1 is parented to Section 7 ("Troubleshooting") and carries textual guidance.
- **Diagnostic Emitted:** `IR-4_DUPLICATE_HEADING_TEXT` (Info).

### Edge Case E: Phantom Table Detections
- **Observed:** pdfplumber detects 7 tables on Page 2 and 5 (v1) / 7 (v2) tables on Page 4 due to cell boundaries and spacing artifacts.
- **Engine Handling:**
  1. Any candidate table with $<2$ rows or $<2$ columns is rejected.
  2. Any candidate whose bounding box is geometrically contained within an already-verified table's bounding box is discarded as an internal fragment.
  3. Cell sparsity check: tables with $>55\%$ empty cells are rejected.
- **Result:** Exactly 1 valid table on Page 2 (8x2 specification table) and 1 valid table on Page 4 (6x3 v1 / 7x3 v2 error codes table).
- **Diagnostic Emitted:** `IR-5_PHANTOM_TABLES_FILTERED` (Info).

### Edge Case F: Numbered List 1–5 in Section 3.3
- **Observed:** Blood pressure classifications in Section 3.3 are formatted as:
  `1. Normal: systolic < 120 and diastolic < 80`
  `2. Elevated: systolic 120–129 and diastolic < 80`
  ...
- **Engine Handling:** The parser enforces that Level-1 section headings require bold font weight AND font size $\ge 15.0\text{pt}$. Because these list items use regular 11.0pt font, they are never confused with root sections and are preserved as sequential body text within Section 3.3.

### Edge Case G: Cross-Page Paragraph and Section Continuation
- **Observed:** Multiple sections span across page boundaries:
  - Section 3.1: Starts at bottom of Page 2, completes on Page 3.
  - Section 4.3: Starts on Page 4, completes on Page 5.
  - Section 6.1: Starts on Page 5, completes on Page 6.
  - Section 8.1 (v2): Starts on Page 6, concludes on Page 7 with an 80-character trailing sentence.
- **Engine Handling:** When text lines at the top of a page do not begin with a heading, they are seamlessly appended to the currently active node. The node's `page_start` and `page_end` attributes accurately record the full page range (e.g., Section 8.1 in v2 has `page_start=6, page_end=7`).

---

## 4. Content Normalization and Cryptographic Hashing

To support cross-version diffing and staleness detection without losing medical meaning, the parser computes deterministic SHA-256 hashes:

1. **`heading_hash`**: SHA-256 of normalized heading text.
2. **`body_hash`**: SHA-256 of normalized body text concatenated with structured table representations.
3. **`content_hash`**: SHA-256 of `{normalized_heading}\n\n{combined_body}`.

**Normalization Rules:**
- Replaces non-breaking spaces (`\xa0`) with standard spaces.
- Normalizes carriage returns (`\r\n` $\rightarrow$ `\n`).
- Collapses duplicate horizontal whitespace (`[ \t]+` $\rightarrow$ ` `).
- Preserves all digits, decimals, measurement units (`mmHg`, `bpm`, `%`, `seconds`), symbols (`±`, `<`, `>`, `≤`, `≥`), and casing.
- Preserves hyphenated words broken across line wraps.

---

## 5. How to Run the Parser and Inspection Utility

### Running the Diagnostic Inspector
```bash
# Inspect CT-200 v1 manual
python -m scripts.inspect_manual data/ct200_manual.pdf

# Inspect CT-200 v2 manual
python -m scripts.inspect_manual data/ct200_manual_v2.pdf
```

### Running the Test Suite
```bash
pytest tests/
```

### Running the FastAPI Service
```bash
uvicorn app.main:app --reload --port 8000
```
- Health Check: `http://localhost:8000/health`
- v1 Preview: `http://localhost:8000/api/v1/documents/preview?version=v1`
- v2 Preview: `http://localhost:8000/api/v1/documents/preview?version=v2`
- Interactive API Docs: `http://localhost:8000/docs`

---

## 6. Implemented vs. Planned Behavior

| Feature | Stage 2 (Current) | Stage 3/4/5 (Planned) |
|---|---|---|
| Native PDF Extraction | ✅ Deterministic via pdfplumber | Preserved |
| Hierarchy Reconstruction | ✅ 8 sections, 27 (v1) / 28 (v2) nodes | Preserved |
| Edge Case Handling | ✅ All 7 confirmed edge cases handled | Preserved |
| Diagnostic Telemetry | ✅ Structured DiagnosticWarning models | Persisted in database |
| Content Hashing | ✅ SHA-256 (heading, body, combined) | Used for cross-version diffs |
| Persistent Storage | ❌ In-memory preview only | SQLite database + SQLAlchemy ORM |
| Version Matching | ❌ Distinct parses | Canonical logical node alignment |
| Staleness Detection | ❌ Not in Stage 2 | Automated staleness classifier |
| LLM Test Generation | ❌ Not in Stage 2 | Structured QA test generation |
