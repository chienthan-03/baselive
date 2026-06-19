import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from src.ingestion.stream_worker import StreamWorker
from src.engine.pipeline import MasterPipeline
from src.engine.pending_event_queue import PendingEventQueue
from src.core.models import TranscriptResult
from src.db.database import Database


def _make_worker_patches():
  return (
      patch("src.ingestion.stream_worker.STTWorker"),
      patch("src.ingestion.platforms.tiktok.StreamRecorder"),
      patch("src.ingestion.platforms.tiktok.ChatCollector"),
      patch("src.ingestion.stream_worker.time.sleep"),
      patch("src.engine.clip_generator.ClipGenerator.generate_final", return_value="/tmp/final.mp4"),
      patch("src.engine.clip_generator.ClipGenerator.generate_draft", return_value="/tmp/draft.mp4"),
  )


def _setup_mocks(MockSTT, MockRecorder, MockCollector):
    mock_stt = MockSTT.return_value
    mock_stt.enabled = False

    mock_recorder = MagicMock()
    mock_recorder.is_running = True
    mock_recorder.video_path = "/tmp/live.mp4"
    MockRecorder.return_value = mock_recorder

    mock_collector = MagicMock()
    mock_collector.is_running = True
    MockCollector.return_value = mock_collector

    return mock_stt, mock_recorder, mock_collector


def _inject_hype_signals(worker, num_loud_chunks: int = 2, num_quiet_chunks: int = 4):
    loud = np.random.normal(0, 0.9, 16000 * 5).astype(np.float32)
    quiet = np.zeros(16000 * 5, dtype=np.float32)
    chunks = [loud] * num_loud_chunks + [quiet] * num_quiet_chunks
    audio = np.concatenate(chunks)
    worker.audio_buffer.write(audio, start_pts=0.0)

    worker.chat_buffer.add_item(
        {
            "content": "wow!",
            "event_type": "GIFT",
            "gift_value": 500,
            "username": "gifter1",
        },
        pts=0.0,
    )
    for i in range(15):
        worker.chat_buffer.add_item(
            {"content": "haha", "event_type": "COMMENT"},
            pts=float(i),
        )

    worker.transcript_buffer.add_item(
        TranscriptResult(
            text="ôi trời không thể tin được",
            segments=[],
            language="vi",
            chunk_start_pts=0,
        ),
        pts=0.0,
    )


def test_full_pipeline_detects_spike_event():
    """
    End-to-end smoke test:
    Inject loud audio, gift chat, and shock-keyword transcript into the ingestion
    layer and verify the MasterPipeline detects a highlight candidate.
    """
    pipeline = MasterPipeline()

    with _make_worker_patches()[0] as MockSTT, \
         _make_worker_patches()[1] as MockRecorder, \
         _make_worker_patches()[2] as MockCollector, \
         _make_worker_patches()[3], \
         _make_worker_patches()[5]:
        _setup_mocks(MockSTT, MockRecorder, MockCollector)

        worker = StreamWorker(
            url="fake_url",
            username="fake_user",
            pipeline=pipeline,
            max_iterations=1,
            chunk_duration_s=5.0,
        )

        _inject_hype_signals(worker, num_loud_chunks=1, num_quiet_chunks=0)

        worker.run()

    current_state = pipeline.state_machine.current_event.state
    assert current_state in ["OPENING", "ACTIVE"]


def test_full_pipeline_draft_to_final_lifecycle(tmp_path):
    """
    Phase 2a integration smoke test:
    Inject loud audio + hype chat + shock-keyword transcript → DRAFT on ACTIVE.
    Continue with quiet audio → CLOSED → HighlightProcessor upgrades DRAFT to FINAL.
    """
    db = Database(db_path=":memory:")
    db.init_db()

    pipeline = MasterPipeline(
        clip_source="/tmp/live.mp4",
        output_dir=str(tmp_path / "clips"),
        db=db,
        stream_id="smoke_test",
    )

    draft_insert_calls = []
    original_insert = db.insert_highlight

    def track_insert(*args, **kwargs):
        draft_insert_calls.append(kwargs.copy())
        return original_insert(*args, **kwargs)

    db.insert_highlight = track_insert

    closed_events = []
    original_process = pipeline.process_chunk

    def track_process(*args, **kwargs):
        result = original_process(*args, **kwargs)
        if result is not None:
            closed_events.append(result)
        return result

    pipeline.process_chunk = track_process

    patches = _make_worker_patches()
    with patches[0] as MockSTT, \
         patches[1] as MockRecorder, \
         patches[2] as MockCollector, \
         patches[3], \
         patches[4], \
         patches[5]:

        _setup_mocks(MockSTT, MockRecorder, MockCollector)

        worker = StreamWorker(
            url="fake_url",
            username="fake_user",
            pipeline=pipeline,
            max_iterations=6,
            chunk_duration_s=5.0,
        )

        pipeline.highlight_processor.llm_gate = MagicMock()
        pipeline.highlight_processor.llm_gate.is_rate_limited.return_value = False
        pipeline.highlight_processor.llm_gate.should_refine_boundary.return_value = False

        worker.highlight_processor.pending_queue = PendingEventQueue(max_wait_sec=0)
        worker.context_expander.look_forward = MagicMock(
            side_effect=lambda **kwargs: kwargs["close_pts"]
        )

        _inject_hype_signals(worker)

        worker.run()

    assert any(
        call.get("highlight_type") == "DRAFT" and call.get("is_growing") == 1
        for call in draft_insert_calls
    ), "Expected DRAFT highlight inserted on ACTIVE transition"

    assert pipeline.state_machine.current_event.state == "IDLE"
    assert len(closed_events) >= 1
    assert closed_events[0].event.peak_score > 0

    highlights = db.get_highlights()
    assert len(highlights) == 1
    assert highlights[0]["highlight_type"] == "FINAL"
    assert highlights[0]["is_growing"] == 0
    assert highlights[0]["clip_path"] == "/tmp/final.mp4"
