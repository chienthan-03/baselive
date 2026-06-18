import numpy as np

from src.core.models import TranscriptResult, TranscriptSegment


class STTWorker:
    def __init__(self, model_size: str = "small", device: str = "cpu"):
        self.model_size = model_size
        self.device = device
        self.model = None

    @property
    def enabled(self) -> bool:
        return self.model is not None

    def load_model(self):
        try:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(self.model_size, device=self.device, compute_type="int8")
        except ImportError:
            raise ImportError("faster-whisper is not installed")

    def transcribe_chunk(self, audio_data: np.ndarray, chunk_start_pts: float = 0.0) -> TranscriptResult:
        if not self.model:
            return TranscriptResult(
                text="",
                segments=[],
                language="vi",
                chunk_start_pts=chunk_start_pts,
            )

        segments_iter, info = self.model.transcribe(audio_data, language="vi", beam_size=1)
        segments: list[TranscriptSegment] = []
        text_parts: list[str] = []
        for segment in segments_iter:
            confidence = min(1.0, max(0.0, 1.0 + segment.avg_logprob))
            segments.append(
                TranscriptSegment(
                    start=segment.start,
                    end=segment.end,
                    text=segment.text,
                    confidence=confidence,
                )
            )
            text_parts.append(segment.text)

        language = getattr(info, "language", "vi") if info else "vi"

        return TranscriptResult(
            text=" ".join(text_parts).strip(),
            segments=segments,
            language=language,
            chunk_start_pts=chunk_start_pts,
        )
