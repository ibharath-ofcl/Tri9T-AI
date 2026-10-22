"""Rigorous test suite targeting all 7 confirmed CT-200 structural edge cases.

Verifies:
- Edge Case A (IR-1): Section 2.1.1.1 numbering gap (missing 2.1.1 intermediate parent)
- Edge Case B (IR-2): Section 3.2 body-sized bold heading text (11.0pt)
- Edge Case C (IR-3): Out-of-order section numbering (Section 3.4 precedes Section 3.3)
- Edge Case D (IR-4): Duplicate "Error Codes" heading text in Section 4.2 and Section 7.1
- Edge Case E (IR-5): Phantom table filtering on page 2 and page 4
- Edge Case F (IR-6): Numbered list 1-5 in Section 3.3 not confused with section headings
- Edge Case G (IR-7): Cross-page content continuation across page boundaries
"""

import pytest
from pathlib import Path
from app.services.pdf_parser import CT200PDFParser
from app.schemas.document import DocumentTree


@pytest.fixture(scope="module")
def parser() -> CT200PDFParser:
    return CT200PDFParser()


@pytest.fixture(scope="module")
def parsed_v1(parser: CT200PDFParser) -> DocumentTree:
    return parser.parse(Path("data/ct200_manual.pdf"), "v1")


@pytest.fixture(scope="module")
def parsed_v2(parser: CT200PDFParser) -> DocumentTree:
    return parser.parse(Path("data/ct200_manual_v2.pdf"), "v2")


def test_edge_case_a_section_2_1_1_1_numbering_gap(
    parser: CT200PDFParser,
    parsed_v1: DocumentTree,
):
    """IR-1: Section 2.1.1.1 has missing parent 2.1.1. Must attach to 2.1 with diagnostic."""
    # Find Section 2.1 and 2.1.1.1
    node_2_1 = parser._search_node_by_section(parsed_v1.nodes, "2.1")
    node_2_1_1_1 = parser._search_node_by_section(parsed_v1.nodes, "2.1.1.1")

    assert node_2_1 is not None, "Section 2.1 must exist"
    assert node_2_1_1_1 is not None, "Section 2.1.1.1 must be recognized"

    # Parent assignment must be nearest valid ancestor (2.1), NOT a fabricated 2.1.1
    assert node_2_1_1_1.parent_id == node_2_1.node_id
    assert any(c.section_number == "2.1.1.1" for c in node_2_1.children)

    # Content must be preserved correctly
    assert "Battery Life Under Typical Use" in (node_2_1_1_1.heading or "")
    assert "AA alkaline" in node_2_1_1_1.body_text
    assert "300 measurement cycles" in node_2_1_1_1.body_text

    # Verify diagnostic warning was emitted
    ir1_warnings = [d for d in parsed_v1.diagnostics if d.code == "IR-1_NUMBERING_GAP"]
    assert len(ir1_warnings) == 1
    assert ir1_warnings[0].section_number == "2.1.1.1"
    assert "missing intermediate parent 2.1.1" in ir1_warnings[0].message


def test_edge_case_b_section_3_2_anomalous_font_size(
    parser: CT200PDFParser,
    parsed_v1: DocumentTree,
):
    """IR-2: Section 3.2 uses 11.0pt bold font. Must be detected as heading and not merged into 3.1."""
    node_3 = parser._search_node_by_section(parsed_v1.nodes, "3.")
    node_3_1 = parser._search_node_by_section(parsed_v1.nodes, "3.1")
    node_3_2 = parser._search_node_by_section(parsed_v1.nodes, "3.2")

    assert node_3 is not None, "Section 3 must exist"
    assert node_3_1 is not None, "Section 3.1 must exist"
    assert node_3_2 is not None, "Section 3.2 must be recognized as distinct heading"

    # Must be child of Section 3
    assert node_3_2.parent_id == node_3.node_id
    assert any(c.section_number == "3.2" for c in node_3.children)

    # 3.2 content must NOT be merged into 3.1
    assert "Cuff Inflation Sequence" in (node_3_2.heading or "")
    assert "initial target of 180 mmHg" in node_3_2.body_text
    assert "Cuff Inflation Sequence" not in node_3_1.body_text

    # Verify diagnostic warning was emitted
    ir2_warnings = [d for d in parsed_v1.diagnostics if d.code == "IR-2_ANOMALOUS_HEADING_FONT"]
    assert len(ir2_warnings) == 1
    assert ir2_warnings[0].section_number == "3.2"


def test_edge_case_c_out_of_order_sections_3_4_and_3_3(
    parser: CT200PDFParser,
    parsed_v1: DocumentTree,
):
    """IR-3: Section 3.4 appears before 3.3. Document order must be preserved and warned."""
    node_3 = parser._search_node_by_section(parsed_v1.nodes, "3.")
    assert node_3 is not None

    child_sec_nums = [c.section_number for c in node_3.children]
    # Document order: 3.1, 3.2, 3.4, 3.3
    assert child_sec_nums == ["3.1", "3.2", "3.4", "3.3"], (
        f"Expected document order ['3.1', '3.2', '3.4', '3.3'], got {child_sec_nums}"
    )

    node_3_4 = parser._search_node_by_section(parsed_v1.nodes, "3.4")
    node_3_3 = parser._search_node_by_section(parsed_v1.nodes, "3.3")

    assert node_3_4.document_order < node_3_3.document_order

    # Verify diagnostic warning was emitted
    ir3_warnings = [d for d in parsed_v1.diagnostics if d.code == "IR-3_OUT_OF_ORDER_SECTION"]
    assert len(ir3_warnings) == 1
    assert "Section 3.3 appears after Section 3.4" in ir3_warnings[0].message


