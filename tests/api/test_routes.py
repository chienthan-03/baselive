import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from src.api.main import app, get_db, get_orchestrator, get_stream_manager
from src.db.database import Database
from src.engine.llm_gate import LLMRefineResult
from src.ingestion.orchestrator import OrchestratorService
from src.ingestion.stream_manager import StreamManager


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
def stream_client(test_db):
    import threading
    import time

    class _FakeWorker:
        def __init__(self, url: str, stream_id: str):
            self.url = url
            self.username = stream_id
            self._running = False
            self._stop_event = threading.Event()

        def run(self) -> None:
            self._running = True
            while not self._stop_event.is_set():
                time.sleep(0.01)

        def stop(self) -> None:
            self._running = False
            self._stop_event.set()

    orch = OrchestratorService(
        worker_factory=lambda url, sid: _FakeWorker(url, sid),
        db_path=":memory:",
        max_streams_per_node=3,
    )
    mgr = StreamManager(orchestrator=orch)

    def override_get_db():
        yield test_db

    def override_get_orchestrator():
        return orch

    def override_get_stream_manager():
        return mgr

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_orchestrator] = override_get_orchestrator
    app.dependency_overrides[get_stream_manager] = override_get_stream_manager
    with TestClient(app) as c:
        yield c, orch
    app.dependency_overrides.clear()
    for stream_id in orch.list_active():
        try:
            orch.stop_stream(stream_id)
        except KeyError:
            pass


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
        mock_gate.budget_tracker.can_call.return_value = True
        mock_gate.refine_boundary.return_value = mock_result
        resp = client.post("/api/highlights/1/llm-analyze")
        assert resp.status_code == 200
        body = resp.json()
        assert body["refined_start_pts"] == 12.0
        assert body["refined_end_pts"] == 22.0
        mock_gate.refine_boundary.assert_called_once()
        assert mock_gate.refine_boundary.call_args.kwargs.get("force") is True
        assert mock_gate.refine_boundary.call_args.kwargs.get("gate") == "editor"


def test_editor_llm_analyze_counts_against_budget(client, db_with_highlights):
    with patch("src.api.main._llm_gate") as mock_gate:
        mock_gate.budget_tracker.can_call.return_value = False
        resp = client.post("/api/highlights/1/llm-analyze")
        assert resp.status_code == 503
        mock_gate.refine_boundary.assert_not_called()


def test_api_start_stream(stream_client):
    client, _ = stream_client
    resp = client.post("/api/streams/start", json={"url": "http://test", "stream_id": "s1"})
    assert resp.status_code == 200
    assert resp.json()["stream_id"] == "s1"


def test_api_list_and_stop_stream(stream_client):
    client, _ = stream_client
    client.post("/api/streams/start", json={"url": "http://test", "stream_id": "s1"})
    resp = client.get("/api/streams")
    assert resp.status_code == 200
    assert "s1" in [s["stream_id"] for s in resp.json()]
    resp = client.post("/api/streams/s1/stop")
    assert resp.status_code == 200


def test_api_start_stream_409_duplicate(stream_client):
    client, _ = stream_client
    client.post("/api/streams/start", json={"url": "http://test", "stream_id": "s1"})
    resp = client.post(
        "/api/streams/start",
        json={"url": "http://other", "stream_id": "s1"},
    )
    assert resp.status_code == 409


def test_api_start_stream_429_at_capacity(stream_client):
    client, _ = stream_client
    for i in range(3):
        client.post("/api/streams/start", json={"url": f"http://test{i}", "stream_id": f"s{i}"})
    resp = client.post("/api/streams/start", json={"url": "http://test4", "stream_id": "s4"})
    assert resp.status_code == 429


def test_api_start_stream_501_non_tiktok_platform(stream_client):
    client, _ = stream_client
    resp = client.post(
        "/api/streams/start",
        json={"url": "http://yt", "stream_id": "s1", "platform": "youtube"},
    )
    assert resp.status_code == 501


def test_api_list_platforms(stream_client):
    client, _ = stream_client
    resp = client.get("/api/platforms")
    assert resp.status_code == 200
    platforms = resp.json()
    ids = {p["id"] for p in platforms}
    assert "tiktok" in ids
    assert "youtube" in ids
    assert "facebook" in ids
    by_id = {p["id"]: p for p in platforms}
    assert by_id["tiktok"]["available"] is True
    assert by_id["youtube"]["available"] is False
    assert by_id["facebook"]["available"] is False


def test_health_liveness(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_metrics_endpoint(client):
    resp = client.get("/metrics")
    assert resp.status_code == 200
    assert "streams_active" in resp.text or "# HELP" in resp.text


def test_health_ready_503_when_stale(stream_client, monkeypatch):
    client, orch = stream_client
    monkeypatch.setattr(
        orch._worker_node,
        "heartbeat",
        lambda: {
            "node_id": "node-0",
            "healthy": True,
            "last_heartbeat_ts": 0.0,
            "active_count": 0,
            "stream_ids": [],
        },
    )
    resp = client.get("/api/health/ready")
    assert resp.status_code == 503


def test_delete_rejected_highlight_success(client, test_db, tmp_path):
    """DELETE should remove rejected highlight and return success."""
    # Insert a rejected highlight
    cursor = test_db.conn.cursor()
    cursor.execute('''
        INSERT INTO highlights (stream_id, start_pts, end_pts, score, status, clip_path)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', ("s1", 10.0, 20.0, 0.8, "REJECTED", str(tmp_path / "clip.mp4")))
    test_db.conn.commit()
    
    # Create the file
    clip_path = tmp_path / "clip.mp4"
    clip_path.write_text("fake video")
    
    # Delete it
    response = client.delete("/api/highlights/1")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "deleted"
    assert str(clip_path) in data["deleted_paths"]
    
    # Verify DB record gone
    cursor.execute("SELECT * FROM highlights WHERE id = 1")
    assert cursor.fetchone() is None
    
    # Verify file deleted
    assert not clip_path.exists()


def test_delete_non_rejected_highlight_fails(client, test_db):
    """DELETE should fail if highlight is not REJECTED."""
    cursor = test_db.conn.cursor()
    cursor.execute('''
        INSERT INTO highlights (stream_id, start_pts, end_pts, score, status)
        VALUES (?, ?, ?, ?, ?)
    ''', ("s1", 10.0, 20.0, 0.8, "PENDING"))
    test_db.conn.commit()
    
    response = client.delete("/api/highlights/1")
    assert response.status_code == 403
    assert "Only rejected highlights" in response.json()["detail"]


def test_delete_nonexistent_highlight_returns_404(client):
    """DELETE should 404 if highlight doesn't exist."""
    response = client.delete("/api/highlights/999")
    assert response.status_code == 404
