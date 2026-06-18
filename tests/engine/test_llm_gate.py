from unittest.mock import patch

import pytest

from src.core.models import AmbiguousPair, BoundaryResult, EventCandidate, ResolvedEvent
from src.engine.llm_gate import LLMGate, LLMRefineResult


@pytest.fixture
def boundary():
    return BoundaryResult(
        trigger_pts=95.0,
        resolution_pts=145.0,
        peak_pts=120.0,
        quality="complete",
        context_status="ok",
        stop_reason="silence",
    )


@pytest.fixture
def mock_openrouter():
    with patch("src.engine.llm_gate.LLMGate._call_openrouter") as mock:
        yield mock


def test_llm_gate_disabled_without_api_key(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    gate = LLMGate()
    assert gate.enabled is False


def test_llm_gate_refine_boundary(mock_openrouter, boundary):
    gate = LLMGate(api_key="test-key")
    mock_openrouter.return_value = {
        "refined_start_pts": 98.5,
        "refined_end_pts": 142.0,
        "content_type": "funny",
        "confidence": 0.82,
        "reasoning": "setup-punchline",
    }
    result = gate.refine_boundary(
        boundary,
        transcript="ôi trời ơi",
        signals_summary={"peak_score": 0.85},
    )
    assert isinstance(result, LLMRefineResult)
    assert result.refined_start_pts == 98.5
    assert result.refined_end_pts == 142.0
    assert result.content_type == "funny"
    assert result.confidence == 0.82


def test_llm_gate_rate_limit_blocks_excess_calls(mock_openrouter, boundary):
    mock_openrouter.return_value = {
        "refined_start_pts": 98.5,
        "refined_end_pts": 142.0,
        "content_type": "funny",
        "confidence": 0.82,
        "reasoning": "ok",
    }
    gate = LLMGate(api_key="test-key")
    base_time = 1_000_000.0

    with patch("src.engine.llm_gate.time.time") as mock_time:
        for i in range(10):
            mock_time.return_value = base_time + i * 31
            result = gate.refine_boundary(
                boundary,
                transcript="test",
                signals_summary={},
            )
            assert result is not None

        mock_time.return_value = base_time + 10 * 31
        result = gate.refine_boundary(
            boundary,
            transcript="test",
            signals_summary={},
        )
        assert result is None
        assert mock_openrouter.call_count == 10


def test_should_refine_boundary_peak_score(boundary):
    gate = LLMGate(api_key="test-key")
    event = EventCandidate(state="CLOSED", peak_score=0.75)
    assert gate.should_refine_boundary(event, boundary) is True


def test_should_refine_boundary_long_duration(boundary):
    gate = LLMGate(api_key="test-key")
    long_boundary = BoundaryResult(
        trigger_pts=10.0,
        resolution_pts=200.0,
        peak_pts=100.0,
        quality="complete",
        context_status="ok",
        stop_reason="silence",
    )
    event = EventCandidate(state="CLOSED", peak_score=0.5)
    assert gate.should_refine_boundary(event, long_boundary) is True


def test_refine_boundary_fallback_on_error(mock_openrouter, boundary):
    gate = LLMGate(api_key="test-key")
    mock_openrouter.side_effect = RuntimeError("API down")
    result = gate.refine_boundary(
        boundary,
        transcript="test",
        signals_summary={},
    )
    assert result is None


def test_resolve_overlap_returns_decision(mock_openrouter):
    gate = LLMGate(api_key="test-key")
    mock_openrouter.return_value = {
        "decision": "MERGE",
        "confidence": 0.9,
        "reasoning": "same topic",
    }
    pair = AmbiguousPair(
        event_a=ResolvedEvent(
            start_pts=10.0,
            end_pts=50.0,
            peak_pts=30.0,
            peak_score=0.8,
            keywords=["a"],
            transcript_excerpt="a",
        ),
        event_b=ResolvedEvent(
            start_pts=40.0,
            end_pts=80.0,
            peak_pts=60.0,
            peak_score=0.7,
            keywords=["b"],
            transcript_excerpt="b",
        ),
        similarity=0.5,
    )
    result = gate.resolve_overlap(pair)
    assert result is not None
    assert result.decision == "MERGE"
