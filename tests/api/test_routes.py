import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.api.main import app, get_db
from src.db.database import Database
from src.engine.llm_gate import LLMRefineResult


@pytest.fixture
def test_db():
    db = Database(":memory:")
    db.init_db()
    yield db
    db.close()


@pytest.fixture
def client(test_db):
    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
def db_with_highlights(test_db):
    test_db.insert_highlight(
        stream_id="stream_a",
        start_pts=10.0,
        end_pts=25.0,
        score=0.9,
        clip_path="dummy.mp4",
        status="PENDING",
        reason="high energy",
        highlight_type="FINAL",
    )
    test_db.insert_highlight(
        stream_id="stream_a",
        start_pts=30.0,
        end_pts=50.0,
        score=0.8,
        highlight_type="DRAFT",
        is_growing=1,
        status="PENDING",
    )
    test_db.insert_highlight(
        stream_id="stream_b",
        start_pts=5.0,
        end_pts=20.0,
        score=0.7,
        highlight_type="DRAFT",
        status="PENDING",
    )
    return test_db


def test_get_highlights(client, test_db):
    test_db.insert_highlight(
        stream_id="test_stream",
        start_pts=10.0,
        end_pts=20.0,
        score=0.9,
        clip_path="dummy.mp4",
        status="PENDING",
        reason="high energy",
    )
    response = client.get("/api/highlights")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["stream_id"] == "test_stream"
    assert data[0]["status"] == "PENDING"


def test_get_highlights_filter_by_type(client, db_with_highlights):
    resp = client.get("/api/highlights?type=DRAFT")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert all(h["highlight_type"] == "DRAFT" for h in data)


def test_get_highlights_filter_by_stream_id(client, db_with_highlights):
    resp = client.get("/api/highlights?stream_id=stream_a")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert all(h["stream_id"] == "stream_a" for h in data)


def test_approve_highlight(client, test_db):
    test_db.insert_highlight(
        stream_id="test_stream",
        start_pts=10.0,
        end_pts=20.0,
        score=0.9,
        clip_path="dummy.mp4",
        status="PENDING",
        reason="high energy",
    )
    response = client.post("/api/highlights/1/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "APPROVED"

    response = client.get("/api/highlights")
    data = response.json()
    assert data[0]["status"] == "APPROVED"


def test_reject_highlight(client, test_db):
    test_db.insert_highlight(
        stream_id="test_stream",
        start_pts=10.0,
        end_pts=20.0,
        score=0.9,
        clip_path="dummy.mp4",
        status="PENDING",
        reason="high energy",
    )
    response = client.post("/api/highlights/1/reject", json={"reason": "other"})
    assert response.status_code == 200
    assert response.json()["status"] == "REJECTED"


def test_reject_with_reason_writes_feedback(client, test_db):
    hid = test_db.insert_highlight(
        stream_id="test_stream",
        start_pts=10.0,
        end_pts=20.0,
        score=0.9,
        clip_path="dummy.mp4",
        status="PENDING",
        reason="high energy",
    )
    resp = client.post(f"/api/highlights/{hid}/reject", json={"reason": "false_positive"})
    assert resp.status_code == 200
    feedback = test_db.get_feedback_for_highlight(hid)
    assert feedback[0]["action"] == "REJECT"
    assert feedback[0]["reject_reason"] == "false_positive"


def test_approve_writes_accept_feedback(client, test_db):
    hid = test_db.insert_highlight(
        stream_id="test_stream",
        start_pts=10.0,
        end_pts=20.0,
        score=0.9,
        clip_path="dummy.mp4",
        status="PENDING",
        reason="high energy",
        ai_start_pts=10.0,
        ai_end_pts=20.0,
    )
    resp = client.post(f"/api/highlights/{hid}/approve")
    assert resp.status_code == 200
    feedback = test_db.get_feedback_for_highlight(hid)
    assert feedback[0]["action"] == "ACCEPT"
    assert feedback[0]["start_delta_sec"] == 0
    assert feedback[0]["end_delta_sec"] == 0


def test_adjust_highlight_boundaries(client, test_db):
    test_db.insert_highlight(
        stream_id="test_stream",
        start_pts=10.0,
        end_pts=20.0,
        score=0.9,
        clip_path="dummy.mp4",
        status="PENDING",
        reason="high energy",
    )
    payload = {"start_pts": 12.0, "end_pts": 18.0}
    response = client.post("/api/highlights/1/adjust", json=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ADJUSTED"

    response = client.get("/api/highlights")
    data = response.json()
    assert data[0]["start_pts"] == 12.0
    assert data[0]["end_pts"] == 18.0


def test_llm_analyze_endpoint(client, db_with_highlights):
    mock_result = LLMRefineResult(
        refined_start_pts=12.0,
        refined_end_pts=22.0,
        content_type="funny",
        confidence=0.85,
        reasoning="adjusted start",
    )
    with patch("src.api.main._llm_gate") as mock_gate:
        mock_gate.refine_boundary.return_value = mock_result
        resp = client.post("/api/highlights/1/llm-analyze")
        assert resp.status_code == 200
        body = resp.json()
        assert body["refined_start_pts"] == 12.0
        assert body["refined_end_pts"] == 22.0
        mock_gate.refine_boundary.assert_called_once()
        assert mock_gate.refine_boundary.call_args.kwargs.get("force") is True