def test_edge_case_d_duplicate_error_codes_headings(
    parser: CT200PDFParser,
    parsed_v1: DocumentTree,
):
    """IR-4: Section 4.2 and Section 7.1 both titled 'Error Codes'. Must be distinct nodes."""
    node_4_2 = parser._search_node_by_section(parsed_v1.nodes, "4.2")
    node_7_1 = parser._search_node_by_section(parsed_v1.nodes, "7.1")

    assert node_4_2 is not None, "Section 4.2 must exist"
    assert node_7_1 is not None, "Section 7.1 must exist"

    # Both contain 'Error Codes' in heading
    assert "Error Codes" in (node_4_2.heading or "")
    assert "Error Codes" in (node_7_1.heading or "")

    # Distinct IDs and distinct parents
    assert node_4_2.node_id != node_7_1.node_id
    assert node_4_2.parent_id != node_7_1.parent_id

    # 4.2 is child of 4.; 7.1 is child of 7.
    node_4 = parser._search_node_by_section(parsed_v1.nodes, "4.")
    node_7 = parser._search_node_by_section(parsed_v1.nodes, "7.")
    assert node_4_2.parent_id == node_4.node_id
    assert node_7_1.parent_id == node_7.node_id

    # Content difference: 4.2 has error table; 7.1 has troubleshooting text
    assert len(node_4_2.tables) == 1
    assert len(node_7_1.tables) == 0
    assert "discontinue use and contact CardioTrack support" in node_7_1.body_text


def test_edge_case_e_phantom_table_filtering(
    parsed_v1: DocumentTree,
    parsed_v2: DocumentTree,
):
    """IR-5: Phantom table detections on page 2 & 4 must be filtered out cleanly."""
    # Diagnostics must record filtered phantoms
    p2_warnings = [
        d for d in parsed_v1.diagnostics
        if d.code == "IR-5_PHANTOM_TABLES_FILTERED" and d.page_number == 2
    ]
    p4_warnings = [
        d for d in parsed_v1.diagnostics
        if d.code == "IR-5_PHANTOM_TABLES_FILTERED" and d.page_number == 4
    ]

    assert len(p2_warnings) == 1
    assert "Filtered out 6 phantom table fragment(s)" in p2_warnings[0].message
    assert len(p4_warnings) == 1
    assert "Filtered out 4 phantom table fragment(s)" in p4_warnings[0].message

    # Total tables in the document must be exactly 2 (General specs + Error codes)
    assert parsed_v1.summary["tables_extracted"] == 2
    assert parsed_v2.summary["tables_extracted"] == 2


def test_edge_case_f_numbered_list_in_section_3_3(
    parser: CT200PDFParser,
    parsed_v1: DocumentTree,
):
    """IR-6: Numbered list 1-5 in 3.3 must NOT be parsed as section headings."""
    node_3_3 = parser._search_node_by_section(parsed_v1.nodes, "3.3")
    assert node_3_3 is not None

    # 3.3 must NOT have child section nodes for items 1-5
    assert len(node_3_3.children) == 0

    # Body text must preserve the classification items
    body = node_3_3.body_text
    assert "1. Normal: systolic < 120 and diastolic < 80" in body
    assert "2. Elevated: systolic 120–129 and diastolic < 80" in body
    assert "3. Hypertension Stage 1:" in body
    assert "4. Hypertension Stage 2:" in body
    assert "5. Hypertensive Crisis:" in body


def test_edge_case_g_cross_page_content_continuation(
    parser: CT200PDFParser,
    parsed_v1: DocumentTree,
    parsed_v2: DocumentTree,
):
    """IR-7: Multi-page section content must span across page boundaries seamlessly."""
    # Section 3.1 starts on Page 2 and finishes on Page 3
    node_3_1 = parser._search_node_by_section(parsed_v1.nodes, "3.1")
    assert node_3_1 is not None
    assert node_3_1.page_start == 2
    assert node_3_1.page_end == 3
    # Text from page 2:
    assert "Press and hold the power button for one second" in node_3_1.body_text
    # Text from page 3:
    assert "Use the profile button to select User 1 or User 2" in node_3_1.body_text

    # In v2: Section 8.1 starts on Page 6 and finishes on Page 7 (the 80-char trailing sentence)
    node_8_1_v2 = parser._search_node_by_section(parsed_v2.nodes, "8.1")
    assert node_8_1_v2 is not None
    assert node_8_1_v2.page_start == 6
    assert node_8_1_v2.page_end == 7
    # Text from page 7:
    assert "validated against relevant clinical accuracy standards" in node_8_1_v2.body_text
