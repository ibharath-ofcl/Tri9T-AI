"""Unit tests for explainable staleness classification, value delta extraction, and precedence."""

import pytest
from app.db.models import NodeVersion
from app.services.staleness_classifier import (
    SAFETY_DISCLAIMER,
    AggregateSelectionStatus,
    NodeStalenessStatus,
    StalenessCategory,
    StalenessClassifier,
)


@pytest.fixture
def classifier():
    return StalenessClassifier()


def make_dummy_node(
    node_id: str = "nv-1",
    logical_id: str = "log-1",
    section: str = "1.0",
    heading: str = "Test Heading",
    body: str = "Standard body text.",
    content_hash: str = "hash1",
    level: int = 1,
    metadata_json: str = None,
) -> NodeVersion:
    return NodeVersion(
        id=node_id,
        document_version_id="ver-1",
        logical_node_id=logical_id,
        heading=heading,
        section_number=section,
        level=level,
        body_text=body,
        content_hash=content_hash,
        heading_hash="hhash",
        body_hash="bhash",
        page_start=1,
        page_end=1,
        source_order=1,
        source_metadata_json=metadata_json,
    )


def test_identical_hashes_yield_no_change(classifier: StalenessClassifier):
    """Test that identical content hashes yield NO_CHANGE with CURRENT status."""
    nv1 = make_dummy_node(content_hash="identical_hash")
    nv2 = make_dummy_node(content_hash="identical_hash")

    res = classifier.classify_node(nv1, nv2, "v1", "v2")
    assert res.classification == StalenessCategory.NO_CHANGE
    assert res.status == NodeStalenessStatus.CURRENT
    assert res.human_review_required is False
    assert res.evidence_level == "HIGH"


def test_whitespace_formatting_yields_formatting_only(classifier: StalenessClassifier):
    """Test that non-semantic whitespace and line wrapping differences yield FORMATTING_ONLY."""
    nv1 = make_dummy_node(
        body="This is standard body text.\nSecond line here.",
        content_hash="hash_a",
    )
    nv2 = make_dummy_node(
        body="This is   standard body text. Second line here.\n\n",
        content_hash="hash_b",
    )

    res = classifier.classify_node(nv1, nv2, "v1", "v2")
    assert res.classification == StalenessCategory.FORMATTING_ONLY
    assert res.status == NodeStalenessStatus.CURRENT
    assert res.human_review_required is False


def test_wording_change_without_numbers(classifier: StalenessClassifier):
    """Test that textual changes without numerical or timing deltas yield WORDING_CHANGE."""
    nv1 = make_dummy_node(
        body="The device must be stored in a dry environment.",
        content_hash="hash_1",
    )
    nv2 = make_dummy_node(
        body="The device should be kept in a climate-controlled room.",
        content_hash="hash_2",
    )

    res = classifier.classify_node(nv1, nv2, "v1", "v2")
    assert res.classification == StalenessCategory.WORDING_CHANGE
    assert res.status == NodeStalenessStatus.STALE
    assert res.human_review_required is True


def test_battery_life_numerical_change_detection(classifier: StalenessClassifier):
    """Test detecting battery measurement cycles 300 -> 250 and percentage 15% -> 10% in §2.1.1.1."""
    text_v1 = (
        "Under typical use (three measurements per day), four AA alkaline batteries "
        "provide approximately 300 measurement cycles before requiring replacement. "
        "The device displays a low ‑ battery icon once remaining capacity falls below 15%."
    )
    text_v2 = (
        "Under typical use (three measurements per day), four AA alkaline batteries "
        "provide approximately 250 measurement cycles before requiring replacement — "
        "revised downward from earlier estimates. The device displays a low ‑ battery icon "
        "once remaining capacity falls below 10%."
    )

    nv1 = make_dummy_node(body=text_v1, content_hash="hash_v1")
    nv2 = make_dummy_node(body=text_v2, content_hash="hash_v2")

    res = classifier.classify_node(nv1, nv2, "v1", "v2")
    assert res.classification == StalenessCategory.NUMERIC_CHANGE
    assert res.status == NodeStalenessStatus.STALE
    assert res.human_review_required is True

    # Check extracted deltas
    delta_vals = {(d.old_value, d.new_value) for d in res.deltas}
    assert ("300", "250") in delta_vals
    assert ("15", "10") in delta_vals


def test_cuff_inflation_pressure_change_detection(classifier: StalenessClassifier):
    """Test detecting cuff inflation increment 40 mmHg -> 30 mmHg in §3.2."""
    text_v1 = (
        "On starting a measurement, the device inflates the cuff to an initial target of 180 mmHg. "
        "If pulse is not detected by 180 mmHg, the device inflates in 40 mmHg increments up to a "
        "maximum of 299 mmHg before aborting with an error."
    )
    text_v2 = (
        "On starting a measurement, the device inflates the cuff to an initial target of 180 mmHg. "
        "If pulse is not detected by 180 mmHg, the device inflates in 30 mmHg increments up to a "
        "maximum of 299 mmHg before aborting with an error."
    )

    nv1 = make_dummy_node(body=text_v1, content_hash="hash_v1")
    nv2 = make_dummy_node(body=text_v2, content_hash="hash_v2")

    res = classifier.classify_node(nv1, nv2, "v1", "v2")
    assert res.classification == StalenessCategory.NUMERIC_CHANGE
    assert res.status == NodeStalenessStatus.STALE

    deltas = res.deltas
    assert any(d.old_value == "40" and d.new_value == "30" and "mmHg" in d.unit for d in deltas)
    # Ensure unchanged values (180, 299) are NOT flagged as changed
    assert not any(d.old_value == "180" and d.new_value != "180" for d in deltas)


