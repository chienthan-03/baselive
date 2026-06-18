import pytest
from fastapi.testclient import TestClient

from src.api.main import app, get_db, get_stream_manager
from src.db.database import Database
from src.engine.llm_gate import LLMRefineResult
from src.ingestion.stream_manager import StreamManager

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

    mgr = StreamManager(worker_factory=lambda url, sid: _FakeWorker(url, sid))

    def override_get_db():
        yield test_db

    def override_get_stream_manager():
        return mgr

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_stream_manager] = override_get_stream_manager
    with TestClient(app) as c:
        yield c, mgr
    app.dependency_overrides.clear()
    for stream_id in mgr.list_active():
        try:
            mgr.stop_stream(stream_id)
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


def test_api_start_stream_429_at_capacity(stream_client):
    client, _ = stream_client
    for i in range(3):
        client.post("/api/streams/start", json={"url": f"http://test{i}", "stream_id": f"s{i}"})
    resp = client.post("/api/streams/start", json={"url": "http://test4", "stream_id": "s4"})
    assert resp.status_code == 429
