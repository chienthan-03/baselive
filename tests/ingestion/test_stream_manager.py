import threading
import time

import pytest

from src.ingestion.orchestrator import OrchestratorService
from src.ingestion.stream_manager import CapacityError, StreamAlreadyRunningError, StreamManager


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
def manager():
    orch = OrchestratorService(
        worker_factory=_fake_factory,
        db_path=":memory:",
        max_streams_per_node=3,
    )
    mgr = StreamManager(orchestrator=orch)
    yield mgr
    for stream_id in mgr.list_active():
        try:
            mgr.stop_stream(stream_id)
        except KeyError:
            pass


def test_stream_manager_max_concurrent(manager):
    manager.start_stream("url1", "s1")
    manager.start_stream("url2", "s2")
    manager.start_stream("url3", "s3")
    with pytest.raises(CapacityError):
        manager.start_stream("url4", "s4")


def test_start_stream_registers_active_stream(manager):
    manager.start_stream("http://test", "s1")
    assert "s1" in manager.list_active()


def test_stop_stream_removes_from_active(manager):
    manager.start_stream("http://test", "s1")
    manager.stop_stream("s1")
    assert manager.list_active() == []


def test_duplicate_stream_raises(manager):
    manager.start_stream("http://test", "s1")
    with pytest.raises(StreamAlreadyRunningError):
        manager.start_stream("http://other", "s1")


def test_list_streams_returns_metadata(manager):
    manager.start_stream("http://test", "s1")
    streams = manager.list_streams()
    assert len(streams) == 1
    assert streams[0]["stream_id"] == "s1"
    assert streams[0]["url"] == "http://test"
    assert streams[0]["status"] == "RUNNING"
