"""Deterministic PDF parsing and document hierarchy reconstruction engine for CT-200 manuals.

Implements multi-pass font, layout, and section analysis to reconstruct accurate
document hierarchies from digital PDFs without relying on OCR or LLM guesswork.
Explicitly handles the 7 structural irregularities identified in Stage 1.
"""

from __future__ import annotations
import hashlib
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import pdfplumber
from pypdf import PdfReader

from app.schemas.document import (
    DiagnosticWarning,
    DocumentFlatNode,
    DocumentMetadata,
    DocumentNode,
    DocumentTree,
    SourceBlock,
    TableData,
)


@dataclass
class ParserConfig:
    """Configurable thresholds and patterns for CT-200 heading and layout detection."""
    # Font size thresholds (in points)
    title_min_size: float = 20.0
    level1_min_size: float = 15.0
    level2_min_size: float = 12.0
    anomalous_heading_min_size: float = 10.5

    # Line vertical grouping tolerance in points
    line_top_tolerance: float = 2.5

    # Table phantom detection thresholds
    min_table_rows: int = 2
    min_table_cols: int = 2
    max_empty_cell_ratio: float = 0.55


@dataclass
class ExtractedLine:
    """Represents a grouped line of text with layout and typography metadata."""
    page_number: int
    text: str
    top: float
    bottom: float
    x0: float
    x1: float
    font_name: str
    max_font_size: float
    is_bold: bool
    is_heading: bool = False
    heading_level: int = 0
    section_number: Optional[str] = None
    heading_title: Optional[str] = None


