import threading
import time

import pytest

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
  mgr = StreamManager(worker_factory=_fake_factory)
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


def test_start_stream_returns_worker(manager):
  worker = manager.start_stream("http://test", "s1")
  assert worker.url == "http://test"
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
