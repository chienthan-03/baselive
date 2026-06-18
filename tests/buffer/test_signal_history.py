from src.buffer.signal_history import SignalHistoryBuffer
from src.core.models import SignalSnapshot

def test_signal_history_append_and_get_range():
    buf = SignalHistoryBuffer(capacity_sec=60)
    for i in range(5):
        buf.append(SignalSnapshot(pts=float(i * 5), composite_score=0.1 * i))
    entries = buf.get_range(5.0, 20.0)
    assert len(entries) == 4
    assert entries[0].pts == 5.0

def test_signal_history_evicts_old_entries():
    buf = SignalHistoryBuffer(capacity_sec=10)
    buf.append(SignalSnapshot(pts=0.0, composite_score=0.1))
    buf.append(SignalSnapshot(pts=15.0, composite_score=0.9))
    assert buf.oldest_pts() >= 5.0
