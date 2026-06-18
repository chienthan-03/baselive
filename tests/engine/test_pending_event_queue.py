from src.core.models import ResolvedEvent
from src.engine.pending_event_queue import PendingEventQueue


def test_queue_ready_when_two_events():
    q = PendingEventQueue()
    q.enqueue(ResolvedEvent(0, 30, 15, 0.8, [], ""), current_pts=0.0)
    q.enqueue(ResolvedEvent(25, 55, 40, 0.7, [], ""), current_pts=25.0)
    assert q.is_ready(current_pts=55.0) is True


def test_queue_ready_after_timeout():
    q = PendingEventQueue(max_wait_sec=30.0)
    q.enqueue(ResolvedEvent(0, 30, 15, 0.8, [], ""), current_pts=0.0)
    assert q.is_ready(current_pts=35.0) is True
    assert q.is_ready(current_pts=10.0) is False


def test_drain_clears_queue():
    q = PendingEventQueue()
    ev = ResolvedEvent(0, 30, 15, 0.8, [], "")
    q.enqueue(ev, current_pts=0.0)
    drained = q.drain()
    assert drained == [ev]
    assert q.is_ready(current_pts=100.0) is False
