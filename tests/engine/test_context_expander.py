import pytest

from src.buffer.circular_buffer import TranscriptBuffer
from src.buffer.signal_history import SignalHistoryBuffer
from src.core.models import (
    BoundaryResult,
    EventCandidate,
    EventHistoryStore,
    ResolvedEvent,
    SignalSnapshot,
    TranscriptResult,
)
from src.engine.context_expander import ContextExpander, topic_jaccard


def test_topic_jaccard():
    a = {"ôi", "trời", "ơi"}
    b = {"ôi", "trời", "không"}
    assert topic_jaccard(a, b) == pytest.approx(2 / 4)


def test_topic_jaccard_empty_union():
    assert topic_jaccard(set(), set()) == 1.0


def test_look_back_stops_at_silence_gap():
    expander = ContextExpander()
    history = SignalHistoryBuffer(capacity_sec=120)
    for pts in range(0, 65, 5):
        silence = 4.0 if pts <= 40 else 0.0
        score = 0.1 if pts <= 40 else 0.8
        history.append(
            SignalSnapshot(pts=float(pts), composite_score=score, silence_before=silence)
        )
    trigger = expander.look_back(
        peak_pts=60.0,
        history=history,
        transcript=TranscriptBuffer(capacity_sec=900),
        event_history=EventHistoryStore(),
    )
    assert trigger < 60.0
    assert trigger >= 40.0


def test_look_back_stops_at_max_lookback():
    expander = ContextExpander()
    history = SignalHistoryBuffer(capacity_sec=600)
    for pts in range(0, 500, 5):
        history.append(SignalSnapshot(pts=float(pts), composite_score=0.8))
    trigger = expander.look_back(
        peak_pts=400.0,
        history=history,
        transcript=TranscriptBuffer(capacity_sec=900),
        event_history=EventHistoryStore(),
    )
    assert trigger == pytest.approx(400.0 - ContextExpander.MAX_LOOKBACK)


def test_look_back_stops_at_buffer_limit():
    expander = ContextExpander()
    history = SignalHistoryBuffer(capacity_sec=60)
    for pts in range(100, 200, 5):
        history.append(SignalSnapshot(pts=float(pts), composite_score=0.8))
    trigger = expander.look_back(
        peak_pts=195.0,
        history=history,
        transcript=TranscriptBuffer(capacity_sec=900),
        event_history=EventHistoryStore(),
    )
    assert trigger >= history.oldest_pts()
    assert trigger < 195.0


def test_look_back_stops_at_prior_event():
    expander = ContextExpander()
    history = SignalHistoryBuffer(capacity_sec=300)
    for pts in range(0, 300, 5):
        history.append(SignalSnapshot(pts=float(pts), composite_score=0.8))
    event_history = EventHistoryStore()
    event_history.append(
        ResolvedEvent(
            start_pts=50.0,
            end_pts=120.0,
            peak_pts=90.0,
            peak_score=0.9,
            keywords=["ôi"],
            transcript_excerpt="",
        )
    )
    trigger = expander.look_back(
        peak_pts=200.0,
        history=history,
        transcript=TranscriptBuffer(capacity_sec=900),
        event_history=event_history,
    )
    assert trigger == pytest.approx(120.0)


def test_look_back_stops_at_topic_change():
    expander = ContextExpander()
    history = SignalHistoryBuffer(capacity_sec=120)
    for pts in range(0, 80, 5):
        keywords = ["ôi", "trời", "ơi"] if pts >= 50 else ["bóng", "đá", "thể", "thao"]
        history.append(
            SignalSnapshot(
                pts=float(pts),
                composite_score=0.7,
                keyword_triggered=keywords,
            )
        )
    trigger = expander.look_back(
        peak_pts=75.0,
        history=history,
        transcript=TranscriptBuffer(capacity_sec=900),
        event_history=EventHistoryStore(),
    )
    assert trigger < 75.0
    assert trigger >= 45.0


def test_look_back_uses_transcript_keywords():
    expander = ContextExpander()
    history = SignalHistoryBuffer(capacity_sec=120)
    for pts in range(0, 80, 5):
        history.append(SignalSnapshot(pts=float(pts), composite_score=0.7))
    transcript = TranscriptBuffer(capacity_sec=900)
    transcript.add_item(
        TranscriptResult(text="ôi trời ơi không thể tin", segments=[], language="vi", chunk_start_pts=70.0),
        pts=70.0,
    )
    transcript.add_item(
        TranscriptResult(text="bóng đá thể thao hôm nay", segments=[], language="vi", chunk_start_pts=10.0),
        pts=10.0,
    )
    trigger = expander.look_back(
        peak_pts=75.0,
        history=history,
        transcript=transcript,
        event_history=EventHistoryStore(),
    )
    assert trigger < 75.0


def test_look_forward_stops_at_low_score():
    expander = ContextExpander()
    history = SignalHistoryBuffer(capacity_sec=200)
    for pts in range(0, 100, 5):
        score = 0.8 if pts < 70 else 0.1
        history.append(
            SignalSnapshot(pts=float(pts), composite_score=score, chat_volume_spike=0.5)
        )
    resolution = expander.look_forward(
        peak_pts=60.0,
        close_pts=70.0,
        history=history,
        transcript=TranscriptBuffer(capacity_sec=900),
        chat_volume_ratio=0.5,
    )
    assert resolution > 70.0
    assert resolution <= 60.0 + ContextExpander.MAX_LOOKFORWARD


def test_expand_returns_boundary_result():
    expander = ContextExpander()
    event = EventCandidate(
        state="CLOSED", start_pts=50.0, end_pts=80.0, peak_pts=60.0, peak_score=0.85
    )
    history = SignalHistoryBuffer(capacity_sec=200)
    for pts in range(0, 100, 5):
        history.append(SignalSnapshot(pts=float(pts), composite_score=0.8))
    result = expander.expand(
        event,
        resolution_pts=95.0,
        history=history,
        transcript=TranscriptBuffer(capacity_sec=900),
        event_history=EventHistoryStore(),
    )
    assert isinstance(result, BoundaryResult)
    assert result.trigger_pts <= result.peak_pts <= result.resolution_pts
