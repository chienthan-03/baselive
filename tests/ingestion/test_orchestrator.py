import threading
import time

import pytest

from src.db.database import Database
from src.ingestion.orchestrator import (
    CapacityError,
    OrchestratorService,
    PlatformNotSupportedError,
    StreamAlreadyRunningError,
)


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


def _fake_factory(url: str, stream_id: str) -> _FakeWorker:
    return _FakeWorker(url, stream_id)


@pytest.fixture
def fake_factory():
    return _fake_factory


@pytest.fixture
def orchestrator(fake_factory):
    orch = OrchestratorService(worker_factory=fake_factory, db_path=":memory:")
    yield orch
    for stream_id in orch.list_active():
        try:
            orch.stop_stream(stream_id)
        except KeyError:
            pass


def test_orchestrator_start_stop(fake_factory, tmp_path):
    orch = OrchestratorService(
        db_path=":memory:",
        output_dir=str(tmp_path),
        worker_factory=fake_factory,
    )
    orch.start_stream("http://test", "s1", platform="tiktok")
    assert "s1" in [s["stream_id"] for s in orch.list_streams()]
    orch.stop_stream("s1")
    assert orch.list_streams() == []


def test_orchestrator_capacity_5(fake_factory):
    orch = OrchestratorService(
        worker_factory=fake_factory,
        max_streams_per_node=5,
        db_path=":memory:",
    )
    for i in range(5):
        orch.start_stream(f"http://t{i}", f"s{i}")
    with pytest.raises(CapacityError):
        orch.start_stream("http://t6", "s6")


def test_orchestrator_rejects_non_tiktok_platform(fake_factory):
    orch = OrchestratorService(worker_factory=fake_factory, db_path=":memory:")
    with pytest.raises(PlatformNotSupportedError):
        orch.start_stream("http://yt", "s1", platform="youtube")


def test_recover_marks_interrupted(fake_factory, tmp_path):
    db_path = tmp_path / "test.db"
    db = Database(str(db_path))
    db.init_db()
    db.upsert_stream(
        "s1",
        platform="tiktok",
        url="http://x",
        status="RUNNING",
        node_id="node-0",
        started_at=100.0,
    )
    db.close()

    orch = OrchestratorService(db_path=str(db_path), worker_factory=fake_factory)
    row = orch._db.get_stream("s1")
    assert row is not None
    assert row["status"] == "INTERRUPTED"
    reg_info = orch._registry.get("s1")
    assert reg_info is not None
    assert reg_info.status == "INTERRUPTED"


def test_duplicate_stream_raises(orchestrator):
    orchestrator.start_stream("http://test", "s1")
    with pytest.raises(StreamAlreadyRunningError):
        orchestrator.start_stream("http://other", "s1")


def test_loads_orchestrator_config(fake_factory):
    orch = OrchestratorService(worker_factory=fake_factory, db_path=":memory:")
    for i in range(5):
        orch.start_stream(f"http://t{i}", f"s{i}")
    with pytest.raises(CapacityError):
        orch.start_stream("http://t6", "s6")


def test_get_node_health(orchestrator):
    health = orchestrator.get_node_health()
    assert len(health) == 1
    assert health[0]["node_id"] == "node-0"
    assert health[0]["healthy"] is True
    assert health[0]["active_count"] == 0

    orchestrator.start_stream("http://test", "s1")
    health = orchestrator.get_node_health()
    assert health[0]["active_count"] == 1
    assert "s1" in health[0]["stream_ids"]
