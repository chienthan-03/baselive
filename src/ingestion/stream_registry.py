"""In-memory stream index synced with the SQLite streams table."""
from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Dict, List, Optional

from src.db.database import Database


@dataclass
class StreamInfo:
    stream_id: str
    platform: str
    url: str
    node_id: str
    started_at: float
    status: str
    ended_at: Optional[float] = None


class StreamRegistry:
    def __init__(self, db: Optional[Database] = None):
        self._db = db
        self._streams: Dict[str, StreamInfo] = {}
        self._lock = threading.Lock()

    def register(self, info: StreamInfo) -> None:
        with self._lock:
            self._streams[info.stream_id] = info

    def get(self, stream_id: str) -> Optional[StreamInfo]:
        with self._lock:
            return self._streams.get(stream_id)

    def update_status(
        self,
        stream_id: str,
        status: str,
        *,
        ended_at: Optional[float] = None,
    ) -> None:
        with self._lock:
            info = self._streams.get(stream_id)
            if info is None:
                return
            info.status = status
            if ended_at is not None:
                info.ended_at = ended_at

    def list_active(self) -> List[StreamInfo]:
        with self._lock:
            return [
                info
                for info in self._streams.values()
                if info.status == "RUNNING"
            ]

    def sync_from_db(self) -> None:
        if self._db is None:
            return
        rows = self._db.list_streams_by_status("RUNNING")
        with self._lock:
            for row in rows:
                self._streams[row["stream_id"]] = StreamInfo(
                    stream_id=row["stream_id"],
                    platform=row["platform"],
                    url=row["url"],
                    node_id=row["node_id"],
                    started_at=row["started_at"],
                    status=row["status"],
                    ended_at=row.get("ended_at"),
                )
