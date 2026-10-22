"""Tests for version-pinned named selections, repository operations, and immutability invariants."""

import pytest
from pathlib import Path
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.models import Document, DocumentVersion, LogicalNode, NodeVersion, Selection, SelectionNode
from app.repositories.document_repository import DocumentRepository
from app.services.document_ingestion import DocumentIngestionService


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
def ingested_db(test_db: Session):
    """Fixture providing a database with real CT-200 v1 manual ingested."""
    ingestion = DocumentIngestionService()
    ingestion.ingest_version(test_db, version_label="v1")
    return test_db


def test_create_and_get_selection_pinned_to_v1(ingested_db: Session):
    """Test creating a named selection pinned to v1 with real node IDs."""
    repo = DocumentRepository()
    doc = repo.list_documents(ingested_db)[0]
    v1 = repo.get_version_by_label(ingested_db, doc.id, "v1")
    assert v1 is not None

    v1_nodes = repo.get_node_versions_for_document_version(ingested_db, v1.id)
    assert len(v1_nodes) >= 3

    selected_ids = [v1_nodes[0].id, v1_nodes[1].id, v1_nodes[2].id]

    selection = repo.create_selection(
        db=ingested_db,
        document_id=doc.id,
        document_version_id=v1.id,
        name="Critical Safety Scope",
        description="Battery and inflation sections",
        node_version_ids=selected_ids,
        metadata_json='{"qa_focus": "safety"}',
    )
    ingested_db.commit()

    assert selection.id is not None
    assert selection.name == "Critical Safety Scope"
    assert selection.document_version_id == v1.id
    assert selection.document_id == doc.id
    assert len(selection.selection_nodes) == 3

    # Retrieve and verify relationships
    fetched = repo.get_selection(ingested_db, selection.id)
    assert fetched is not None
    assert fetched.document_version.version_label == "v1"
    fetched_ids = [sn.node_version_id for sn in fetched.selection_nodes]
    assert fetched_ids == selected_ids


def test_reject_empty_selection_creation(ingested_db: Session):
    """Test that creating a selection with empty node list is rejected."""
    repo = DocumentRepository()
    doc = repo.list_documents(ingested_db)[0]
    v1 = repo.get_version_by_label(ingested_db, doc.id, "v1")

    with pytest.raises(ValueError, match="non-empty list"):
        repo.create_selection(
            db=ingested_db,
            document_id=doc.id,
            document_version_id=v1.id,
            name="Empty Selection",
            node_version_ids=[],
        )


def test_reject_nonexistent_node_id(ingested_db: Session):
    """Test that specifying nonexistent node IDs raises ValueError."""
    repo = DocumentRepository()
    doc = repo.list_documents(ingested_db)[0]
    v1 = repo.get_version_by_label(ingested_db, doc.id, "v1")

    with pytest.raises(ValueError, match="Unknown node_version_ids"):
        repo.create_selection(
            db=ingested_db,
            document_id=doc.id,
            document_version_id=v1.id,
            name="Bad Nodes Selection",
            node_version_ids=["non-existent-uuid-1234"],
        )


def test_reject_mixed_version_nodes(ingested_db: Session):
    """Test that a selection cannot contain nodes belonging to different document versions."""
    ingestion = DocumentIngestionService()
    ingestion.ingest_version(ingested_db, version_label="v2")

    repo = DocumentRepository()
    doc = repo.list_documents(ingested_db)[0]
    v1 = repo.get_version_by_label(ingested_db, doc.id, "v1")
    v2 = repo.get_version_by_label(ingested_db, doc.id, "v2")

    v1_nodes = repo.get_node_versions_for_document_version(ingested_db, v1.id)
    v2_nodes = repo.get_node_versions_for_document_version(ingested_db, v2.id)

    mixed_ids = [v1_nodes[0].id, v2_nodes[0].id]

    with pytest.raises(ValueError, match="Mixed-version selections are forbidden"):
        repo.create_selection(
            db=ingested_db,
            document_id=doc.id,
            document_version_id=v1.id,
            name="Mixed Selection",
            node_version_ids=mixed_ids,
        )


