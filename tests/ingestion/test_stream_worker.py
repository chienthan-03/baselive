import pytest
import numpy as np
import time
from unittest.mock import patch, MagicMock, call

from src.ingestion.stream_worker import StreamWorker
from src.engine.pipeline import MasterPipeline
from src.core.models import TranscriptResult


def _make_mock_pipeline() -> MagicMock:
    pipeline = MagicMock(spec=MasterPipeline)
    return pipeline


def _patch_stt(enabled: bool = False):
    mock_stt = MagicMock()
    mock_stt.enabled = enabled
    return patch("src.ingestion.stream_worker.STTWorker", return_value=mock_stt)


def test_stream_worker_calls_pipeline_process_chunk():
    """StreamWorker should call pipeline.process_chunk() during its run loop."""
    pipeline = _make_mock_pipeline()

    with _patch_stt(), \
         patch("src.ingestion.stream_worker.StreamRecorder") as MockRecorder, \
         patch("src.ingestion.stream_worker.ChatCollector") as MockCollector:


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
         patch("src.ingestion.stream_worker.StreamRecorder") as MockRecorder, \
         patch("src.ingestion.stream_worker.ChatCollector") as MockCollector, \
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

    with patch("src.ingestion.stream_worker.StreamRecorder") as MockRecorder, \
         patch("src.ingestion.stream_worker.ChatCollector") as MockCollector, \
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
