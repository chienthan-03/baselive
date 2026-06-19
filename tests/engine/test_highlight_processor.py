import pytest
from unittest.mock import MagicMock, patch

from src.buffer.circular_buffer import TranscriptBuffer
from src.buffer.signal_history import SignalHistoryBuffer
from src.core.models import (
    BoundaryResult,
    EventCandidate,
    ResolvedEvent,
    SignalSnapshot,
)
from src.db.database import Database
from src.engine.highlight_processor import HighlightProcessor
from src.engine.pending_event_queue import PendingEventQueue
from src.engine.state_machine import StateMachine


def _append_score_curve(history: SignalHistoryBuffer, scores_by_pts: dict[float, float]) -> None:
    for pts in sorted(scores_by_pts):
        history.append(
            SignalSnapshot(pts=pts, composite_score=scores_by_pts[pts])
        )


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
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def mock_clip():
    clip = MagicMock()
    clip.generate_final.return_value = "/tmp/final.mp4"
    return clip


@pytest.fixture
def history():
    buf = SignalHistoryBuffer(capacity_sec=600)
    for pts in range(0, 100, 5):
        buf.append(SignalSnapshot(pts=float(pts), composite_score=0.5))
    return buf


@pytest.fixture
def transcript():
    return TranscriptBuffer(capacity_sec=900)


def test_pending_event_queue_ready_with_two_events():
    q = PendingEventQueue()
    ev = ResolvedEvent(
        start_pts=50.0, end_pts=80.0, peak_pts=60.0, peak_score=0.8,
        keywords=[], transcript_excerpt="",
    )
    q.enqueue(ev, current_pts=80.0)
    assert not q.is_ready(85.0)
    q.enqueue(ev, current_pts=90.0)
    assert q.is_ready(90.0)


def test_pending_event_queue_ready_after_timeout():
    q = PendingEventQueue(max_wait_sec=30.0)
    ev = ResolvedEvent(
        start_pts=50.0, end_pts=80.0, peak_pts=60.0, peak_score=0.8,
        keywords=[], transcript_excerpt="",
    )
    q.enqueue(ev, current_pts=80.0)
    assert not q.is_ready(100.0)
    assert q.is_ready(110.0)


def test_highlight_processor_on_closed_enqueues_and_finalizes(
    mock_db, mock_clip, history, transcript
):
    state_machine = StateMachine()
    state_machine.current_event = EventCandidate(
        state="CLOSED",
        peak_pts=60.0,
        start_pts=50.0,
        end_pts=80.0,
        peak_score=0.85,
        draft_highlight_id=42,
    )

    boundary = BoundaryResult(
        trigger_pts=45.0,
        resolution_pts=90.0,
        peak_pts=60.0,
        quality="complete",
        context_status="FULL",
        stop_reason="look_back_complete",
    )

    mock_expander = MagicMock()
    mock_expander.expand.return_value = boundary

    processor = HighlightProcessor(
        context_expander=mock_expander,
        clip_generator=mock_clip,
        db=mock_db,
        state_machine=state_machine,
    )
    processor.pending_queue = PendingEventQueue(max_wait_sec=0)

    event = state_machine.current_event
    processor.on_event_closed(
        event=event,
        history=history,
        transcript=transcript,
        clip_source="live.mp4",
        resolution_pts=90.0,
        current_pts=90.0,
    )

    mock_expander.expand.assert_called_once()
    mock_db.upgrade_to_final.assert_called_once_with(
        42,
        start_pts=45.0,
        end_pts=90.0,
        clip_path="/tmp/final.mp4",
        quality="complete",
    )
    mock_clip.generate_final.assert_called_once()
    gen_args = mock_clip.generate_final.call_args[0]
    assert gen_args[0] == 45.0
    assert gen_args[1] == 90.0
    assert gen_args[2].draft_highlight_id == 42
    assert gen_args[2].peak_pts == 60.0
    assert len(processor.event_history._events) == 1
    assert state_machine.current_event.state == "IDLE"
    assert state_machine.current_event.draft_highlight_id is None


def test_processor_full_pipeline_long_event_split(
    history_multi_peak, transcript, tmp_path
):
    db = Database(db_path=":memory:")
    db.init_db()
    parent_id = db.insert_highlight(
        stream_id="test",
        start_pts=0.0,
        end_pts=300.0,
        score=0.9,
        highlight_type="DRAFT",
        is_growing=0,
        peak_pts=150.0,
    )

    mock_clip = MagicMock()
    mock_clip.generate_final.return_value = str(tmp_path / "final.mp4")

    processor = HighlightProcessor(
        context_expander=MagicMock(),
        clip_generator=mock_clip,
        db=db,
        stream_id="test",
    )
    processor.pending_queue.enqueue(
        ResolvedEvent(
            start_pts=0.0,
            end_pts=300.0,
            peak_pts=150.0,
            peak_score=0.9,
            keywords=[],
            transcript_excerpt="",
            draft_highlight_id=parent_id,
        ),
        current_pts=300.0,
    )

    results = processor.process_pending_queue(
        history_multi_peak, transcript, "live.mp4"
    )

    assert len(results) >= 2
    for record in results:
        assert record["highlight_type"] == "FINAL"

    finals = db.get_highlights(type="FINAL")
    assert len(finals) >= 2
    child_rows = [row for row in finals if row.get("parent_id") == parent_id]
    assert len(child_rows) >= 1
    assert mock_clip.generate_final.call_count >= 2


