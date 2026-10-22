"""FastAPI endpoint tests for persistent document browsing, search, and version diffing."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.base import Base
from app.db.session import get_db
from app.main import app


@pytest.fixture
def client_with_test_db():
    """Create a FastAPI test client backed by an isolated in-memory SQLite database."""
    test_engine = create_engine(
        "sqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(test_engine)
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    def override_get_db():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()
    with test_engine.connect() as conn:
        conn.execute(text("PRAGMA foreign_keys=OFF"))
        Base.metadata.drop_all(conn)


def test_api_ingest_and_list_documents(client_with_test_db: TestClient):
    """Test POST /documents/ingest and GET /documents."""
    # Ingest v1
    resp = client_with_test_db.post("/api/v1/documents/ingest?version=v1")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "success"
    assert data["version_label"] == "v1"
    assert data["total_nodes"] == 27
    doc_id = data["document_id"]

    # Ingest v2
    resp2 = client_with_test_db.post("/api/v1/documents/ingest?version=v2")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert data2["version_label"] == "v2"
    assert data2["total_nodes"] == 28

    # List documents
    list_resp = client_with_test_db.get("/api/v1/documents")
    assert list_resp.status_code == 200
    docs = list_resp.json()
    assert len(docs) == 1
    assert docs[0]["document_id"] == doc_id
    assert len(docs[0]["versions"]) == 2
    version_labels = [v["version_label"] for v in docs[0]["versions"]]
    assert "v1" in version_labels and "v2" in version_labels


def test_api_get_document_sections(client_with_test_db: TestClient):
    """Test GET /documents/{id}/sections?version=v1."""
    # Ingest v1
    ingest_resp = client_with_test_db.post("/api/v1/documents/ingest?version=v1")
    assert ingest_resp.status_code == 200
    doc_id = ingest_resp.json()["document_id"]

    # Fetch top level sections
    resp = client_with_test_db.get(f"/api/v1/documents/{doc_id}/sections?version=v1")
    assert resp.status_code == 200
    sections = resp.json()
    assert len(sections) == 8  # 8 main sections (1. to 8.)
    assert sections[0]["section_number"] == "1."
    assert "Device Overview" in sections[0]["heading"]
    assert len(sections[0]["children"]) == 2  # 1.1 and 1.2


def test_api_get_node_detail(client_with_test_db: TestClient):
    """Test GET /nodes/{node_version_id} with full provenance and tables."""
    client_with_test_db.post("/api/v1/documents/ingest?version=v1")

    # Search for Section 2.1 to obtain node_version_id
    s_resp = client_with_test_db.get("/api/v1/search?q=General%20Specifications&version=v1")
    assert s_resp.status_code == 200
    hits = s_resp.json()["hits"]
    assert len(hits) > 0
    node_id = hits[0]["node_version_id"]

    # Get node details
    detail_resp = client_with_test_db.get(f"/api/v1/nodes/{node_id}")
    assert detail_resp.status_code == 200
    node = detail_resp.json()
    assert node["section_number"] == "2.1"
    assert node["level"] == 2
    assert len(node["content_hash"]) == 64
    assert len(node["tables"]) == 1
    assert node["tables"][0]["headers"] == ["Parameter", "Value"]


def test_api_search_with_version_isolation(client_with_test_db: TestClient):
    """Test search endpoint isolation by version."""
    client_with_test_db.post("/api/v1/documents/ingest?version=v1")
    client_with_test_db.post("/api/v1/documents/ingest?version=v2")

    # Search for "Bluetooth sync failure" (which only exists in v2 error code table)
    resp_v1 = client_with_test_db.get("/api/v1/search?q=Bluetooth%20sync%20failure&version=v1")
    assert resp_v1.status_code == 200
    assert resp_v1.json()["total_hits"] == 0

    resp_v2 = client_with_test_db.get("/api/v1/search?q=Bluetooth%20sync%20failure&version=v2")
    assert resp_v2.status_code == 200
    assert resp_v2.json()["total_hits"] >= 1
    assert resp_v2.json()["hits"][0]["version_label"] == "v2"


def test_api_compare_node_versions_and_diff(client_with_test_db: TestClient):
    """Test GET /nodes/{logical_node_id}/changes between v1 and v2."""
    client_with_test_db.post("/api/v1/documents/ingest?version=v1")
    client_with_test_db.post("/api/v1/documents/ingest?version=v2")

    # Locate Section 3.2 logical_node_id (increment 40 -> 30 mmHg)
    search_resp = client_with_test_db.get("/api/v1/search?q=Cuff%20Inflation%20Sequence&version=v1")
    assert search_resp.status_code == 200
    logical_id_3_2 = search_resp.json()["hits"][0]["logical_node_id"]

    # Compare changes
    diff_resp = client_with_test_db.get(
        f"/api/v1/nodes/{logical_id_3_2}/changes?from_version=v1&to_version=v2"
    )
    assert diff_resp.status_code == 200
    data = diff_resp.json()
    assert data["change_classification"] == "MODIFIED"
    assert data["is_content_changed"] is True
    assert data["from_version"]["content_hash"] != data["to_version"]["content_hash"]
    assert data["diff_summary"] is not None
    # Diff should show changes in 40 vs 30
    assert "40 mmHg" in data["from_version"]["body_text"]
    assert "30 mmHg" in data["to_version"]["body_text"]
