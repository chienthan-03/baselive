import pytest
from fastapi.testclient import TestClient

from src.api.main import app, get_db
from src.db.database import Database

# Single in-memory DB instance shared across all tests
_test_db = Database(":memory:")
_test_db.init_db()
_test_db.insert_highlight(
    stream_id="test_stream",
    start_pts=10.0,
    end_pts=20.0,
    score=0.9,
    clip_path="dummy.mp4",
    status="PENDING",
    reason="high energy"
)

def override_get_db():
    yield _test_db

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

def test_get_highlights():
    response = client.get("/api/highlights")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["stream_id"] == "test_stream"
    assert data[0]["status"] == "PENDING"

def test_approve_highlight():
    response = client.post("/api/highlights/1/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"

    response = client.get("/api/highlights")
    data = response.json()
    assert data[0]["status"] == "APPROVED"

def test_reject_highlight():
    response = client.post("/api/highlights/1/reject")
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"

def test_adjust_highlight_boundaries():
    payload = {"start_pts": 12.0, "end_pts": 18.0}
    response = client.post("/api/highlights/1/adjust", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ADJUSTED"

    response = client.get("/api/highlights")
    data = response.json()
    assert data[0]["start_pts"] == 12.0
    assert data[0]["end_pts"] == 18.0
