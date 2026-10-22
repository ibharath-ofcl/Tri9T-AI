"""General extraction and verification tests for CT-200 PDF parser."""

import pytest
from pathlib import Path
from app.services.pdf_parser import CT200PDFParser
from app.schemas.document import DocumentTree


@pytest.fixture(scope="module")
def parser() -> CT200PDFParser:
    return CT200PDFParser()


@pytest.fixture(scope="module")
def v1_path() -> Path:
    p = Path("data/ct200_manual.pdf")
    assert p.exists(), f"Missing required test asset: {p}"
    return p


@pytest.fixture(scope="module")
def v2_path() -> Path:
    p = Path("data/ct200_manual_v2.pdf")
    assert p.exists(), f"Missing required test asset: {p}"
    return p


@pytest.fixture(scope="module")
def parsed_v1(parser: CT200PDFParser, v1_path: Path) -> DocumentTree:
    return parser.parse(v1_path, version_label="v1")


@pytest.fixture(scope="module")
def parsed_v2(parser: CT200PDFParser, v2_path: Path) -> DocumentTree:
    return parser.parse(v2_path, version_label="v2")


def test_document_metadata_and_pages(parsed_v1: DocumentTree, parsed_v2: DocumentTree):
    """Verify basic document metadata and correct page counts."""
    assert parsed_v1.metadata.page_count == 6
    assert parsed_v2.metadata.page_count == 7
    assert len(parsed_v1.metadata.sha256) == 64
    assert len(parsed_v2.metadata.sha256) == 64
    assert parsed_v1.metadata.sha256 != parsed_v2.metadata.sha256

    expected_title = "CardioTrack CT-200 Home Blood Pressure Monitor — Technical & User Manual"
    assert parsed_v1.title == expected_title
    assert parsed_v2.title == expected_title


def test_top_level_sections_count(parsed_v1: DocumentTree, parsed_v2: DocumentTree):
    """Both versions must have exactly 8 top-level main sections (1 to 8)."""
    assert len(parsed_v1.nodes) == 8
    assert len(parsed_v2.nodes) == 8

    v1_section_nums = [n.section_number for n in parsed_v1.nodes]
    assert v1_section_nums == ["1.", "2.", "3.", "4.", "5.", "6.", "7.", "8."]

    v2_section_nums = [n.section_number for n in parsed_v2.nodes]
    assert v2_section_nums == ["1.", "2.", "3.", "4.", "5.", "6.", "7.", "8."]


def test_total_nodes_and_v2_new_section(
    parser: CT200PDFParser,
    parsed_v1: DocumentTree,
    parsed_v2: DocumentTree,
):
    """v1 must have 27 nodes; v2 must have 28 nodes including new section 5.3 Data Export."""
    assert parsed_v1.metadata.total_nodes == 27
    assert parsed_v2.metadata.total_nodes == 28

    # Section 5.3 exists in v2 but not in v1
    sec_5_3_v1 = parser._search_node_by_section(parsed_v1.nodes, "5.3")
    assert sec_5_3_v1 is None

    sec_5_3_v2 = parser._search_node_by_section(parsed_v2.nodes, "5.3")
    assert sec_5_3_v2 is not None
    assert "Data Export" in (sec_5_3_v2.heading or "")
    assert "CSV file" in sec_5_3_v2.body_text
    assert "firmware 1.4" in sec_5_3_v2.body_text


def test_content_hash_stability(parser: CT200PDFParser, v1_path: Path):
    """Parsing the same document repeatedly must generate identical content hashes."""
    run1 = parser.parse(v1_path, version_label="v1")
    run2 = parser.parse(v1_path, version_label="v1")

    flat1 = parser._finalize_nodes_and_compute_hashes(run1.nodes)
    flat2 = parser._finalize_nodes_and_compute_hashes(run2.nodes)

    assert len(flat1) == len(flat2)
    for n1, n2 in zip(flat1, flat2):
        assert n1.section_number == n2.section_number
        assert n1.heading_hash == n2.heading_hash
        assert n1.body_hash == n2.body_hash
        assert n1.content_hash == n2.content_hash


def test_table_extraction_and_v2_error_code_e6(
    parser: CT200PDFParser,
    parsed_v1: DocumentTree,
    parsed_v2: DocumentTree,
):
    """Section 4.2 table must contain E1-E5 in v1 and E1-E6 in v2 with deflation timing diff."""
    node_v1 = parser._search_node_by_section(parsed_v1.nodes, "4.2")
    node_v2 = parser._search_node_by_section(parsed_v2.nodes, "4.2")

    assert node_v1 is not None and len(node_v1.tables) == 1
    assert node_v2 is not None and len(node_v2.tables) == 1

    t1 = node_v1.tables[0]
    t2 = node_v2.tables[0]

    # Verify column headers
    assert t1.headers == ["Code", "Meaning", "Device Behavior"]
    assert t2.headers == ["Code", "Meaning", "Device Behavior"]

    # v1 rows: E1 to E5 (5 rows)
    codes_v1 = [r[0] for r in t1.rows]
    assert codes_v1 == ["E1", "E2", "E3", "E4", "E5"]

    # v2 rows: E1 to E6 (6 rows, including E6)
    codes_v2 = [r[0] for r in t2.rows]
    assert codes_v2 == ["E1", "E2", "E3", "E4", "E5", "E6"]

    # Check safety-critical timing change in E3:
    e3_v1 = next(r for r in t1.rows if r[0] == "E3")
    e3_v2 = next(r for r in t2.rows if r[0] == "E3")
    assert "within 2 seconds" in e3_v1[2]
    assert "within 1.5 seconds" in e3_v2[2]


def test_specs_table_in_section_2_1(
    parser: CT200PDFParser,
    parsed_v1: DocumentTree,
):
    """Section 2.1 must have the 7-parameter specification table attached."""
    node_2_1 = parser._search_node_by_section(parsed_v1.nodes, "2.1")
    assert node_2_1 is not None
    assert len(node_2_1.tables) == 1

    tbl = node_2_1.tables[0]
    assert tbl.headers == ["Parameter", "Value"]
    assert len(tbl.rows) == 7

    param_names = [r[0] for r in tbl.rows]
    assert "Measurement method" in param_names
    assert "Pressure range" in param_names
    assert "Pulse range" in param_names
    assert "Accuracy (pressure)" in param_names
