import pytest
from src.core.models import SignalSnapshot, EventCandidate, TranscriptResult, TranscriptSegment

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

def test_transcript_result_structure():
    seg = TranscriptSegment(start=0.0, end=1.2, text="xin chào", confidence=0.92)
    result = TranscriptResult(
        text="xin chào",
        segments=[seg],
        language="vi",
        chunk_start_pts=10.0,
    )
    assert result.segments[0].text == "xin chào"
