from typing import List

from src.core.models import ResolvedEvent


class PendingEventQueue:
    MAX_WAIT_SEC = 30.0

    def __init__(self, max_wait_sec: float = MAX_WAIT_SEC):
        self.MAX_WAIT_SEC = max_wait_sec
        self._items: List[ResolvedEvent] = []
        self._enqueue_pts: List[float] = []

    def enqueue(self, event: ResolvedEvent, current_pts: float) -> None:
        self._items.append(event)
        self._enqueue_pts.append(current_pts)

    def is_ready(self, current_pts: float) -> bool:
        if len(self._items) >= 2:
            return True
        if self._items and current_pts - self._enqueue_pts[0] >= self.MAX_WAIT_SEC:
            return True
        return False

    def drain(self) -> List[ResolvedEvent]:
        items = list(self._items)
        self._items.clear()
        self._enqueue_pts.clear()
        return items
