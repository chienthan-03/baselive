"""
StreamManager: manages up to MAX_CONCURRENT StreamWorker instances.
One worker thread per active stream.
"""
import logging
import threading
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from src.db.database import Database
from src.engine.pipeline import MasterPipeline
from src.ingestion.stream_worker import StreamWorker

logger = logging.getLogger(__name__)


class CapacityError(Exception):
    """Raised when MAX_CONCURRENT streams are already running."""


class StreamAlreadyRunningError(Exception):
    """Raised when start_stream is called for an already-active stream_id."""


@dataclass
class _StreamEntry:
    worker: StreamWorker
    thread: threading.Thread


WorkerFactory = Callable[[str, str], StreamWorker]


class StreamManager:
    MAX_CONCURRENT = 3

    def __init__(
        self,
        db_path: str = "base_live.db",
        output_dir: str = "output/clips",
        worker_factory: Optional[WorkerFactory] = None,
    ):
        self._db_path = db_path
        self._output_dir = output_dir
        self._worker_factory = worker_factory
        self._streams: Dict[str, _StreamEntry] = {}
        self._lock = threading.Lock()

    def start_stream(self, url: str, stream_id: str) -> StreamWorker:
        with self._lock:
            if stream_id in self._streams:
                raise StreamAlreadyRunningError(f"Stream {stream_id} already running")
            if len(self._streams) >= self.MAX_CONCURRENT:
                raise CapacityError("Maximum concurrent streams reached")

            worker = self._create_worker(url, stream_id)
            thread = threading.Thread(
                target=worker.run,
                name=f"stream-{stream_id}",
                daemon=True,
            )
            self._streams[stream_id] = _StreamEntry(worker=worker, thread=thread)
            thread.start()
            logger.info("Started stream %s (%s)", stream_id, url)
            return worker

    def stop_stream(self, stream_id: str) -> None:
        with self._lock:
            entry = self._streams.pop(stream_id, None)
        if entry is None:
            raise KeyError(f"Stream {stream_id} not found")
        entry.worker.stop()
        entry.thread.join(timeout=5.0)
        logger.info("Stopped stream %s", stream_id)

    def list_active(self) -> List[str]:
        with self._lock:
            return list(self._streams.keys())

    def list_streams(self) -> List[dict]:
        with self._lock:
            return [
                {
                    "stream_id": stream_id,
                    "url": entry.worker.url,
                    "running": entry.worker._running,
                }
                for stream_id, entry in self._streams.items()
            ]

    def _create_worker(self, url: str, stream_id: str) -> StreamWorker:
        if self._worker_factory is not None:
            return self._worker_factory(url, stream_id)

        db = Database(self._db_path)
        db.init_db()
        stream_output = f"{self._output_dir}/{stream_id}"
        pipeline = MasterPipeline(
            output_dir=stream_output,
            db=db,
            stream_id=stream_id,
        )
        return StreamWorker(
            url=url,
            username=stream_id,
            pipeline=pipeline,
            output_dir=stream_output,
        )
