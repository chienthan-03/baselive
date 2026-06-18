import pytest

from src.buffer.signal_history import SignalHistoryBuffer
from src.core.models import ResolvedEvent, SignalSnapshot
from src.engine.event_splitter import EventSplitter, TIKTOK_MAX, TIKTOK_MIN


def _append_score_curve(history: SignalHistoryBuffer, scores_by_pts: dict[float, float]) -> None:
    for pts in sorted(scores_by_pts):
        history.append(
            SignalSnapshot(pts=pts, composite_score=scores_by_pts[pts])
        )


@pytest.fixture
def history_short():
    history = SignalHistoryBuffer(capacity_sec=300)
    for pts in range(0, 125, 5):
        history.append(SignalSnapshot(pts=float(pts), composite_score=0.5))
    return history


@pytest.fixture
def history_multi_peak():
    history = SignalHistoryBuffer(capacity_sec=400)
    scores: dict[float, float] = {}
    for pts in range(0, 305, 5):
        score = 0.15
        if 50 <= pts <= 70:
            score = 0.2 + (1.0 - abs(pts - 60) / 10.0) * 0.75
        elif 130 <= pts <= 150:
            score = 0.2 + (1.0 - abs(pts - 140) / 10.0) * 0.7
        elif 220 <= pts <= 250:
            score = 0.2 + (1.0 - abs(pts - 235) / 15.0) * 0.8
        scores[float(pts)] = score
    _append_score_curve(history, scores)
    return history


@pytest.fixture
def history_with_short_segment():
    history = SignalHistoryBuffer(capacity_sec=400)
    scores: dict[float, float] = {}
    for pts in range(0, 305, 5):
        score = 0.15
        if 50 <= pts <= 70:
            score = 0.2 + (1.0 - abs(pts - 60) / 10.0) * 0.75
        elif 72 <= pts <= 78:
            score = 0.85 - abs(pts - 75) * 0.05
        elif 130 <= pts <= 150:
            score = 0.2 + (1.0 - abs(pts - 140) / 10.0) * 0.7
        elif 220 <= pts <= 250:
            score = 0.2 + (1.0 - abs(pts - 235) / 15.0) * 0.8
        scores[float(pts)] = score
    _append_score_curve(history, scores)
    return history


def test_no_split_under_180s(history_short):
    splitter = EventSplitter()
    event = ResolvedEvent(0, 120, 60, 0.8, [], "")
    result = splitter.split(event, history_short)
    assert len(result) == 1
    assert result[0].start_pts == 0
    assert result[0].end_pts == 120
    assert result[0].pre_roll is None
    assert result[0].post_roll is None


def test_split_long_event_into_micro_highlights(history_multi_peak):
    splitter = EventSplitter()
    event = ResolvedEvent(0, 300, 150, 0.9, [], "")
    result = splitter.split(event, history_multi_peak, platform="tiktok")
    assert len(result) >= 2
    for micro in result:
        duration = micro.end_pts - micro.start_pts
        assert TIKTOK_MIN <= duration <= TIKTOK_MAX
        assert micro.pre_roll == pytest.approx(2.0)
        assert micro.post_roll == pytest.approx(1.0)


def test_discards_micro_highlight_under_15s(history_with_short_segment):
    splitter = EventSplitter()
    event = ResolvedEvent(0, 300, 150, 0.9, [], "")
    result = splitter.split(event, history_with_short_segment, platform="tiktok")
    assert len(result) >= 2
    for micro in result:
        assert micro.end_pts - micro.start_pts >= 15.0
    peak_pts = [micro.peak_pts for micro in result]
    assert not any(72 <= pts <= 78 for pts in peak_pts)
