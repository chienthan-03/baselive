import numpy as np
from unittest.mock import MagicMock
from src.pipeline.stt_worker import STTWorker


def test_stt_transcription():
    worker = STTWorker(model_size="tiny")
    worker.model = MagicMock()

    mock_segment = MagicMock()
    mock_segment.start = 0.0
    mock_segment.end = 1.0
    mock_segment.text = "Hello highlight"
    mock_segment.avg_logprob = -0.3
    worker.model.transcribe.return_value = ([mock_segment], None)

    audio = np.zeros(16000)
    result = worker.transcribe_chunk(audio)

    assert result.text == "Hello highlight"
    worker.model.transcribe.assert_called_once()


def test_stt_returns_transcript_result():
    worker = STTWorker(model_size="tiny")
    worker.model = MagicMock()
    mock_seg = MagicMock()
    mock_seg.start = 0.0
    mock_seg.end = 1.0
    mock_seg.text = "Hello highlight"
    mock_seg.avg_logprob = -0.3
    worker.model.transcribe.return_value = ([mock_seg], None)

    result = worker.transcribe_chunk(np.zeros(16000), chunk_start_pts=5.0)
    assert result.text == "Hello highlight"
    assert result.chunk_start_pts == 5.0
    assert len(result.segments) == 1
