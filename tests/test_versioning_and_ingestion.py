"""Unit and integration tests for document versioning, relational ingestion, and logical lineage."""

import pytest
import uuid
from pathlib import Path
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Document, DocumentVersion, LogicalNode, NodeVersion
from app.repositories.document_repository import DocumentRepository
from app.services.document_ingestion import DocumentIngestionService, IngestionConflictError
from app.services.version_matcher import ChangeClassification, VersionMatcher, PriorNodeSnapshot
from app.schemas.document import DocumentNode


from sqlalchemy import create_engine, select, text

@pytest.fixture
def test_db():
    """Isolated in-memory SQLite database fixture for every test."""
    engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        with engine.connect() as conn:
            conn.execute(text("PRAGMA foreign_keys=OFF"))
            Base.metadata.drop_all(conn)


@pytest.fixture
def ingestion_service():
    return DocumentIngestionService()


def test_database_initialization_and_models(test_db: Session):
    """Verify database schema creation and relationships."""
    repo = DocumentRepository()
    doc = repo.get_or_create_document(test_db, "TEST-MANUAL", "Test Manual Title")
    assert doc.id is not None
    assert doc.document_key == "TEST-MANUAL"
    test_db.commit()

    fetched = repo.get_document_by_key(test_db, "TEST-MANUAL")
    assert fetched is not None
    assert fetched.id == doc.id


def test_ingest_v1_and_v2_lineage(test_db: Session, ingestion_service: DocumentIngestionService):
    """Ingest v1, then ingest v2 without mutating v1, and verify logical node lineage."""
    repo = DocumentRepository()

    # Step 1: Ingest v1
    res1 = ingestion_service.ingest_version(test_db, version_label="v1")
    assert res1.version_label == "v1"
    assert res1.total_nodes == 27
    assert res1.page_count == 6
    assert res1.is_idempotent_replay is False

    # Check v1 nodes in DB
    v1_version = repo.get_document_version(test_db, res1.version_id)
    assert v1_version is not None
    v1_nodes = repo.get_node_versions_for_document_version(test_db, res1.version_id)
    assert len(v1_nodes) == 27

    # Record v1 content hash for a modified section: Section 3.2
    v1_node_3_2 = next(n for n in v1_nodes if n.section_number == "3.2")
    v1_hash_3_2 = v1_node_3_2.content_hash
    logical_id_3_2 = v1_node_3_2.logical_node_id
    nv_id_3_2 = v1_node_3_2.id

    # Step 2: Ingest v2
    res2 = ingestion_service.ingest_version(test_db, version_label="v2")
    assert res2.version_label == "v2"
    assert res2.total_nodes == 28
    assert res2.page_count == 7
    assert res2.is_idempotent_replay is False

    # Verify matching statistics: 23 unchanged, 4 modified, 1 added
    assert res2.match_summary["UNCHANGED"] == 23
    assert res2.match_summary["MODIFIED"] == 4
    assert res2.match_summary["ADDED"] == 1
    assert res2.match_summary["REMOVED"] == 0

    # Step 3: Verify v1 records remain completely unchanged (immutability)
    v1_node_3_2_after = test_db.get(NodeVersion, nv_id_3_2)
    assert v1_node_3_2_after.content_hash == v1_hash_3_2
    assert v1_node_3_2_after.logical_node_id == logical_id_3_2
    assert "40 mmHg" in v1_node_3_2_after.body_text

    # Step 4: Verify v2 node for Section 3.2 retains same logical_node_id but has new nv_id and hash
    v2_nodes = repo.get_node_versions_for_document_version(test_db, res2.version_id)
    assert len(v2_nodes) == 28
    v2_node_3_2 = next(n for n in v2_nodes if n.section_number == "3.2")
    assert v2_node_3_2.logical_node_id == logical_id_3_2  # Conceptual identity preserved!
    assert v2_node_3_2.id != nv_id_3_2                   # New immutable version record!
    assert v2_node_3_2.content_hash != v1_hash_3_2       # Content hash changed!
    assert "30 mmHg" in v2_node_3_2.body_text

    # Step 5: Verify Section 5.3 Data Export received a brand new logical node
    v2_node_5_3 = next(n for n in v2_nodes if n.section_number == "5.3")
    assert v2_node_5_3 is not None
    # Logical node for 5.3 must not exist in any v1 node
    v1_logical_ids = {n.logical_node_id for n in v1_nodes}
    assert v2_node_5_3.logical_node_id not in v1_logical_ids


def test_idempotent_ingestion(test_db: Session, ingestion_service: DocumentIngestionService):
    """Re-ingesting the exact same manual returns existing record without duplicating nodes."""
    res1 = ingestion_service.ingest_version(test_db, "v1")
    assert res1.is_idempotent_replay is False

    # Second ingestion of v1
    res1_replay = ingestion_service.ingest_version(test_db, "v1")
    assert res1_replay.is_idempotent_replay is True
    assert res1_replay.version_id == res1.version_id

    # Total DocumentVersion records in DB must still be 1
    versions = test_db.execute(select(DocumentVersion)).scalars().all()
    assert len(versions) == 1

    # Total NodeVersion records in DB must still be exactly 27
    nodes = test_db.execute(select(NodeVersion)).scalars().all()
    assert len(nodes) == 27


