import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from src.ingestion.stream_worker import StreamWorker
from src.engine.pipeline import MasterPipeline
from src.core.models import TranscriptResult


def test_full_pipeline_detects_spike_event():
    """
    End-to-end smoke test:
    Inject loud audio, gift chat, and shock-keyword transcript into the ingestion
    layer and verify the MasterPipeline detects a highlight candidate.
    """
    pipeline = MasterPipeline()

    with patch("src.ingestion.stream_worker.STTWorker") as MockSTT, \
         patch("src.ingestion.stream_worker.StreamRecorder") as MockRecorder, \
         patch("src.ingestion.stream_worker.ChatCollector") as MockCollector, \
         patch("src.ingestion.stream_worker.time.sleep"):

        mock_stt = MockSTT.return_value
        mock_stt.enabled = False

        mock_recorder = MagicMock()
        mock_recorder.is_running = True
        mock_recorder.video_path = "/tmp/live.mp4"
        MockRecorder.return_value = mock_recorder

        mock_collector = MagicMock()
        mock_collector.is_running = True
        MockCollector.return_value = mock_collector

        worker = StreamWorker(
            url="fake_url",
            username="fake_user",
            pipeline=pipeline,
            max_iterations=1,
            chunk_duration_s=5.0,
        )

        fake_audio = np.random.normal(0, 0.9, 16000 * 5).astype(np.float32)
        worker.audio_buffer.write(fake_audio, start_pts=0.0)

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

        worker.run()

    current_state = pipeline.state_machine.current_event.state
    assert current_state in ["OPENING", "ACTIVE"]
