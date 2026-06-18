import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from src.core.models import TranscriptResult, ClosedEventInfo
from src.engine.pipeline import MasterPipeline


@pytest.fixture
def loud_audio():
    return np.random.normal(0, 0.9, 16000 * 5).astype(np.float32)


@pytest.fixture
def hype_chat():
    msgs = [{"content": "😂😂😂", "event_type": "COMMENT"}] * 20
    msgs.append({"content": "gift!", "event_type": "GIFT", "gift_value": 500})
    return msgs


@pytest.fixture
def mock_db():
    db = MagicMock()
    db.insert_highlight.return_value = 42
    return db


def _set_score(pipeline, score):
    def fake_compute(snapshot):
        snapshot.composite_score = score
        return score

    return patch.object(pipeline.aggregator, "compute_score", side_effect=fake_compute)


def test_pipeline_integration():
    pipeline = MasterPipeline()
    audio_chunk = np.random.normal(0, 0.8, 16000 * 5)
    chat_msgs = [{"msg": "haha", "pts": 1.0}] * 10

    pipeline.process_chunk(pts=10.0, audio_data=audio_chunk, chat_messages=chat_msgs)

    assert pipeline.state_machine.current_event.state in ["OPENING", "ACTIVE"]


def test_pipeline_populates_full_snapshot():
    pipeline = MasterPipeline()
    audio = np.random.normal(0, 0.8, 16000 * 5)
    chat = [{"content": "😂😂", "event_type": "COMMENT"}] * 10
    transcript = [
        {
            "item": TranscriptResult(
                text="ôi trời",
                segments=[],
                language="vi",
                chunk_start_pts=0,
            ),
            "pts": 0,
        }
    ]
    pipeline.process_chunk(
        pts=10.0,
        audio_data=audio,
        chat_messages=chat,
        transcript=transcript,
    )
    assert pipeline.state_machine.current_event.state in ["OPENING", "ACTIVE"]


def test_pipeline_returns_closed_event_info_on_close():
    pipeline = MasterPipeline()
    pipeline.state_machine.current_event.state = "ACTIVE"
    pipeline.state_machine.current_event.start_pts = 5.0
    pipeline.state_machine.current_event.below_close_since = 5.0
    pipeline.state_machine.current_event.peak_score = 0.9
    pipeline.state_machine.current_event.peak_pts = 8.0

    audio_chunk = np.zeros(16000 * 5)
    with _set_score(pipeline, 0.1):
        result = pipeline.process_chunk(
            pts=11.0, audio_data=audio_chunk, chat_messages=[]
        )

    assert pipeline.state_machine.current_event.state == "CLOSED"
    assert isinstance(result, ClosedEventInfo)
    assert result.close_pts == pytest.approx(5.0)
    assert result.event.peak_score == pytest.approx(0.9)


def test_pipeline_creates_draft_on_first_active(mock_db, loud_audio, hype_chat):
    pipeline = MasterPipeline(db=mock_db, stream_id="test_stream")
    pipeline.state_machine.current_event.state = "OPENING"
    pipeline.state_machine.current_event.start_pts = 5.0

    with _set_score(pipeline, 0.8):
        pipeline.process_chunk(
            pts=10.0, audio_data=loud_audio, chat_messages=hype_chat
        )

    assert pipeline.state_machine.current_event.state == "ACTIVE"
    mock_db.insert_highlight.assert_called_once()
    call_kwargs = mock_db.insert_highlight.call_args.kwargs
    assert call_kwargs["highlight_type"] == "DRAFT"
    assert call_kwargs["is_growing"] == 1
    assert pipeline.state_machine.current_event.draft_highlight_id == 42


def test_pipeline_does_not_duplicate_draft_on_peak_update(
    mock_db, loud_audio, hype_chat
):
    pipeline = MasterPipeline(db=mock_db, stream_id="test_stream")
    pipeline.state_machine.current_event.state = "OPENING"
    pipeline.state_machine.current_event.start_pts = 5.0

    with _set_score(pipeline, 0.8):
        pipeline.process_chunk(
            pts=10.0, audio_data=loud_audio, chat_messages=hype_chat
        )

    with _set_score(pipeline, 0.95):
        pipeline.process_chunk(
            pts=15.0, audio_data=loud_audio, chat_messages=hype_chat
        )

    mock_db.insert_highlight.assert_called_once()
    assert mock_db.update_highlight.call_count >= 1
    last_update = mock_db.update_highlight.call_args
    assert last_update.args[0] == 42
    assert last_update.kwargs["score"] == pytest.approx(0.95)


def test_pipeline_sets_is_growing_false_on_closed(mock_db):
    pipeline = MasterPipeline(db=mock_db, stream_id="test_stream")
    pipeline.state_machine.current_event.state = "ACTIVE"
    pipeline.state_machine.current_event.start_pts = 5.0
    pipeline.state_machine.current_event.below_close_since = 5.0
    pipeline.state_machine.current_event.draft_highlight_id = 42
    pipeline.state_machine.current_event.peak_score = 0.9
    pipeline.state_machine.current_event.peak_pts = 8.0

    audio_chunk = np.zeros(16000 * 5)
    with _set_score(pipeline, 0.1):
        result = pipeline.process_chunk(
            pts=11.0, audio_data=audio_chunk, chat_messages=[]
        )

    assert pipeline.state_machine.current_event.state == "CLOSED"
    assert isinstance(result, ClosedEventInfo)
    mock_db.insert_highlight.assert_not_called()
    mock_db.update_highlight.assert_called_once_with(
        42,
        is_growing=0,
        end_pts=pytest.approx(5.0),
        score=pytest.approx(0.9),
        peak_pts=pytest.approx(8.0),
    )


def test_pipeline_copies_video_signals_to_snapshot():
    pipeline = MasterPipeline()
    audio = np.random.normal(0, 0.8, 16000 * 5).astype(np.float32)
    pipeline.process_chunk(
        pts=10.0,
        audio_data=audio,
        chat_messages=[],
        video_signals={"video_scene_change": 0.8, "video_motion": 0.5},
    )
    entries = pipeline.signal_history.get_range(0.0, 100.0)
    assert entries
    snapshot = entries[-1].snapshot
    assert snapshot.video_scene_change == pytest.approx(0.8)
    assert snapshot.video_motion == pytest.approx(0.5)
