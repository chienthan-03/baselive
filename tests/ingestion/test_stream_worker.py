import pytest
import numpy as np
import time
from unittest.mock import patch, MagicMock, call

from src.ingestion.stream_worker import StreamWorker
from src.engine.pipeline import MasterPipeline
from src.core.models import TranscriptResult, ClosedEventInfo, EventCandidate


def _make_mock_pipeline() -> MagicMock:
    pipeline = MagicMock(spec=MasterPipeline)
    pipeline.process_chunk.return_value = None
    pipeline.signal_history = MagicMock()
    pipeline.state_machine = MagicMock()
    pipeline.clip_generator = MagicMock()
    pipeline.db = MagicMock()
    pipeline.audio_analyzer = MagicMock()
    pipeline.audio_analyzer._compute_rms.return_value = 0.5
    return pipeline


def _patch_stt(enabled: bool = False):
    mock_stt = MagicMock()
    mock_stt.enabled = enabled
    return patch("src.ingestion.stream_worker.STTWorker", return_value=mock_stt)


def test_stream_worker_calls_pipeline_process_chunk():
    """StreamWorker should call pipeline.process_chunk() during its run loop."""
    pipeline = _make_mock_pipeline()

    with _patch_stt(), \
         patch("src.ingestion.platforms.tiktok.StreamRecorder") as MockRecorder, \
         patch("src.ingestion.platforms.tiktok.ChatCollector") as MockCollector:


        mock_recorder = MagicMock()
        mock_recorder.is_running = True
        mock_recorder.audio_buffer = MagicMock()
        mock_recorder.audio_buffer.read.return_value = np.zeros(16000 * 5, dtype=np.float32)
        MockRecorder.return_value = mock_recorder

        mock_collector = MagicMock()
        mock_collector.is_running = True
        mock_collector.chat_buffer = MagicMock()
        mock_collector.chat_buffer.items = []
        MockCollector.return_value = mock_collector

        worker = StreamWorker(
            url="https://tiktok.com/@test/live",
            username="testuser",
            pipeline=pipeline,
            max_iterations=1,  # run exactly 1 iteration
        )
        worker.run()

    pipeline.process_chunk.assert_called_once()


def test_stream_worker_reconnects_on_recorder_failure():
    """StreamWorker should attempt reconnect when recorder stops unexpectedly."""
    pipeline = _make_mock_pipeline()

    with _patch_stt(), \
         patch("src.ingestion.platforms.tiktok.StreamRecorder") as MockRecorder, \
         patch("src.ingestion.platforms.tiktok.ChatCollector") as MockCollector, \
         patch("src.ingestion.stream_worker.time.sleep"):  # no real sleeping

        mock_recorder = MagicMock()
        # Recorder fails immediately every time (is_running always False)
        mock_recorder.is_running = False
        MockRecorder.return_value = mock_recorder

        mock_collector = MagicMock()
        mock_collector.is_running = True
        mock_collector.chat_buffer.items = []
        MockCollector.return_value = mock_collector

        worker = StreamWorker(
            url="https://tiktok.com/@test/live",
            username="testuser",
            pipeline=pipeline,
            max_reconnect_attempts=2,
            max_iterations=2,
        )
        worker.run()

    # Should have tried to start recorder more than once (initial + reconnects)
    assert mock_recorder.start.call_count >= 1


@patch("src.ingestion.stream_worker.STTWorker")
def test_stream_worker_passes_transcript_to_pipeline(MockSTT):
    """StreamWorker should transcribe audio and pass transcript + video path to pipeline."""
    pipeline = _make_mock_pipeline()
    mock_stt = MockSTT.return_value
    mock_stt.enabled = True
    mock_stt.transcribe_chunk.return_value = TranscriptResult(
        text="test",
        segments=[],
        language="vi",
        chunk_start_pts=0,
    )

    with patch("src.ingestion.platforms.tiktok.StreamRecorder") as MockRecorder, \
         patch("src.ingestion.platforms.tiktok.ChatCollector") as MockCollector, \
         patch("src.ingestion.stream_worker.time.sleep"):

        mock_recorder = MagicMock()
        mock_recorder.is_running = True
        mock_recorder.video_path = "/tmp/live.mp4"
        mock_recorder.audio_buffer = MagicMock()
        MockRecorder.return_value = mock_recorder

        mock_collector = MagicMock()
        mock_collector.is_running = True
        mock_collector.chat_buffer = MagicMock()
        mock_collector.chat_buffer.items = []
        MockCollector.return_value = mock_collector

        worker = StreamWorker(
            url="https://tiktok.com/@test/live",
            username="testuser",
            pipeline=pipeline,
            max_iterations=1,
        )
        worker.audio_buffer.write(
            np.zeros(16000 * 5, dtype=np.float32), start_pts=0.0
        )
        worker.run()

    mock_stt.transcribe_chunk.assert_called_once()
    pipeline.process_chunk.assert_called_once()
    call_kwargs = pipeline.process_chunk.call_args.kwargs
    assert call_kwargs["transcript"] is not None
    assert len(call_kwargs["transcript"]) == 1
    assert call_kwargs["transcript"][0]["item"].text == "test"
    assert call_kwargs["clip_source"] == "/tmp/live.mp4"


