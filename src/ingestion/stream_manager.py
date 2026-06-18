"""
StreamManager: deprecated thin wrapper around OrchestratorService.

Prefer OrchestratorService directly for new code.
"""
from __future__ import annotations

from typing import List, Optional

from src.ingestion.orchestrator import OrchestratorService, StreamAlreadyRunningError
from src.ingestion.worker_node import CapacityError

__all__ = [
    "CapacityError",
    "StreamAlreadyRunningError",
    "StreamManager",
]


class StreamManager:
    """Deprecated alias delegating to OrchestratorService."""

    MAX_CONCURRENT = 3

    def __init__(
        self,
        orchestrator: Optional[OrchestratorService] = None,
        *,
        db_path: str = "base_live.db",
        output_dir: str = "output/clips",
        worker_factory=None,
        max_streams_per_node: Optional[int] = None,
    ):
        if orchestrator is not None:
            self._orchestrator = orchestrator
        else:
            kwargs = {"db_path": db_path, "output_dir": output_dir}
            if worker_factory is not None:
                kwargs["worker_factory"] = worker_factory
            if max_streams_per_node is not None:
                kwargs["max_streams_per_node"] = max_streams_per_node
            self._orchestrator = OrchestratorService(**kwargs)

    def start_stream(self, url: str, stream_id: str, platform: str = "tiktok") -> None:
        self._orchestrator.start_stream(url, stream_id, platform=platform)

    def stop_stream(self, stream_id: str) -> None:
        self._orchestrator.stop_stream(stream_id)

    def list_active(self) -> List[str]:
        return self._orchestrator.list_active()

    def list_streams(self) -> List[dict]:
        return self._orchestrator.list_streams()
