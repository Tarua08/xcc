"""Tests for the approval UI API endpoints.

Uses FastAPI's TestClient with a mocked Firestore client.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from x_content_agent.shared.models import DraftPost, DraftStatus


@pytest.fixture
def mock_db():
    """Create a mock FirestoreClient."""
    db = MagicMock()
    db.list_drafts.return_value = [
        DraftPost(
            item_id="item1",
            variant=1,
            content="Test draft post about RAG pipelines.",
            status=DraftStatus.PENDING,
            quality_score=75.0,
            created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        ),
    ]
    db.get_draft.return_value = DraftPost(
        item_id="item1",
        variant=1,
        content="Test draft post about RAG pipelines.",
        status=DraftStatus.PENDING,
        quality_score=75.0,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    db.get_item.return_value = None
    db.get_approved_drafts_for_week.return_value = []
    db.get_pending_drafts.return_value = []
    return db


@pytest.fixture
def client(mock_db):
    """Create a test client with mocked DB."""
    with patch("x_content_agent.services.approval_ui.app.get_db", return_value=mock_db):
        from x_content_agent.services.approval_ui.app import app
        yield TestClient(app)


class TestHealthEndpoint:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "healthy"


class TestDraftAPI:
    def test_list_drafts(self, client):
        resp = client.get("/api/drafts")
        assert resp.status_code == 200
        data = resp.json()
        assert "drafts" in data
        assert len(data["drafts"]) == 1

    def test_get_draft(self, client):
        resp = client.get("/api/drafts/item1_v1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["draft"]["content"] == "Test draft post about RAG pipelines."

    def test_get_draft_not_found(self, client, mock_db):
        mock_db.get_draft.return_value = None
        resp = client.get("/api/drafts/nonexistent")
        assert resp.status_code == 404

    def test_approve_draft(self, client):
        resp = client.post("/api/drafts/item1_v1/approve")
        assert resp.status_code == 200
        assert resp.json()["status"] == "approved"

    def test_reject_draft(self, client):
        resp = client.post("/api/drafts/item1_v1/reject")
        assert resp.status_code == 200
        assert resp.json()["status"] == "rejected"

    def test_update_draft_content(self, client):
        resp = client.patch(
            "/api/drafts/item1_v1",
            json={"content": "Updated content for the post."},
        )
        assert resp.status_code == 200

    def test_update_draft_content_too_long(self, client):
        resp = client.patch(
            "/api/drafts/item1_v1",
            json={"content": "x" * 281},
        )
        assert resp.status_code == 400

    def test_update_draft_human_lines(self, client):
        resp = client.patch(
            "/api/drafts/item1_v1",
            json={"human_lines": "My hot take\nBuilder perspective"},
        )
        assert resp.status_code == 200

    def test_update_draft_too_many_human_lines(self, client):
        resp = client.patch(
            "/api/drafts/item1_v1",
            json={"human_lines": "line1\nline2\nline3"},
        )
        assert resp.status_code == 422  # Pydantic validation error


class TestScheduleAPI:
    def test_schedule_empty(self, client):
        resp = client.get("/api/schedule")
        assert resp.status_code == 200
        assert resp.json()["total"] == 0
