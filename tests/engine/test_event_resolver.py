import pytest

from src.core.models import ResolvedEvent
from src.engine.event_resolver import EventResolver


def test_merge_overlapping_same_topic():
    resolver = EventResolver()
    a = ResolvedEvent(0, 50, 30, 0.9, ["ôi", "trời"], "ôi trời ơi")
    b = ResolvedEvent(40, 80, 60, 0.7, ["ôi", "trời"], "ôi trời không")
    result = resolver.resolve([a, b])
    assert len(result.events) == 1
    assert result.events[0].peak_score == 0.9
    assert result.events[0].start_pts == 0
    assert result.events[0].end_pts == 80


def test_keep_both_different_topic():
    resolver = EventResolver()
    a = ResolvedEvent(0, 50, 30, 0.8, ["game", "win"], "thắng game")
    b = ResolvedEvent(40, 80, 60, 0.7, ["ăn", "ngon"], "ăn ngon quá")
    result = resolver.resolve([a, b])
    assert len(result.events) == 2
    assert len(result.ambiguous_pairs) == 0
    midpoint = (50 + 40) / 2
    assert result.events[0].end_pts == pytest.approx(midpoint)
    assert result.events[1].start_pts == pytest.approx(midpoint)


def test_adjacent_merge_same_topic():
    resolver = EventResolver()
    a = ResolvedEvent(0, 50, 25, 0.8, ["game", "play"], "game play fun")
    b = ResolvedEvent(52, 90, 70, 0.7, ["game", "play"], "game play win")
    result = resolver.resolve([a, b])
    assert len(result.events) == 1
    assert result.events[0].peak_score == 0.8
    assert result.events[0].start_pts == 0
    assert result.events[0].end_pts == 90


def test_ambiguous_pair_in_result():
    resolver = EventResolver()
    a = ResolvedEvent(0, 50, 30, 0.8, ["game", "win", "play"], "game win play")
    b = ResolvedEvent(40, 80, 60, 0.7, ["game", "play", "fun"], "game play fun")
    result = resolver.resolve([a, b])
    assert len(result.events) == 2
    assert len(result.ambiguous_pairs) == 1
    pair = result.ambiguous_pairs[0]
    assert 0.3 < pair.similarity < 0.7
    assert pair.event_a.start_pts == 0
    assert pair.event_b.start_pts == 40
