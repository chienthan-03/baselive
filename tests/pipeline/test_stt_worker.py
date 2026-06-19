import numpy as np
from unittest.mock import MagicMock
from src.pipeline.stt_worker import STTWorker


def test_stt_transcription():
    worker = STTWorker(model_size="tiny")
    worker.client = MagicMock()
    worker.base_url = "https://api.openai.com/v1"

    mock_response = MagicMock()
    # Mocking model_dump or dictionary access if needed, or attributes
    mock_response.text = "Hello highlight"
    mock_seg = MagicMock()
    mock_seg.start = 0.0
    mock_seg.end = 1.0
    mock_seg.text = "Hello highlight"
    mock_seg.avg_logprob = -0.3
    mock_response.segments = [mock_seg]
    # We want it to not have model_dump to fallback to attributes, or we can mock dict behavior
    delattr(mock_response, "model_dump")
    
    worker.client.audio.transcriptions.create.return_value = mock_response

    audio = np.zeros(16000)
    result = worker.transcribe_chunk(audio)

    assert result.text == "Hello highlight"
    worker.client.audio.transcriptions.create.assert_called_once()


def test_stt_returns_transcript_result():
    worker = STTWorker(model_size="tiny")
    worker.client = MagicMock()
    worker.base_url = "https://api.openai.com/v1"

    mock_response = MagicMock()
    mock_response.text = "Hello highlight"
    mock_seg = MagicMock()
    mock_seg.start = 0.0
    mock_seg.end = 1.0
    mock_seg.text = "Hello highlight"
    mock_seg.avg_logprob = -0.3
    mock_response.segments = [mock_seg]
    delattr(mock_response, "model_dump")

    worker.client.audio.transcriptions.create.return_value = mock_response

    result = worker.transcribe_chunk(np.zeros(16000), chunk_start_pts=5.0)
    assert result.text == "Hello highlight"
    assert result.chunk_start_pts == 5.0
    assert len(result.segments) == 1