def test_timing_change_precedence_over_numeric(classifier: StalenessClassifier):
    """Test that a timing threshold change (e.g. 2s -> 1.5s) is classified as TIMING_CHANGE."""
    text_v1 = "Overpressure condition: Auto-deflates within 2 seconds, displays E3."
    text_v2 = "Overpressure condition: Auto-deflates within 1.5 seconds, displays E3."

    nv1 = make_dummy_node(body=text_v1, content_hash="h1")
    nv2 = make_dummy_node(body=text_v2, content_hash="h2")

    res = classifier.classify_node(nv1, nv2, "v1", "v2")
    assert res.classification == StalenessCategory.TIMING_CHANGE
    assert res.status == NodeStalenessStatus.STALE
    assert res.human_review_required is True
    assert any(d.delta_type == "TIMING" and d.old_value == "2" and d.new_value == "1.5" for d in res.deltas)


def test_table_row_added_error_code_e6(classifier: StalenessClassifier):
    """Test detecting added error code row E6 in §4.2 table metadata."""
    meta_v1 = {
        "tables": [
            {
                "headers": ["Code", "Condition", "Action"],
                "rows": [
                    ["E1", "Leak detected", "Aborts measurement"],
                    ["E3", "Overpressure", "Deflates in 2 seconds"],
                ],
            }
        ]
    }
    meta_v2 = {
        "tables": [
            {
                "headers": ["Code", "Condition", "Action"],
                "rows": [
                    ["E1", "Leak detected", "Aborts measurement"],
                    ["E3", "Overpressure", "Deflates in 1.5 seconds"],
                    ["E6", "Bluetooth sync failure", "Displays E6"],
                ],
            }
        ]
    }
    import json
    nv1 = make_dummy_node(metadata_json=json.dumps(meta_v1), content_hash="tbl1")
    nv2 = make_dummy_node(metadata_json=json.dumps(meta_v2), content_hash="tbl2")

    res = classifier.classify_node(nv1, nv2, "v1", "v2")
    # Contains both timing delta and table row addition
    assert res.classification in (StalenessCategory.TIMING_CHANGE, StalenessCategory.STRUCTURAL_CHANGE)
    assert any("E6" in d.context for d in res.deltas)


def test_added_and_removed_sections(classifier: StalenessClassifier):
    """Test ADDED and REMOVED section lifecycle classifications."""
    nv = make_dummy_node(section="5.3", heading="Data Export")

    # Added node
    added_res = classifier.classify_node(None, nv, "v1", "v2")
    assert added_res.classification == StalenessCategory.ADDED
    assert added_res.human_review_required is True

    # Removed node
    removed_res = classifier.classify_node(nv, None, "v1", "v2")
    assert removed_res.classification == StalenessCategory.REMOVED
    assert removed_res.status == NodeStalenessStatus.REMOVED
    assert removed_res.human_review_required is True


def test_moved_section_detection(classifier: StalenessClassifier):
    """Test that a section whose structural level changes with identical content is classified as MOVED."""
    nv1 = make_dummy_node(level=2, content_hash="same_hash")
    nv2 = make_dummy_node(level=1, content_hash="same_hash")

    res = classifier.classify_node(nv1, nv2, "v1", "v2")
    assert res.classification == StalenessCategory.MOVED
    assert res.status == NodeStalenessStatus.MOVED
    assert res.human_review_required is True


def test_ambiguous_lineage_reporting(classifier: StalenessClassifier):
    """Test that ambiguous lineage is reported as AMBIGUOUS without forcing false match."""
    nv1 = make_dummy_node(content_hash="h1")
    nv2 = make_dummy_node(content_hash="h2")

    res = classifier.classify_node(nv1, nv2, "v1", "v2", lineage_status="AMBIGUOUS")
    assert res.classification == StalenessCategory.AMBIGUOUS
    assert res.status == NodeStalenessStatus.AMBIGUOUS
    assert res.human_review_required is True
    assert res.evidence_level == "LOW"


def test_unrelated_numbers_not_falsely_paired(classifier: StalenessClassifier):
    """Test that completely unrelated numbers across different contexts and units are not paired."""
    text1 = "Operates on 4 AA batteries. Unit weight is 350 grams."
    text2 = "Operates on 4 AA batteries. Tested at 25 °C temperature."

    deltas = classifier.compare_quantities(text1, text2)
    # Grams vs Celsius should NOT be paired as a delta
    assert not any(d.old_value == "350" and d.new_value == "25" for d in deltas)
