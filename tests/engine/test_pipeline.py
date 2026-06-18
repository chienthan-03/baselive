import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from src.core.models import TranscriptResult
from src.engine.pipeline import MasterPipeline


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


def test_pipeline_emits_clip_on_event_closed():
    with patch("src.engine.clip_generator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)

        pipeline = MasterPipeline(
            clip_source="dummy.mp4",
            output_dir="output/clips",
        )

        pipeline.state_machine.current_event.state = "ACTIVE"
        pipeline.state_machine.current_event.start_pts = 5.0
        pipeline.state_machine.current_event.below_close_since = 5.0

        audio_chunk = np.zeros(16000 * 5)
        chat_msgs = []
        pipeline.process_chunk(pts=11.0, audio_data=audio_chunk, chat_messages=chat_msgs)

        assert pipeline.state_machine.current_event.state == "CLOSED"
        mock_run.assert_called_once()