@patch("src.ingestion.stream_worker.HighlightProcessor")
def test_stream_worker_look_forward_on_closed(MockHighlightProcessor):
    """StreamWorker should run look_forward blocking when pipeline returns ClosedEventInfo."""
    pipeline = _make_mock_pipeline()
    closed_event = EventCandidate(
        state="CLOSED",
        peak_pts=60.0,
        start_pts=50.0,
        end_pts=80.0,
        peak_score=0.8,
        draft_highlight_id=1,
    )
    pipeline.process_chunk.side_effect = [
        ClosedEventInfo(event=closed_event, close_pts=80.0),
        None,
    ]
    pipeline.signal_history = MagicMock()
    pipeline.signal_history.get_at.return_value = MagicMock()
    pipeline.state_machine = MagicMock()
    pipeline.state_machine.current_event = closed_event
    pipeline.clip_generator = MagicMock()
    pipeline.db = MagicMock()

    mock_processor = MockHighlightProcessor.return_value

    with _patch_stt(), \
         patch("src.ingestion.platforms.tiktok.StreamRecorder") as MockRecorder, \
         patch("src.ingestion.platforms.tiktok.ChatCollector") as MockCollector, \
         patch("src.ingestion.stream_worker.ContextExpander") as MockExpander, \
         patch("src.ingestion.stream_worker.time.sleep"):

        mock_expander = MockExpander.return_value
        mock_expander.look_forward.return_value = 85.0

        mock_recorder = MagicMock()
        mock_recorder.is_running = True
        mock_recorder.video_path = "/tmp/live.mp4"
        mock_recorder.audio_buffer = MagicMock()
        mock_recorder.audio_buffer.read.return_value = np.zeros(16000 * 5, dtype=np.float32)
        MockRecorder.return_value = mock_recorder

        mock_collector = MagicMock()
        mock_collector.is_running = True
        mock_collector.chat_buffer = MagicMock()
        mock_collector.chat_buffer.items = []
        MockCollector.return_value = mock_collector

        worker = StreamWorker(
            url="https://tiktok.com/@test/live",
            username="testuser",
            pipeline=pipeline,
            max_iterations=2,
        )
        worker.run()

    assert pipeline.process_chunk.call_count == 2
    mock_processor.on_event_closed.assert_called_once()
    call_kwargs = mock_processor.on_event_closed.call_args.kwargs
    assert call_kwargs["event"] is closed_event
    assert call_kwargs["resolution_pts"] == 85.0
    assert call_kwargs["clip_source"] == "/tmp/live.mp4"


@patch("src.ingestion.stream_worker.VideoAnalyzer")
def test_stream_worker_passes_video_signals_to_pipeline(MockVA):
    """StreamWorker should sample video and pass video_signals to pipeline."""
    pipeline = _make_mock_pipeline()

    mock_va = MockVA.return_value
    mock_va.enabled = True
    mock_va.sample_frame.return_value = np.zeros((64, 64, 3), dtype=np.uint8)
    mock_va.analyze.return_value = {
        "video_scene_change": 0.8,
        "video_motion": 0.5,
    }

    with _patch_stt(), \
         patch("src.ingestion.platforms.tiktok.StreamRecorder") as MockRecorder, \
         patch("src.ingestion.platforms.tiktok.ChatCollector") as MockCollector, \
         patch("src.ingestion.stream_worker.time.sleep"):

        mock_recorder = MagicMock()
        mock_recorder.is_running = True
        mock_recorder.video_path = "/tmp/live.mp4"
        mock_recorder.audio_buffer = MagicMock()
        mock_recorder.audio_buffer.read.return_value = np.zeros(16000 * 5, dtype=np.float32)
        MockRecorder.return_value = mock_recorder

        mock_collector = MagicMock()
        mock_collector.is_running = True
        mock_collector.chat_buffer = MagicMock()
        mock_collector.chat_buffer.items = []
        MockCollector.return_value = mock_collector

        worker = StreamWorker(
            url="https://tiktok.com/@test/live",
            username="testuser",
            pipeline=pipeline,
            max_iterations=1,
        )
        worker.run()

    mock_va.sample_frame.assert_called_once_with("/tmp/live.mp4", 0.0)
    mock_va.analyze.assert_called_once()
    call_kwargs = pipeline.process_chunk.call_args.kwargs
    assert call_kwargs["video_signals"] == {
        "video_scene_change": 0.8,
        "video_motion": 0.5,
    }