def test_processor_batch_resolve_overlapping_merge(transcript, tmp_path):
    db = Database(db_path=":memory:")
    db.init_db()
    draft_a = db.insert_highlight(
        stream_id="test",
        start_pts=0.0,
        end_pts=50.0,
        score=0.9,
        highlight_type="DRAFT",
        is_growing=0,
        peak_pts=30.0,
    )
    draft_b = db.insert_highlight(
        stream_id="test",
        start_pts=40.0,
        end_pts=80.0,
        score=0.7,
        highlight_type="DRAFT",
        is_growing=0,
        peak_pts=60.0,
    )

    mock_clip = MagicMock()
    mock_clip.generate_final.return_value = str(tmp_path / "final.mp4")

    processor = HighlightProcessor(
        context_expander=MagicMock(),
        clip_generator=mock_clip,
        db=db,
        stream_id="test",
    )
    processor.pending_queue.enqueue(
        ResolvedEvent(
            start_pts=0.0,
            end_pts=50.0,
            peak_pts=30.0,
            peak_score=0.9,
            keywords=["ôi", "trời"],
            transcript_excerpt="ôi trời ơi",
            draft_highlight_id=draft_a,
        ),
        current_pts=50.0,
    )
    processor.pending_queue.enqueue(
        ResolvedEvent(
            start_pts=40.0,
            end_pts=80.0,
            peak_pts=60.0,
            peak_score=0.7,
            keywords=["ôi", "trời"],
            transcript_excerpt="ôi trời không",
            draft_highlight_id=draft_b,
        ),
        current_pts=80.0,
    )

    results = processor.process_pending_queue(
        SignalHistoryBuffer(capacity_sec=120), transcript, "live.mp4"
    )

    assert len(results) == 1
    assert results[0]["highlight_type"] == "FINAL"
    assert results[0]["id"] == draft_a
    assert results[0]["start_pts"] == pytest.approx(0.0)
    assert results[0]["end_pts"] == pytest.approx(80.0)

    merged_row = db.get_highlight(draft_b)
    assert merged_row["status"] == "MERGED"
    assert db.get_highlights() == [results[0]]


def test_pre_filter_rejects_low_score_event():
    """Events with peak_score below MIN_PEAK_SCORE must be rejected before LLM."""
    from src.engine.highlight_processor import HighlightProcessor, MIN_PEAK_SCORE
    from src.engine.context_expander import ContextExpander
    from src.core.models import ResolvedEvent

    db_mock = MagicMock()
    processor = HighlightProcessor(
        context_expander=ContextExpander(),
        db=db_mock,
        stream_id="test",
    )

    low_score_event = ResolvedEvent(
        start_pts=0.0,
        end_pts=30.0,
        peak_pts=15.0,
        peak_score=MIN_PEAK_SCORE - 0.05,  # just below threshold
        keywords=[],
        transcript_excerpt="",
        draft_highlight_id=42,
    )

    result = processor._pre_filter(low_score_event)

    assert result is None, "Low-score event should be rejected by pre-filter"
    db_mock.update_status.assert_called_once_with(42, "REJECTED_PREFILTER")


def test_pre_filter_trims_long_event():
    """Events longer than MAX_PRE_LLM_DURATION must be trimmed around peak_pts."""
    from src.engine.highlight_processor import HighlightProcessor, MAX_PRE_LLM_DURATION
    from src.engine.context_expander import ContextExpander
    from src.core.models import ResolvedEvent

    processor = HighlightProcessor(context_expander=ContextExpander())

    long_event = ResolvedEvent(
        start_pts=0.0,
        end_pts=200.0,       # 200s duration — way over limit
        peak_pts=100.0,
        peak_score=0.8,
        keywords=[],
        transcript_excerpt="",
    )

    result = processor._pre_filter(long_event)

    assert result is not None
    duration = result.end_pts - result.start_pts
    assert duration <= MAX_PRE_LLM_DURATION, (
        f"Expected trimmed duration <= {MAX_PRE_LLM_DURATION}s, got {duration:.1f}s"
    )
    # Peak must remain inside the trimmed boundary
    assert result.start_pts <= long_event.peak_pts <= result.end_pts


def test_pre_filter_passes_valid_event():
    """Normal event must pass through unchanged."""
    from src.engine.highlight_processor import HighlightProcessor
    from src.engine.context_expander import ContextExpander
    from src.core.models import ResolvedEvent

    processor = HighlightProcessor(context_expander=ContextExpander())

    good_event = ResolvedEvent(
        start_pts=10.0,
        end_pts=50.0,
        peak_pts=30.0,
        peak_score=0.75,
        keywords=[],
        transcript_excerpt="",
    )

    result = processor._pre_filter(good_event)

    assert result is not None
    assert result.start_pts == 10.0
    assert result.end_pts == 50.0

