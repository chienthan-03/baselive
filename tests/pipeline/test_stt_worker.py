import pytest
import numpy as np
from unittest.mock import MagicMock
from src.pipeline.stt_worker import STTWorker

def test_stt_transcription():
    worker = STTWorker(model_size="tiny")
    worker.model = MagicMock()
    
    mock_segment = MagicMock()
    mock_segment.text = "Hello highlight"
    worker.model.transcribe.return_value = ([mock_segment], None)
    
    audio = np.zeros(16000)
    text = worker.transcribe_chunk(audio)
    
    assert text == "Hello highlight"
    worker.model.transcribe.assert_called_once()
