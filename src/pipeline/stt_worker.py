import numpy as np

class STTWorker:
    def __init__(self, model_size: str = "small", device: str = "cpu"):
        self.model_size = model_size
        self.device = device
        self.model = None

    def load_model(self):
        try:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(self.model_size, device=self.device, compute_type="int8")
        except ImportError:
            raise ImportError("faster-whisper is not installed")

    def transcribe_chunk(self, audio_data: np.ndarray) -> str:
        if not self.model:
            return ""
        
        segments, _ = self.model.transcribe(audio_data, language="vi", beam_size=1)
        text_parts = [segment.text for segment in segments]
        return " ".join(text_parts).strip()
