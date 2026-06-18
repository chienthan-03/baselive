import threading
import time

import pytest

from src.ingestion.worker_node import CapacityError, WorkerNode


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


@pytest.fixture
def node():
    worker_node = WorkerNode(node_id="node-0", max_streams=2)
    yield worker_node
    for stream_id in worker_node.list_stream_ids():
        try:
            worker_node.remove_stream(stream_id)
        except KeyError:
            pass


def test_worker_node_capacity(node):
    node.assign_stream("s1", _FakeWorker("http://test1", "s1"))
    node.assign_stream("s2", _FakeWorker("http://test2", "s2"))
    assert node.list_stream_ids() == ["s1", "s2"]

    with pytest.raises(CapacityError):
        node.assign_stream("s3", _FakeWorker("http://test3", "s3"))


def test_worker_node_heartbeat():
    node = WorkerNode(node_id="node-0", max_streams=5)
    hb = node.heartbeat()
    assert hb["node_id"] == "node-0"
    assert hb["healthy"] is True
    assert hb["active_count"] == 0
    assert hb["stream_ids"] == []
    assert isinstance(hb["last_heartbeat_ts"], float)
