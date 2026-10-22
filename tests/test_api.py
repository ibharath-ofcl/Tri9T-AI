"""API endpoint integration tests for CT-200 Document Intelligence service."""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def test_health_endpoint():
    """Verify GET /health returns 200 with asset status."""
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["assets_status"]["v1_manual_present"] is True
    assert data["assets_status"]["v2_manual_present"] is True


def test_preview_v1_endpoint():
    """Verify GET /api/v1/documents/preview?version=v1 returns parsed tree."""
    response = client.get("/api/v1/documents/preview?version=v1")
    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["version"] == "v1"
    assert data["metadata"]["page_count"] == 6
    assert data["metadata"]["total_nodes"] == 27
    assert len(data["nodes"]) == 8
    assert len(data["diagnostics"]) > 0


def test_preview_v2_endpoint():
    """Verify GET /api/v1/documents/preview?version=v2 returns parsed tree with 28 nodes."""
    response = client.get("/api/v1/documents/preview?version=v2")
    assert response.status_code == 200
    data = response.json()
    assert data["metadata"]["version"] == "v2"
    assert data["metadata"]["page_count"] == 7
    assert data["metadata"]["total_nodes"] == 28


def test_preview_invalid_version():
    """Verify path traversal or invalid version query is rejected with 422/400."""
    response = client.get("/api/v1/documents/preview?version=v3")
    assert response.status_code in (400, 422)

    response_traversal = client.get("/api/v1/documents/preview?version=../../etc/passwd")
    assert response_traversal.status_code in (400, 422)
