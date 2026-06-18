from dataclasses import dataclass
from typing import List, Optional

from src.core.models import SignalSnapshot


@dataclass
class HistoryEntry:
    snapshot: SignalSnapshot
    pts: float


class SignalHistoryBuffer:
    def __init__(self, capacity_sec: int = 300):
        self.capacity_sec = capacity_sec
        self._entries: List[HistoryEntry] = []

    def append(self, snapshot: SignalSnapshot) -> None:
        pts = snapshot.pts
        self._entries.append(HistoryEntry(snapshot=snapshot, pts=pts))
        latest_pts = pts
        self._entries = [
            e for e in self._entries
            if latest_pts - e.pts <= self.capacity_sec
        ]

    def get_at(self, pts: float) -> Optional[SignalSnapshot]:
        tolerance = 2.5
        nearest: Optional[HistoryEntry] = None
        min_dist = float("inf")
        for entry in self._entries:
            dist = abs(entry.pts - pts)
            if dist <= tolerance and dist < min_dist:
                min_dist = dist
                nearest = entry
        return nearest.snapshot if nearest else None

    def get_range(self, start_pts: float, end_pts: float) -> List[HistoryEntry]:
        return [
            e for e in self._entries
            if start_pts <= e.pts <= end_pts
        ]

    def oldest_pts(self) -> float:
        if not self._entries:
            return 0.0
        return min(e.pts for e in self._entries)
