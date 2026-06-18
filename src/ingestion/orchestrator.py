"""
OrchestratorService: coordinates WorkerNode, StreamRegistry, and Database.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from src.db.database import Database
from src.ingestion.platforms import create_default_registry
from src.ingestion.stream_registry import StreamInfo, StreamRegistry
from src.ingestion.worker_node import CapacityError, WorkerNode

try:
    from src.observability.metrics import MetricsCollector
except Exception:  # pragma: no cover - optional dependency
    MetricsCollector = None  # type: ignore[misc, assignment]

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "orchestrator.json"
)

NODE_ID = "node-0"

WorkerFactory = Callable[[str, str], Any]


class StreamAlreadyRunningError(Exception):
    """Raised when start_stream is called for an already-active stream_id."""


class PlatformNotSupportedError(Exception):
    """Raised when the requested platform is not supported."""


class OrchestratorService:
    def __init__(
        self,
        db_path: str = "base_live.db",
        output_dir: str = "output",
        worker_factory: Optional[WorkerFactory] = None,
        max_streams_per_node: Optional[int] = None,
        metrics=None,
        config_path: Optional[Path] = None,
    ):
        config = self._load_config(config_path or _DEFAULT_CONFIG_PATH)
        self._max_streams = max_streams_per_node or config.get("max_streams_per_node", 5)
        self._heartbeat_interval = config.get("heartbeat_interval_sec", 30)

        self._db_path = db_path
        self._output_dir = output_dir
        self._worker_factory = worker_factory
        if metrics is None and MetricsCollector is not None:
            try:
                metrics = MetricsCollector.get_instance()
            except Exception:
                metrics = None
        self._metrics = metrics

        self._db = Database(db_path)
        self._db.init_db()
        self._platform_registry = create_default_registry()
        self._registry = StreamRegistry(db=self._db)
        self._worker_node = WorkerNode(node_id=NODE_ID, max_streams=self._max_streams)
        self._lock = threading.Lock()

        interrupted = self.recover_streams()
        if interrupted:
            logger.info(
                "Startup: %d stream(s) marked INTERRUPTED (restart to resume): %s",
                len(interrupted),
                interrupted,
            )
        else:
            logger.info("Startup: no streams to recover")
        logger.info("Orchestrator ready (node=%s, max_streams=%d)", NODE_ID, self._max_streams)

        self._heartbeat_stop = threading.Event()
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_loop,
            name="orchestrator-heartbeat",
            daemon=True,
        )
        self._heartbeat_thread.start()

    @staticmethod
    def _load_config(path: Path) -> dict:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)

    def recover_streams(self) -> List[str]:
        running = self._db.list_streams_by_status("RUNNING")
        interrupted_ids: List[str] = []
        for row in running:
            stream_id = row["stream_id"]
            self._db.update_stream_status(stream_id, "INTERRUPTED")
            self._registry.register(
                StreamInfo(
                    stream_id=stream_id,
                    platform=row["platform"],
                    url=row["url"],
                    node_id=row["node_id"],
                    started_at=row["started_at"],
                    status="INTERRUPTED",
                    ended_at=row.get("ended_at"),
                )
            )
            interrupted_ids.append(stream_id)
            logger.info("Recovered stream %s as INTERRUPTED", stream_id)
        return interrupted_ids

    def start_stream(self, url: str, stream_id: str, platform: str = "tiktok") -> None:
        try:
            adapter = self._platform_registry.get(platform)
        except KeyError as exc:
            raise PlatformNotSupportedError(platform) from exc
        if not adapter.is_available():
            raise PlatformNotSupportedError(platform)

        with self._lock:
            if stream_id in self._worker_node.list_stream_ids():
                raise StreamAlreadyRunningError(f"Stream {stream_id} already running")

            worker = self._create_worker(url, stream_id, platform=platform)
            self._worker_node.assign_stream(stream_id, worker)

            started_at = time.time()
            self._db.upsert_stream(
                stream_id,
                platform=platform,
                url=url,
                status="RUNNING",
                node_id=NODE_ID,
                started_at=started_at,
            )
            self._registry.register(
                StreamInfo(
                    stream_id=stream_id,
                    platform=platform,
                    url=url,
                    node_id=NODE_ID,
                    started_at=started_at,
                    status="RUNNING",
                )
            )
            logger.info("Started stream %s (%s) on %s", stream_id, url, NODE_ID)

        self._inc_stream_started(platform)
        self._update_metrics()

    def stop_stream(self, stream_id: str) -> None:
        info = self._registry.get(stream_id)
        platform = info.platform if info is not None else "tiktok"

        with self._lock:
            self._worker_node.remove_stream(stream_id)
            ended_at = time.time()
            self._db.update_stream_status(stream_id, "STOPPED", ended_at=ended_at)
            self._registry.update_status(stream_id, "STOPPED", ended_at=ended_at)
            logger.info("Stopped stream %s", stream_id)

        self._inc_stream_stopped(platform, reason="manual")
        self._update_metrics()

    def list_streams(self) -> List[dict]:
        result: List[dict] = []
        for stream_id in self._worker_node.list_stream_ids():
            info = self._registry.get(stream_id)
            if info is None:
                continue
            result.append(
                {
                    "stream_id": info.stream_id,
                    "platform": info.platform,
                    "url": info.url,
                    "status": info.status,
                    "node_id": info.node_id,
                }
            )
        return result

    def list_active(self) -> List[str]:
        return self._worker_node.list_stream_ids()

    def list_platforms(self) -> List[dict]:
        return self._platform_registry.list_platforms()

    def list_interrupted(self) -> List[dict]:
        rows = self._db.list_streams_by_status("INTERRUPTED")
        return [
            {
                "stream_id": row["stream_id"],
                "platform": row["platform"],
                "url": row["url"],
                "status": row["status"],
                "node_id": row["node_id"],
                "started_at": row["started_at"],
                "ended_at": row.get("ended_at"),
            }
            for row in rows
        ]

    def get_node_health(self) -> List[dict]:
        return [self._worker_node.heartbeat()]

    def _heartbeat_loop(self) -> None:
        while not self._heartbeat_stop.is_set():
            self._update_metrics()
            self._heartbeat_stop.wait(self._heartbeat_interval)

    def _inc_stream_started(self, platform: str) -> None:
        if self._metrics is None:
            return
        try:
            self._metrics.inc_stream_started(platform)
        except Exception:
            logger.debug("Failed to record streams_started_total", exc_info=True)

    def _inc_stream_stopped(self, platform: str, reason: str) -> None:
        if self._metrics is None:
            return
        try:
            self._metrics.inc_stream_stopped(platform, reason)
        except Exception:
            logger.debug("Failed to record streams_stopped_total", exc_info=True)

    def _update_metrics(self) -> None:
        if self._metrics is None:
            return

        hb = self._worker_node.heartbeat()
        self._metrics.set_node_healthy(hb["node_id"], hb["healthy"])

        platform_counts: Dict[str, int] = {}
        for stream_id in hb["stream_ids"]:
            info = self._registry.get(stream_id)
            plat = info.platform if info is not None else "tiktok"
            platform_counts[plat] = platform_counts.get(plat, 0) + 1

        if not platform_counts:
            self._metrics.set_streams_active(0, "tiktok", hb["node_id"])
            return

        for platform, count in platform_counts.items():
            self._metrics.set_streams_active(count, platform, hb["node_id"])

    def _create_worker(self, url: str, stream_id: str, platform: str = "tiktok") -> Any:
        if self._worker_factory is not None:
            return self._worker_factory(url, stream_id)

        try:
            adapter = self._platform_registry.get(platform)
        except KeyError as exc:
            raise PlatformNotSupportedError(platform) from exc

        from src.engine.pipeline import MasterPipeline
        from src.ingestion.stream_worker import StreamWorker

        stream_output = f"{self._output_dir}/{stream_id}"
        pipeline = MasterPipeline(
            output_dir="output/clips",
            db=self._db,
            stream_id=stream_id,
        )
        return StreamWorker(
            url=url,
            username=adapter.extract_username(url),
            adapter=adapter,
            pipeline=pipeline,
            output_dir=stream_output,
            metrics=self._metrics,
        )