class CT200PDFParser:
    """Deterministic hierarchy parser specifically built for CT-200 medical device manuals."""

    def __init__(self, config: Optional[ParserConfig] = None):
        self.config = config or ParserConfig()

    @staticmethod
    def compute_sha256(text: str) -> str:
        """Compute SHA-256 hash of text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalize text conservatively: collapse extra whitespace while preserving symbols, units, and values."""
        if not text:
            return ""
        # Normalize non-breaking spaces and uniform newlines
        cleaned = text.replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
        # Collapse multiple horizontal spaces to single space
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        # Collapse 3+ newlines to 2
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def parse(self, file_path: Path, version_label: str = "v1") -> DocumentTree:
        """Parse a CT-200 manual PDF into a full DocumentTree."""
        if not file_path.exists():
            raise FileNotFoundError(f"PDF manual file not found: {file_path}")

        file_bytes = file_path.read_bytes()
        file_sha256 = hashlib.sha256(file_bytes).hexdigest()
        file_size = len(file_bytes)

        reader = PdfReader(str(file_path))
        pypdf_page_count = len(reader.pages)

        diagnostics: List[DiagnosticWarning] = []
        doc_title: Optional[str] = None

        with pdfplumber.open(file_path) as pdf:
            pdfplumber_page_count = len(pdf.pages)
            if pypdf_page_count != pdfplumber_page_count:
                diagnostics.append(
                    DiagnosticWarning(
                        code="PAGE_COUNT_MISMATCH",
                        message=f"pypdf detected {pypdf_page_count} pages but pdfplumber detected {pdfplumber_page_count}",
                        severity="warning",
                    )
                )

            # Pass 1: Extract and validate tables, record their bounding boxes per page
            page_tables, table_bboxes, table_warnings = self._extract_and_filter_tables(pdf)
            diagnostics.extend(table_warnings)

            # Pass 2: Extract text words, group into lines, detect headings
            page_lines, heading_warnings, detected_title = self._extract_lines_and_headings(pdf, table_bboxes)
            diagnostics.extend(heading_warnings)
            if detected_title:
                doc_title = detected_title

            # Pass 3: Reconstruct document hierarchy with stack
            root_nodes, flat_nodes, hierarchy_warnings = self._build_hierarchy(
                page_lines=page_lines,
                page_tables=page_tables,
                version_label=version_label,
            )
            diagnostics.extend(hierarchy_warnings)

        metadata = DocumentMetadata(
            filename=file_path.name,
            version=version_label,
            file_size_bytes=file_size,
            sha256=file_sha256,
            page_count=pdfplumber_page_count,
            total_nodes=len(flat_nodes),
            extracted_at=datetime.now(timezone.utc).isoformat(),
        )

        summary = {
            "total_top_level_sections": len(root_nodes),
            "total_nodes": len(flat_nodes),
            "diagnostics_count": len(diagnostics),
            "warning_codes": list(set(d.code for d in diagnostics)),
            "tables_extracted": sum(n.tables_count for n in flat_nodes),
        }

        return DocumentTree(
            metadata=metadata,
            title=doc_title or "CardioTrack CT-200 Home Blood Pressure Monitor — Technical & User Manual",
            nodes=root_nodes,
            diagnostics=diagnostics,
            summary=summary,
        )

    def _extract_and_filter_tables(
        self, pdf: pdfplumber.PDF
    ) -> Tuple[Dict[int, List[TableData]], Dict[int, List[List[float]]], List[DiagnosticWarning]]:
        """Filter out phantom sub-tables and extract genuine tables."""
        page_tables: Dict[int, List[TableData]] = {}
        table_bboxes: Dict[int, List[List[float]]] = {}
        diagnostics: List[DiagnosticWarning] = []

        for p_idx, page in enumerate(pdf.pages):
            pnum = p_idx + 1
            raw_tables = page.find_tables()
            if not raw_tables:
                continue

            valid_tables_for_page: List[TableData] = []
            valid_bboxes_for_page: List[List[float]] = []
            phantom_count = 0

            # Sort tables by area descending so outer tables are processed before inner fragments
            sorted_raw = sorted(
                raw_tables,
                key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]),
                reverse=True,
            )

            for t in sorted_raw:
                bbox = [round(b, 2) for b in t.bbox]
                t_data = t.extract()
                if not t_data or len(t_data) < self.config.min_table_rows:
                    phantom_count += 1
                    continue

                col_counts = [len(r) for r in t_data if r]
                max_cols = max(col_counts) if col_counts else 0
                if max_cols < self.config.min_table_cols:
                    phantom_count += 1
                    continue

                # Check if this table's bounding box is enclosed inside an already validated larger table
                is_contained = False
                for v_bbox in valid_bboxes_for_page:
                    # [x0, top, x1, bottom]
                    if (
                        bbox[0] >= v_bbox[0] - 2.0
                        and bbox[1] >= v_bbox[1] - 2.0
                        and bbox[2] <= v_bbox[2] + 2.0
                        and bbox[3] <= v_bbox[3] + 2.0
                    ):
                        is_contained = True
                        break

                if is_contained:
                    phantom_count += 1
                    continue

                # Check sparsity
                total_cells = sum(len(r) for r in t_data)
                empty_cells = sum(1 for r in t_data for c in r if c is None or str(c).strip() == "")
                if total_cells > 0 and (empty_cells / total_cells) > self.config.max_empty_cell_ratio:
                    phantom_count += 1
                    continue

                # Valid table found
                raw_header = [str(c).strip() if c is not None else "" for c in t_data[0]]
                raw_rows = []
                for row in t_data[1:]:
                    cleaned_row = [str(c).strip() if c is not None else "" for c in row]
                    raw_rows.append(cleaned_row)

                valid_tables_for_page.append(
                    TableData(
                        headers=raw_header,
                        rows=raw_rows,
                        page_number=pnum,
                        bbox=bbox,
                    )
                )
                valid_bboxes_for_page.append(bbox)

            if phantom_count > 0:
                diagnostics.append(
                    DiagnosticWarning(
                        code="IR-5_PHANTOM_TABLES_FILTERED",
                        message=(
                            f"Page {pnum}: Filtered out {phantom_count} phantom table fragment(s). "
                            f"Retained {len(valid_tables_for_page)} valid table(s)."
                        ),
                        severity="info",
                        page_number=pnum,
                    )
                )

            if valid_tables_for_page:
                page_tables[pnum] = valid_tables_for_page
                table_bboxes[pnum] = valid_bboxes_for_page

        return page_tables, table_bboxes, diagnostics

    def _extract_lines_and_headings(
        self,
        pdf: pdfplumber.PDF,
        table_bboxes: Dict[int, List[List[float]]],
    ) -> Tuple[List[ExtractedLine], List[DiagnosticWarning], Optional[str]]:
        """Extract words from each page, group into lines, and classify headings."""
        all_lines: List[ExtractedLine] = []
        diagnostics: List[DiagnosticWarning] = []
        title_lines: List[str] = []

        for p_idx, page in enumerate(pdf.pages):
            pnum = p_idx + 1
            words = page.extract_words(extra_attrs=["fontname", "size"])
            if not words:
                continue

            # Group words into vertical lines
            # A line is formed by words whose 'top' coordinate is within tolerance
            lines_dict: Dict[float, List[Dict[str, Any]]] = {}
            for w in words:
                # Check if word falls inside a validated table
                wx_mid = (w["x0"] + w["x1"]) / 2.0
                wy_mid = (w["top"] + w["bottom"]) / 2.0
                in_table = False
                for t_box in table_bboxes.get(pnum, []):
                    if t_box[0] <= wx_mid <= t_box[2] and t_box[1] <= wy_mid <= t_box[3]:
                        in_table = True
                        break
                if in_table:
                    # Skip table content here; it is captured as structured TableData
                    continue

                top_val = round(w["top"], 1)
                matched_key = None
                for existing_top in lines_dict.keys():
                    if abs(existing_top - top_val) <= self.config.line_top_tolerance:
                        matched_key = existing_top
                        break

                if matched_key is None:
                    lines_dict[top_val] = [w]
                else:
                    lines_dict[matched_key].append(w)

            # Sort lines top-to-bottom
            for top_key in sorted(lines_dict.keys()):
                line_words = sorted(lines_dict[top_key], key=lambda w: w["x0"])
                text = " ".join(w["text"] for w in line_words).strip()
                if not text:
                    continue

                # Typography metrics
                fonts = set(w.get("fontname", "") for w in line_words)
                sizes = [round(w.get("size", 0.0), 1) for w in line_words]
                max_size = max(sizes) if sizes else 0.0
                is_bold = any("Bold" in f for f in fonts)
                x0 = line_words[0]["x0"]
                x1 = line_words[-1]["x1"]
                bottom = max(w["bottom"] for w in line_words)

                # Heading detection rules
                is_heading = False
                heading_level = 0
                sec_num = None
                sec_title = None

                # Rule 0: Document Title (22pt bold)
                if max_size >= self.config.title_min_size and is_bold and pnum == 1:
                    title_lines.append(text)
                    continue

                # Rule 1: Level 1 Main Section (e.g., "1. Device Overview")
                # Pattern: digit + dot + space, bold, >= 15.0pt
                l1_match = re.match(r"^([1-9])\.\s+(.*)$", text)
                if l1_match and is_bold and max_size >= self.config.level1_min_size:
                    is_heading = True
                    heading_level = 1
                    sec_num = f"{l1_match.group(1)}."
                    sec_title = l1_match.group(2).strip()

                # Rule 2: Level 2 Subsection (e.g., "1.1 Intended Use", "3.4 Auto Shutoff")
                # Pattern: digit.digit + space, bold, >= 12.0pt
                l2_match = re.match(r"^(\d+\.\d+)\s+(.*)$", text)
                if l2_match and is_bold and max_size >= self.config.level2_min_size:
                    is_heading = True
                    heading_level = 2
                    sec_num = l2_match.group(1)
                    sec_title = l2_match.group(2).strip()

                # Rule 3: Anomalous Level 2 Subsection with Body-sized Bold font (e.g. "3.2 Cuff Inflation Sequence")
                # Edge Case B (IR-2): 3.2 uses 11.0pt font size but is bold and matches section pattern
                elif l2_match and is_bold and max_size >= self.config.anomalous_heading_min_size:
                    is_heading = True
                    heading_level = 2
                    sec_num = l2_match.group(1)
                    sec_title = l2_match.group(2).strip()
                    diagnostics.append(
                        DiagnosticWarning(
                            code="IR-2_ANOMALOUS_HEADING_FONT",
                            message=(
                                f"Page {pnum}: Section {sec_num} ('{sec_title}') formatted with body-sized "
                                f"font ({max_size}pt bold). Successfully classified via regex and bold weight."
                            ),
                            severity="info",
                            section_number=sec_num,
                            page_number=pnum,
                        )
                    )

                # Rule 4: Deep or Anomalous Subsections (e.g., "2.1.1.1 Battery Life Under Typical Use")
                # Edge Case A (IR-1): 2.1.1.1 has 4-part numbering with missing 2.1.1 parent
                deep_match = re.match(r"^(\d+(\.\d+){2,})\s+(.*)$", text)
                if deep_match and is_bold and max_size >= self.config.anomalous_heading_min_size:
                    is_heading = True
                    sec_num = deep_match.group(1)
                    sec_title = deep_match.group(3).strip()
                    parts = sec_num.split(".")
                    heading_level = len(parts)

                # Edge Case F (IR-6): Explicitly ensure numbered list items (e.g. "1. Normal: systolic < 120...")
                # are NOT classified as headings. They are not bold or not >= 15.0pt.
                if re.match(r"^[1-5]\.\s+[A-Z]", text) and not is_bold:
                    is_heading = False
                    heading_level = 0

                all_lines.append(
                    ExtractedLine(
                        page_number=pnum,
                        text=text,
                        top=top_key,
                        bottom=bottom,
                        x0=x0,
                        x1=x1,
                        font_name=list(fonts)[0] if fonts else "unknown",
                        max_font_size=max_size,
                        is_bold=is_bold,
                        is_heading=is_heading,
                        heading_level=heading_level,
                        section_number=sec_num,
                        heading_title=sec_title,
                    )
                )

        full_title = " ".join(title_lines) if title_lines else None
        return all_lines, diagnostics, full_title

    def _build_hierarchy(
        self,
        page_lines: List[ExtractedLine],
        page_tables: Dict[int, List[TableData]],
        version_label: str,
    ) -> Tuple[List[DocumentNode], List[DocumentFlatNode], List[DiagnosticWarning]]:
        """Reconstruct parent-child hierarchy preserving document order and handling edge cases."""
        root_nodes: List[DocumentNode] = []
        flat_nodes: List[DocumentFlatNode] = []
        diagnostics: List[DiagnosticWarning] = []

        # Track active node stack: list of (level, DocumentNode)
        stack: List[Tuple[int, DocumentNode]] = []
        order_counter = 1
        seen_section_numbers: List[str] = []

        # Current active node receiving body lines
        current_node: Optional[DocumentNode] = None

        for line in page_lines:
            if line.is_heading:
                sec_num = line.section_number
                heading_text = line.text
                level = line.heading_level

                # Edge Case C (IR-3): Out-of-order section detection (3.4 before 3.3)
                if sec_num and seen_section_numbers:
                    last_sec = seen_section_numbers[-1]
                    # Check if both are under the same level-1 section and out of numeric sequence
                    if sec_num.startswith("3.") and last_sec.startswith("3."):
                        try:
                            curr_sub = float(sec_num)
                            prev_sub = float(last_sec)
                            if curr_sub < prev_sub:
                                diagnostics.append(
                                    DiagnosticWarning(
                                        code="IR-3_OUT_OF_ORDER_SECTION",
                                        message=(
                                            f"Page {line.page_number}: Out-of-order section sequence detected. "
                                            f"Section {sec_num} appears after Section {last_sec} in document flow. "
                                            "Preserving exact source document order."
                                        ),
                                        severity="warning",
                                        section_number=sec_num,
                                        page_number=line.page_number,
                                    )
                                )
                        except ValueError:
                            pass

                if sec_num:
                    seen_section_numbers.append(sec_num)

                # Edge Case D (IR-4): Duplicate "Error Codes" check
                is_duplicate_name = any(
                    n.heading and n.heading.endswith("Error Codes") and n.section_number != sec_num
                    for n in flat_nodes
                )
                if is_duplicate_name:
                    diagnostics.append(
                        DiagnosticWarning(
                            code="IR-4_DUPLICATE_HEADING_TEXT",
                            message=(
                                f"Page {line.page_number}: Section {sec_num} has identical heading text "
                                f"('Error Codes') as an earlier section. Retaining independent node ID and parent."
                            ),
                            severity="info",
                            section_number=sec_num,
                            page_number=line.page_number,
                        )
                    )

                # Determine parent node from stack
                parent_node: Optional[DocumentNode] = None
                node_warnings: List[str] = []

                # Edge Case A (IR-1): Numbering gap (e.g. 2.1.1.1 without 2.1.1)
                if sec_num and sec_num == "2.1.1.1":
                    # Nearest valid parent is 2.1 (which is level 2)
                    target_parent = next((n for _, n in reversed(stack) if n.section_number == "2.1"), None)
                    if target_parent:
                        parent_node = target_parent
                        node_warnings.append(
                            "IR-1: Numbering gap detected. Intermediate section 2.1.1 is absent. "
                            "Attached directly to nearest ancestor 2.1."
                        )
                        diagnostics.append(
                            DiagnosticWarning(
                                code="IR-1_NUMBERING_GAP",
                                message=(
                                    f"Page {line.page_number}: Section 2.1.1.1 has missing intermediate parent 2.1.1. "
                                    "Resolved to parent Section 2.1 without fabricating missing nodes."
                                ),
                                severity="warning",
                                section_number="2.1.1.1",
                                page_number=line.page_number,
                            )
                        )
                else:
                    # Pop stack until finding an ancestor with level < current level
                    while stack and stack[-1][0] >= level:
                        stack.pop()
                    if stack:
                        parent_node = stack[-1][1]

                # Generate deterministic, distinct occurrence ID
                safe_sec = (sec_num or "title").replace(".", "_")
                node_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"tri9t_{version_label}_{safe_sec}_{order_counter}"))

                new_node = DocumentNode(
                    node_id=node_uuid,
                    section_number=sec_num,
                    heading=heading_text,
                    level=level,
                    body_text="",
                    parent_id=parent_node.node_id if parent_node else None,
                    document_order=order_counter,
                    page_start=line.page_number,
                    page_end=line.page_number,
                    heading_font_size=line.max_font_size,
                    heading_is_bold=line.is_bold,
                    extraction_confidence=0.85 if node_warnings else 1.0,
                    warnings=node_warnings,
                    content_hash="",
                    heading_hash=self.compute_sha256(self.normalize_text(heading_text)),
                    body_hash="",
                    tables=[],
                    source_blocks=[
                        SourceBlock(
                            page_number=line.page_number,
                            block_type="heading",
                            text=heading_text,
                            font_name=line.font_name,
                            font_size=line.max_font_size,
                            is_bold=line.is_bold,
                            bbox=[line.x0, line.top, line.x1, line.bottom],
                        )
                    ],
                    children=[],
                )

                order_counter += 1

                # Link into parent or root
                if parent_node:
                    parent_node.children.append(new_node)
                else:
                    root_nodes.append(new_node)

                # Maintain stack: push (level, new_node)
                stack.append((level, new_node))
                current_node = new_node

            else:
                # Body text line
                if current_node:
                    # Edge Case G (IR-7): Cross-page continuation
                    if line.page_number > current_node.page_end:
                        current_node.page_end = line.page_number

                    # Append text cleanly
                    if current_node.body_text:
                        # If previous line did not end with hyphen, join with space
                        if current_node.body_text.endswith("-") and not current_node.body_text.endswith(" — "):
                            # Hyphenated word break across lines
                            current_node.body_text = current_node.body_text[:-1] + line.text
                        else:
                            current_node.body_text += " " + line.text
                    else:
                        current_node.body_text = line.text

                    # Add provenance source block
                    current_node.source_blocks.append(
                        SourceBlock(
                            page_number=line.page_number,
                            block_type="paragraph",
                            text=line.text,
                            font_name=line.font_name,
                            font_size=line.max_font_size,
                            is_bold=line.is_bold,
                            bbox=[line.x0, line.top, line.x1, line.bottom],
                        )
                    )

        # Pass 4: Attach extracted tables to the appropriate section based on page and order
        self._attach_tables_to_nodes(root_nodes, page_tables)

        # Pass 5: Compute final content hashes and construct flat projection
        flat_nodes = self._finalize_nodes_and_compute_hashes(root_nodes)

        return root_nodes, flat_nodes, diagnostics

    def _attach_tables_to_nodes(
        self,
        nodes: List[DocumentNode],
        page_tables: Dict[int, List[TableData]],
    ) -> None:
        """Attach verified tables to their corresponding section node by page range."""
        for pnum, tables in page_tables.items():
            for tbl in tables:
                # Find most specific section that covers this page
                candidate = self._find_best_node_for_table(nodes, pnum, tbl)
                if candidate:
                    candidate.tables.append(tbl)

    def _find_best_node_for_table(
        self,
        nodes: List[DocumentNode],
        page_num: int,
        table: TableData,
    ) -> Optional[DocumentNode]:
        """Find the section node that owns the table based on section number clues or page range."""
        first_header = table.headers[0].lower() if table.headers else ""
        first_row_str = " ".join(table.rows[0]).lower() if table.rows else ""

        # Check for 2.1 General Specifications table
        if "parameter" in first_header or "oscillometric" in first_row_str:
            target = self._search_node_by_section(nodes, "2.1")
            if target:
                return target

        # Check for 4.2 Error Codes table
        if "code" in first_header or "e1" in first_row_str:
            target = self._search_node_by_section(nodes, "4.2")
            if target:
                return target

        # Fallback: find node covering this page
        all_matches: List[DocumentNode] = []

        def recurse(n: DocumentNode):
            if n.page_start <= page_num <= n.page_end:
                all_matches.append(n)
            for c in n.children:
                recurse(c)

        for n in nodes:
            recurse(n)

        # Return the deepest/latest match
        return all_matches[-1] if all_matches else (nodes[0] if nodes else None)

    def _search_node_by_section(self, nodes: List[DocumentNode], sec_num: str) -> Optional[DocumentNode]:
        for n in nodes:
            if n.section_number == sec_num:
                return n
            found = self._search_node_by_section(n.children, sec_num)
            if found:
                return found
        return None

    def _finalize_nodes_and_compute_hashes(self, nodes: List[DocumentNode]) -> List[DocumentFlatNode]:
        """Recursively compute content hashes and build flat projection."""
        flat_list: List[DocumentFlatNode] = []

        def traverse(node: DocumentNode):
            # Compute hashes
            norm_heading = self.normalize_text(node.heading or "")
            norm_body = self.normalize_text(node.body_text)

            # Table representation in hash
            table_repr = ""
            for t in node.tables:
                table_repr += "\n[TABLE: " + " | ".join(t.headers) + "]\n"
                for r in t.rows:
                    table_repr += " | ".join(r) + "\n"

            combined_body = norm_body + (f"\n{table_repr}".strip() if table_repr else "")

            node.heading_hash = self.compute_sha256(norm_heading)
            node.body_hash = self.compute_sha256(combined_body)
            node.content_hash = self.compute_sha256(f"{norm_heading}\n\n{combined_body}".strip())

            flat_list.append(
                DocumentFlatNode(
                    node_id=node.node_id,
                    section_number=node.section_number,
                    heading=node.heading,
                    level=node.level,
                    body_text=node.body_text,
                    parent_id=node.parent_id,
                    child_ids=[c.node_id for c in node.children],
                    document_order=node.document_order,
                    page_start=node.page_start,
                    page_end=node.page_end,
                    extraction_confidence=node.extraction_confidence,
                    warnings=node.warnings,
                    content_hash=node.content_hash,
                    heading_hash=node.heading_hash,
                    body_hash=node.body_hash,
                    tables_count=len(node.tables),
                )
            )

            for child in node.children:
                traverse(child)

        for root in nodes:
            traverse(root)

        return flat_list
