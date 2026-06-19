import numpy as np
import time
import io
import wave
import os
import logging
import base64
import httpx

from src.core.models import TranscriptResult, TranscriptSegment

logger = logging.getLogger(__name__)

class STTWorker:
    def __init__(self, model_size: str = "small", device: str = "cpu", metrics=None):
        self._metrics = metrics
        
        self.api_key = os.environ.get("STT_API_KEY")
        self.base_url = os.environ.get("STT_BASE_URL", "https://api.openai.com/v1")
        self.model_name = os.environ.get("STT_MODEL", "whisper-1")
        
        self.client = None
        if self.api_key:
            try:
                from openai import OpenAI
                self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            except ImportError:
                logger.error("openai package is not installed. STT API will be disabled.")
        else:
            logger.warning("STT_API_KEY not found. STT will be disabled.")

    @property
    def enabled(self) -> bool:
        return self.client is not None

    def load_model(self):
        # Model is hosted on cloud, no local loading needed.
        pass

    def _numpy_to_wav_bytes(self, audio_data: np.ndarray, sample_rate: int = 16000) -> io.BytesIO:
        """Convert float32 numpy array to a WAV file in memory (PCM 16-bit)."""
        # Ensure input is 1D
        if len(audio_data.shape) > 1:
            audio_data = audio_data.flatten()
            
        # Convert float32 [-1.0, 1.0] to int16 [-32768, 32767]
        audio_int16 = (audio_data * 32767.0).clip(-32768, 32767).astype(np.int16)
        
        wav_io = io.BytesIO()
        with wave.open(wav_io, 'wb') as wav_file:
            wav_file.setnchannels(1)  # Mono
            wav_file.setsampwidth(2)  # 2 bytes per sample (16-bit)
            wav_file.setframerate(sample_rate)
            wav_file.writeframes(audio_int16.tobytes())
            
        wav_io.seek(0)
        wav_io.name = "audio.wav"  # Required by openai client to recognize format
        return wav_io

    def transcribe_chunk(self, audio_data: np.ndarray, chunk_start_pts: float = 0.0) -> TranscriptResult:
        if not self.client:
            return TranscriptResult(
                text="",
                segments=[],
                language="vi",
                chunk_start_pts=chunk_start_pts,
            )

        started = time.perf_counter()
        try:
            # 1. Convert numpy array to WAV
            wav_bytes = self._numpy_to_wav_bytes(audio_data)
            
            # 2. Call API
            if "openrouter" in self.base_url.lower():
                wav_io = wav_bytes.read()
                b64_audio = base64.b64encode(wav_io).decode('utf-8')
                
                payload = {
                    "model": self.model_name,
                    "input_audio": {
                        "data": b64_audio,
                        "format": "wav"
                    },
                    "language": "vi",
                    "response_format": "verbose_json"
                }
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                }
                
                with httpx.Client() as http_client:
                    http_response = http_client.post(
                        f"{self.base_url.rstrip('/')}/audio/transcriptions",
                        headers=headers,
                        json=payload,
                        timeout=60.0
                    )
                    http_response.raise_for_status()
                    res_data = http_response.json()
            else:
                response = self.client.audio.transcriptions.create(
                    model=self.model_name,
                    file=wav_bytes,
                    language="vi",
                    response_format="verbose_json",
                )
                
                # Convert response to dict to handle different API implementations
                if hasattr(response, 'model_dump'):
                    res_data = response.model_dump()
                elif isinstance(response, dict):
                    res_data = response
                else:
                    res_data = {"text": getattr(response, "text", ""), "segments": getattr(response, "segments", [])}
            
            # 3. Parse Response
            segments: list[TranscriptSegment] = []
            text_parts: list[str] = []
                
            api_segments = res_data.get("segments", [])
            
            for seg in api_segments:
                if isinstance(seg, dict):
                    start = float(seg.get("start", 0.0))
                    end = float(seg.get("end", 0.0))
                    text = str(seg.get("text", ""))
                    logprob = float(seg.get("avg_logprob", 0.0)) 
                else:
                    start = float(getattr(seg, "start", 0.0))
                    end = float(getattr(seg, "end", 0.0))
                    text = str(getattr(seg, "text", ""))
                    logprob = float(getattr(seg, "avg_logprob", 0.0))
                    
                confidence = min(1.0, max(0.0, 1.0 + logprob))
                
                segments.append(
                    TranscriptSegment(
                        start=start,
                        end=end,
                        text=text,
                        confidence=confidence,
                    )
                )
                text_parts.append(text)

            full_text = res_data.get("text", "")
            if not segments and full_text:
                duration = len(audio_data) / 16000.0
                segments.append(
                    TranscriptSegment(
                        start=0.0,
                        end=duration,
                        text=full_text,
                        confidence=1.0,
                    )
                )
                
            return TranscriptResult(
                text=full_text.strip() if full_text else " ".join(text_parts).strip(),
                segments=segments,
                language=res_data.get("language", "vi"),
                chunk_start_pts=chunk_start_pts,
            )
            
        except Exception as e:
            logger.error(f"STT API Transcription failed: {e}")
            return TranscriptResult(
                text="",
                segments=[],
                language="vi",
                chunk_start_pts=chunk_start_pts,
            )
        finally:
            if self._metrics is not None:
                try:
                    self._metrics.observe_stt(time.perf_counter() - started)
                except Exception:
                    pass
