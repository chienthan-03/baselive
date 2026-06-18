import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from src.ingestion.stream_worker import StreamWorker
from src.engine.pipeline import MasterPipeline


def test_full_pipeline_detects_spike_event():
    """
    End-to-end smoke test:
    Inject a loud audio spike and heavy chat activity into the ingestion layer
    and verify the MasterPipeline detects a highlight candidate.
    """
    pipeline = MasterPipeline()

    with patch("src.ingestion.stream_worker.StreamRecorder") as MockRecorder, \
         patch("src.ingestion.stream_worker.ChatCollector") as MockCollector, \
         patch("src.ingestion.stream_worker.time.sleep"):

        worker = StreamWorker(
            url="fake_url",
            username="fake_user",
            pipeline=pipeline,
            max_iterations=1,
            chunk_duration_s=5.0
        )

        # Inject fake audio directly into worker's buffer
        fake_audio = np.random.normal(0, 0.9, 16000 * 5).astype(np.float32)
        worker.audio_buffer.write(fake_audio, start_pts=0.0)

        # Inject fake chat messages directly into worker's buffer
        for i in range(15):
            worker.chat_buffer.add_item({"msg": "haha", "pts": float(i)}, pts=float(i))

        worker.run()

    # The pipeline should have processed the loud audio and heavy chat.
    # The StateMachine should have transitioned to OPENING or ACTIVE.
    current_state = pipeline.state_machine.current_event.state
    assert current_state in ["OPENING", "ACTIVE"]
