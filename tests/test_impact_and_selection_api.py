"""Integration tests for Selection CRUD, Staleness evaluation, and Document Impact APIs."""

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


def test_selection_lifecycle_and_crud_api(client_with_test_db: TestClient):
    """Test full Selection CRUD via HTTP endpoints."""
    # 1. Ingest v1
    resp_ingest = client_with_test_db.post("/api/v1/documents/ingest?version=v1")
    assert resp_ingest.status_code == 200
    doc_id = resp_ingest.json()["document_id"]
    v1_id = resp_ingest.json()["version_id"]

    # 2. Get section node IDs for v1
    search_resp = client_with_test_db.get("/api/v1/search?q=battery&version=v1")
    assert search_resp.status_code == 200
    hits = search_resp.json()["hits"]
    assert len(hits) > 0
    node_id_1 = hits[0]["node_version_id"]

    search_resp_2 = client_with_test_db.get("/api/v1/search?q=cuff&version=v1")
    assert search_resp_2.status_code == 200
    node_id_2 = search_resp_2.json()["hits"][0]["node_version_id"]

    # 3. Create named selection
    create_payload = {
        "name": "Safety Baseline Verification",
        "description": "Selected safety-critical sections from v1 manual",
        "document_version_id": v1_id,
        "node_version_ids": [node_id_1, node_id_2],
        "metadata_json": '{"test_suite": "smoke"}',
    }
    create_resp = client_with_test_db.post("/api/v1/selections", json=create_payload)
    assert create_resp.status_code == 201
    sel_data = create_resp.json()
    sel_id = sel_data["id"]
    assert sel_data["name"] == "Safety Baseline Verification"
    assert sel_data["version_label"] == "v1"
    assert sel_data["total_nodes"] == 2
    assert len(sel_data["nodes"]) == 2

    # 4. List selections
    list_resp = client_with_test_db.get("/api/v1/selections")
    assert list_resp.status_code == 200
    selections = list_resp.json()
    assert len(selections) == 1
    assert selections[0]["id"] == sel_id

    # Filter by version
    list_filtered = client_with_test_db.get("/api/v1/selections?version=v1")
    assert list_filtered.status_code == 200
    assert len(list_filtered.json()) == 1

    list_empty = client_with_test_db.get("/api/v1/selections?version=v2")
    assert list_empty.status_code == 200
    assert len(list_empty.json()) == 0

    # 5. Retrieve selection by ID
    get_resp = client_with_test_db.get(f"/api/v1/selections/{sel_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["id"] == sel_id

    # 6. Update selection metadata
    patch_payload = {
        "name": "Renamed Safety Scope",
        "description": "Updated description",
    }
    patch_resp = client_with_test_db.patch(f"/api/v1/selections/{sel_id}", json=patch_payload)
    assert patch_resp.status_code == 200
    assert patch_resp.json()["name"] == "Renamed Safety Scope"
    assert patch_resp.json()["description"] == "Updated description"
    # Pinned version remains v1
    assert patch_resp.json()["version_label"] == "v1"

    # 7. Delete selection
    del_resp = client_with_test_db.delete(f"/api/v1/selections/{sel_id}")
    assert del_resp.status_code == 200

    # Verify 404 after deletion
    get_after_del = client_with_test_db.get(f"/api/v1/selections/{sel_id}")
    assert get_after_del.status_code == 404

    # Verify node still exists in document store
    node_get = client_with_test_db.get(f"/api/v1/nodes/{node_id_1}")
    assert node_get.status_code == 200


def test_selection_validation_errors(client_with_test_db: TestClient):
    """Test validation errors for invalid selection inputs."""
    # Ingest v1 and v2
    client_with_test_db.post("/api/v1/documents/ingest?version=v1")
    client_with_test_db.post("/api/v1/documents/ingest?version=v2")

    # Fetch nodes from v1 and v2
    search_v1 = client_with_test_db.get("/api/v1/search?q=battery&version=v1").json()["hits"]
    search_v2 = client_with_test_db.get("/api/v1/search?q=battery&version=v2").json()["hits"]
    v1_node_id = search_v1[0]["node_version_id"]
    v2_node_id = search_v2[0]["node_version_id"]

    # 1. Nonexistent node ID
    resp_bad_node = client_with_test_db.post(
        "/api/v1/selections",
        json={"name": "Bad Node Selection", "version_label": "v1", "node_version_ids": ["invalid-uuid-000"]},
    )
    assert resp_bad_node.status_code == 400

    # 2. Mixed-version nodes
    resp_mixed = client_with_test_db.post(
        "/api/v1/selections",
        json={"name": "Mixed Selection", "version_label": "v1", "node_version_ids": [v1_node_id, v2_node_id]},
    )
    assert resp_mixed.status_code == 400
    assert "Mixed-version" in resp_mixed.json()["detail"]


def test_selection_staleness_and_impact_endpoints(client_with_test_db: TestClient):
    """Test /selections/{id}/staleness, /selections/{id}/impact, and /documents/{id}/impact."""
    # 1. Ingest v1
    v1_ingest = client_with_test_db.post("/api/v1/documents/ingest?version=v1").json()
    doc_id = v1_ingest["document_id"]
    v1_id = v1_ingest["version_id"]

    # 2. Find nodes for §2.1.1.1 (battery life), §3.2 (cuff inflation), §4.2 (error codes)
    hits_battery = client_with_test_db.get("/api/v1/search?q=battery&version=v1").json()["hits"]
    battery_id = next(h["node_version_id"] for h in hits_battery if h["section_number"] == "2.1.1.1")

    hits_cuff = client_with_test_db.get("/api/v1/search?q=cuff&version=v1").json()["hits"]
    cuff_id = next(h["node_version_id"] for h in hits_cuff if h["section_number"] == "3.2")

    hits_err = client_with_test_db.get("/api/v1/search?q=error&version=v1").json()["hits"]
    err_id = next(h["node_version_id"] for h in hits_err if h["section_number"] == "4.2")

    # Also find an unchanged section, e.g. §1.1 Intended Use
    hits_use = client_with_test_db.get("/api/v1/search?q=intended&version=v1").json()["hits"]
    intended_use_id = hits_use[0]["node_version_id"]

    # 3. Create Selection 1: Changed/Impacted sections
    sel1 = client_with_test_db.post(
        "/api/v1/selections",
        json={
            "name": "Modified Features Selection",
            "document_version_id": v1_id,
            "node_version_ids": [battery_id, cuff_id, err_id],
        },
    ).json()

    # 4. Create Selection 2: Unchanged sections
    sel2 = client_with_test_db.post(
        "/api/v1/selections",
        json={
            "name": "Unchanged Baseline Selection",
            "document_version_id": v1_id,
            "node_version_ids": [intended_use_id],
        },
    ).json()

    # Ingest v2
    client_with_test_db.post("/api/v1/documents/ingest?version=v2")

    # 5. Evaluate Staleness for Selection 1 (Modified features)
    stale_resp1 = client_with_test_db.get(f"/api/v1/selections/{sel1['id']}/staleness?target_version=v2")
    assert stale_resp1.status_code == 200
    stale1 = stale_resp1.json()
    assert stale1["aggregate_status"] == "IMPACTED"
    assert stale1["human_review_required"] is True
    assert "Notice:" in stale1["disclaimer"]
    assert stale1["summary"]["stale"] == 3
    assert stale1["summary"]["current"] == 0

    # Verify numeric and timing deltas exist in node assessments
    all_deltas = [d for a in stale1["node_assessments"] for d in a["deltas"]]
    assert any(d["delta_type"] == "NUMERIC" and d["old_value"] == "300" for d in all_deltas)
    assert any(d["delta_type"] == "NUMERIC" and d["old_value"] == "40" for d in all_deltas)
    assert any(d["delta_type"] == "TIMING" and d["old_value"] == "2" for d in all_deltas)

    # 6. Evaluate Staleness for Selection 2 (Unchanged section)
    stale_resp2 = client_with_test_db.get(f"/api/v1/selections/{sel2['id']}/staleness?target_version=v2")
    assert stale_resp2.status_code == 200
    stale2 = stale_resp2.json()
    assert stale2["aggregate_status"] == "CURRENT"
    assert stale2["human_review_required"] is False
    assert stale2["summary"]["current"] == 1
    assert stale2["summary"]["stale"] == 0

    # 7. Evaluate Impact endpoint for Selection 1
    impact_resp1 = client_with_test_db.get(f"/api/v1/selections/{sel1['id']}/impact?target_version=v2")
    assert impact_resp1.status_code == 200
    imp1 = impact_resp1.json()
    assert imp1["affected_nodes_count"] == 3
    assert imp1["unaffected_nodes_count"] == 0
    assert imp1["aggregate_status"] == "IMPACTED"
    assert "IMPACTED" in imp1["explanation"]

    # 8. Document-Wide Impact Endpoint
    doc_impact_resp = client_with_test_db.get(
        f"/api/v1/documents/{doc_id}/impact?from_version=v1&to_version=v2"
    )
    assert doc_impact_resp.status_code == 200
    doc_impact = doc_impact_resp.json()
    assert doc_impact["total_selections_evaluated"] == 2
    assert doc_impact["impacted_selections_count"] == 1
    assert doc_impact["current_selections_count"] == 1
    assert doc_impact["human_review_required"] is True
    assert len(doc_impact["affected_selections"]) == 1
    assert len(doc_impact["unaffected_selections"]) == 1
    assert doc_impact["affected_selections"][0]["selection_id"] == sel1["id"]
    assert doc_impact["unaffected_selections"][0]["selection_id"] == sel2["id"]
