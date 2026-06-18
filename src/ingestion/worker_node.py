"""
WorkerNode: manages up to max_streams StreamWorker instances on one node.
One daemon thread per assigned stream.
"""
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class CapacityError(Exception):
    """Raised when max_streams capacity is reached on this node."""


@dataclass
class _StreamEntry:
    worker: Any
    thread: threading.Thread


class WorkerNode:
    def __init__(self, node_id: str, max_streams: int = 5):
        self.node_id = node_id
        self.max_streams = max_streams
        self._streams: Dict[str, _StreamEntry] = {}
        self._lock = threading.Lock()
        self._last_heartbeat_ts = time.time()

    def assign_stream(self, stream_id: str, worker: Any) -> None:
        with self._lock:
            if len(self._streams) >= self.max_streams:
                raise CapacityError("Maximum streams reached for node")

            thread = threading.Thread(
                target=worker.run,
                name=f"stream-{stream_id}",
                daemon=True,
            )
            self._streams[stream_id] = _StreamEntry(worker=worker, thread=thread)
            thread.start()
            logger.info("Assigned stream %s to node %s", stream_id, self.node_id)

    def remove_stream(self, stream_id: str) -> Any:
        with self._lock:
            entry = self._streams.pop(stream_id, None)
        if entry is None:
            raise KeyError(f"Stream {stream_id} not found")
        entry.worker.stop()
        entry.thread.join(timeout=5.0)
        logger.info("Removed stream %s from node %s", stream_id, self.node_id)
        return entry.worker

    def list_stream_ids(self) -> List[str]:
        with self._lock:
            return list(self._streams.keys())

    def heartbeat(self) -> dict:
        with self._lock:
            stream_ids = list(self._streams.keys())
            active_count = len(self._streams)
            healthy = all(entry.thread.is_alive() for entry in self._streams.values())
            self._last_heartbeat_ts = time.time()

        return {
            "node_id": self.node_id,
            "healthy": healthy,
            "last_heartbeat_ts": self._last_heartbeat_ts,
            "active_count": active_count,
            "stream_ids": stream_ids,
        }