def test_deduplicate_selected_node_references(ingested_db: Session):
    """Test that duplicate node IDs in input are deduplicated without error."""
    repo = DocumentRepository()
    doc = repo.list_documents(ingested_db)[0]
    v1 = repo.get_version_by_label(ingested_db, doc.id, "v1")
    v1_nodes = repo.get_node_versions_for_document_version(ingested_db, v1.id)

    duplicated_ids = [v1_nodes[0].id, v1_nodes[1].id, v1_nodes[0].id, v1_nodes[1].id]

    sel = repo.create_selection(
        db=ingested_db,
        document_id=doc.id,
        document_version_id=v1.id,
        name="Deduped Selection",
        node_version_ids=duplicated_ids,
    )
    assert len(sel.selection_nodes) == 2


def test_update_selection_metadata_and_nodes(ingested_db: Session):
    """Test updating selection name, description, and node membership."""
    repo = DocumentRepository()
    doc = repo.list_documents(ingested_db)[0]
    v1 = repo.get_version_by_label(ingested_db, doc.id, "v1")
    v1_nodes = repo.get_node_versions_for_document_version(ingested_db, v1.id)

    sel = repo.create_selection(
        db=ingested_db,
        document_id=doc.id,
        document_version_id=v1.id,
        name="Original Name",
        node_version_ids=[v1_nodes[0].id],
    )

    # Update name and add a second node
    updated = repo.update_selection(
        db=ingested_db,
        selection=sel,
        name="Updated Name",
        description="New description",
        node_version_ids=[v1_nodes[0].id, v1_nodes[1].id],
    )

    assert updated.name == "Updated Name"
    assert updated.description == "New description"
    assert len(updated.selection_nodes) == 2
    # Pinned version must NOT change silently
    assert updated.document_version_id == v1.id


def test_delete_selection_preserves_node_snapshots(ingested_db: Session):
    """Test that deleting a selection does NOT delete underlying node snapshots or document versions."""
    repo = DocumentRepository()
    doc = repo.list_documents(ingested_db)[0]
    v1 = repo.get_version_by_label(ingested_db, doc.id, "v1")
    v1_nodes = repo.get_node_versions_for_document_version(ingested_db, v1.id)
    target_node_id = v1_nodes[0].id

    sel = repo.create_selection(
        db=ingested_db,
        document_id=doc.id,
        document_version_id=v1.id,
        name="To Be Deleted",
        node_version_ids=[target_node_id],
    )
    ingested_db.commit()

    sel_id = sel.id
    repo.delete_selection(ingested_db, sel)
    ingested_db.commit()

    # Selection is gone
    assert repo.get_selection(ingested_db, sel_id) is None

    # Underlying node version is preserved completely
    nv = repo.get_node_version(ingested_db, target_node_id)
    assert nv is not None
    assert nv.id == target_node_id


def test_selection_pinned_version_immutability_after_v2_ingest(ingested_db: Session):
    """Test that ingesting v2 leaves v1 selection strictly pinned to v1 snapshots and hashes."""
    repo = DocumentRepository()
    doc = repo.list_documents(ingested_db)[0]
    v1 = repo.get_version_by_label(ingested_db, doc.id, "v1")
    v1_nodes = repo.get_node_versions_for_document_version(ingested_db, v1.id)

    # Select battery life section in v1
    battery_v1 = next(n for n in v1_nodes if n.section_number == "2.1.1.1")
    original_hash = battery_v1.content_hash
    original_node_id = battery_v1.id

    sel = repo.create_selection(
        db=ingested_db,
        document_id=doc.id,
        document_version_id=v1.id,
        name="Battery Verification",
        node_version_ids=[original_node_id],
    )
    ingested_db.commit()

    # Ingest v2
    ingestion = DocumentIngestionService()
    ingestion.ingest_version(ingested_db, version_label="v2")

    # Re-fetch selection
    refetched = repo.get_selection(ingested_db, sel.id)
    assert refetched.document_version_id == v1.id
    assert len(refetched.selection_nodes) == 1
    pinned_node = refetched.selection_nodes[0].node_version

    # Node snapshot ID and hash must remain completely unchanged
    assert pinned_node.id == original_node_id
    assert pinned_node.content_hash == original_hash
    assert pinned_node.document_version.version_label == "v1"
