import pytest
from src.core.models import SignalSnapshot, EventCandidate

def test_signal_snapshot_initialization():
    snapshot = SignalSnapshot(
        pts=10.5,
        audio_energy=0.8,
        audio_energy_spike=True,
        silence_before=2.0,
        composite_score=0.75
    )
    assert snapshot.composite_score == 0.75
    
def test_event_candidate_initialization():
    event = EventCandidate()
    assert event.state == "IDLE"