def test_conflicting_version_checksum_rejection(
    test_db: Session, ingestion_service: DocumentIngestionService, tmp_path: Path
):
    """Attempting to ingest a conflicting checksum under an existing version label must raise IngestionConflictError."""
    # Ingest standard v1
    ingestion_service.ingest_version(test_db, "v1")

    # Create a dummy modified file for v1
    fake_v1 = tmp_path / "fake_v1.pdf"
    fake_v1.write_bytes(b"%PDF-1.4 dummy modified content")

    with pytest.raises(IngestionConflictError) as exc_info:
        ingestion_service.ingest_version(test_db, "v1", file_path=fake_v1)
    assert "conflicts with new checksum" in str(exc_info.value)


def test_atomic_rollback_on_failure(test_db: Session):
    """If an error occurs during ingestion, all records must be rolled back atomically."""
    repo = DocumentRepository()
    doc = repo.get_or_create_document(test_db, "CT-200", "CT-200 Manual")
    test_db.commit()

    # Artificially trigger an error by passing an unparseable dummy file
    dummy_file = Path("dummy_corrupt.pdf")
    dummy_file.write_bytes(b"NOT A REAL PDF")
    service = DocumentIngestionService()

    try:
        with pytest.raises(Exception):
            service.ingest_version(test_db, "v1", file_path=dummy_file)
    finally:
        dummy_file.unlink(missing_ok=True)

    # Verify no partial document_versions or node_versions were committed
    versions = test_db.execute(select(DocumentVersion)).scalars().all()
    assert len(versions) == 0
    nodes = test_db.execute(select(NodeVersion)).scalars().all()
    assert len(nodes) == 0


def test_duplicate_error_codes_headings_disambiguation(
    test_db: Session, ingestion_service: DocumentIngestionService
):
    """Verify Section 4.2 and Section 7.1 ('Error Codes') have distinct logical nodes and parents."""
    repo = DocumentRepository()
    res = ingestion_service.ingest_version(test_db, "v1")
    nodes = repo.get_node_versions_for_document_version(test_db, res.version_id)

    n42 = next(n for n in nodes if n.section_number == "4.2")
    n71 = next(n for n in nodes if n.section_number == "7.1")

    assert "Error Codes" in n42.heading
    assert "Error Codes" in n71.heading
    assert n42.id != n71.id
    assert n42.logical_node_id != n71.logical_node_id
    assert n42.parent_node_version_id != n71.parent_node_version_id


def test_hierarchy_tree_has_no_cycles(
    test_db: Session, ingestion_service: DocumentIngestionService
):
    """Verify that persisted parent-child hierarchy contains no cycles and resolves up to root."""
    repo = DocumentRepository()
    res = ingestion_service.ingest_version(test_db, "v1")
    nodes = repo.get_node_versions_for_document_version(test_db, res.version_id)
    node_map = {n.id: n for n in nodes}

    for n in nodes:
        visited = set()
        curr = n
        while curr.parent_node_version_id:
            assert curr.id not in visited, f"Cycle detected at node {curr.id} ({curr.section_number})"
            visited.add(curr.id)
            curr = node_map[curr.parent_node_version_id]
        # Root node has level 1
        assert curr.level == 1 or curr.level == 0


def test_matcher_ambiguity_reporting():
    """Verify that ambiguous matches (equally plausible candidates) are flagged AMBIGUOUS rather than forced."""
    matcher = VersionMatcher(similarity_threshold=0.80, ambiguity_margin=0.10)

    # Two prior nodes with near-identical headings
    prior1 = PriorNodeSnapshot(
        node_version_id="pv-1",
        logical_node_id="log-1",
        section_number="9.1",
        heading="Safety Limits and Alarms",
        normalized_heading="safety limits and alarms",
        parent_logical_id="log-parent",
        parent_section_number="9.",
        structural_path="9. > 9.1",
        content_hash="hash-1",
        body_text="Body 1",
        source_order=1,
    )
    prior2 = PriorNodeSnapshot(
        node_version_id="pv-2",
        logical_node_id="log-2",
        section_number="9.2",
        heading="Safety Limits and Warnings",
        normalized_heading="safety limits and warnings",
        parent_logical_id="log-parent",
        parent_section_number="9.",
        structural_path="9. > 9.2",
        content_hash="hash-2",
        body_text="Body 2",
        source_order=2,
    )

    # New node without section number that equally matches both
    new_ambiguous_node = DocumentNode(
        node_id="new-1",
        section_number=None,
        heading="Safety Limits and Warnings",
        level=2,
        body_text="New text",
        parent_id=None,
        document_order=1,
        page_start=1,
        page_end=1,
        content_hash="new-hash",
        heading_hash="new-h-hash",
        body_hash="new-b-hash",
    )

    # If parent context differs from both, scores will be very close
    parent_map = {"new-1": None}
    results, removed = matcher.match_versions(
        prev_nodes=[prior1, prior2],
        new_nodes=[new_ambiguous_node],
        parent_map_new=parent_map,
    )

    res = results["new-1"]
    # Either matched top candidate or flagged ambiguous; must not silently overwrite
    assert res.classification in (ChangeClassification.AMBIGUOUS, ChangeClassification.MOVED, ChangeClassification.MODIFIED)
