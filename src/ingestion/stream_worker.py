"""
StreamWorker: Per-stream orchestrator. Ties together StreamRecorder,
ChatCollector, and MasterPipeline. Runs a continuous loop to fetch
data chunks and push them to the pipeline.
"""
import time
import logging
from typing import Optional
import numpy as np

from src.ingestion.stream_recorder import StreamRecorder
from src.ingestion.chat_collector import ChatCollector
from src.engine.pipeline import MasterPipeline
from src.engine.context_expander import ContextExpander
from src.engine.highlight_processor import HighlightProcessor
from src.buffer.circular_buffer import AudioRingBuffer, ChatBuffer, TranscriptBuffer
from src.pipeline.stt_worker import STTWorker
from src.core.models import EventCandidate

logger = logging.getLogger(__name__)

LOOKFORWARD_TIMEOUT_SEC = 120.0


class StreamWorker:
    def __init__(
        self,
        url: str,
        username: str,
        pipeline: MasterPipeline,
        clip_source: str = "",
        output_dir: str = "output/clips",
        max_reconnect_attempts: int = 5,
        chunk_duration_s: float = 5.0,
        max_iterations: Optional[int] = None,  # For testing
    ):
        self.url = url
        self.username = username
        self.pipeline = pipeline
        self.max_reconnect_attempts = max_reconnect_attempts
        self.chunk_duration_s = chunk_duration_s
        self.max_iterations = max_iterations

        self.audio_buffer = AudioRingBuffer(capacity_sec=600, sample_rate=16000)
        self.chat_buffer = ChatBuffer(capacity_sec=900)
        self.transcript_buffer = TranscriptBuffer(capacity_sec=900)

        self.stt_worker = STTWorker(model_size="small")
        try:
            self.stt_worker.load_model()
        except Exception as exc:
            logger.warning("STT model failed to load: %s", exc)

        self.recorder = StreamRecorder(
            url=self.url,
            audio_buffer=self.audio_buffer,
            chunk_duration_s=self.chunk_duration_s,
        )
        self.collector = ChatCollector(
            username=self.username,
            chat_buffer=self.chat_buffer,
        )

        self._running = False
        self._pts = 0.0

        self.context_expander = ContextExpander()
        self.highlight_processor = HighlightProcessor(
            context_expander=self.context_expander,
            clip_generator=pipeline.clip_generator,
            db=pipeline.db,
            state_machine=pipeline.state_machine,
            stream_id=getattr(pipeline, "stream_id", "default"),
        )
        pipeline.highlight_processor = self.highlight_processor
        pipeline.transcript_buffer = self.transcript_buffer

    def _process_chunk(
        self,
        audio_chunk: np.ndarray,
        chat_items: list,
        transcript_items: list,
        clip_source: str,
    ):
        return self.pipeline.process_chunk(
            pts=self._pts,
            audio_data=audio_chunk,
            chat_messages=chat_items,
            transcript=transcript_items or None,
            clip_source=clip_source,
        )

    def _blocking_look_forward(
        self,
        closed_info,
        clip_source: str,
        chat_items: list,
        transcript_items: list,
        audio_chunk: np.ndarray,
        iterations: int,
    ) -> tuple[float, int]:
        event = closed_info.event
        close_pts = closed_info.close_pts
        peak_pts = event.peak_pts
        resolution_pts = close_pts
        deadline_pts = close_pts + LOOKFORWARD_TIMEOUT_SEC

        while self._running:
            resolution_pts = self.context_expander.look_forward(
                peak_pts=peak_pts,
                close_pts=close_pts,
                history=self.pipeline.signal_history,
                transcript=self.transcript_buffer,
            )

            if self._pts >= resolution_pts:
                break
            if self._pts >= deadline_pts:
                resolution_pts = deadline_pts
                break

            time.sleep(self.chunk_duration_s)
            self._pts += self.chunk_duration_s
            iterations += 1

            if self.max_iterations is not None and iterations >= self.max_iterations:
                break

            audio_chunk = self.audio_buffer.read(
                start_pts=self._pts, duration_sec=self.chunk_duration_s
            )
            if len(audio_chunk) < self.chunk_duration_s * 16000:
                pad_len = int(self.chunk_duration_s * 16000) - len(audio_chunk)
                audio_chunk = np.concatenate(
                    [audio_chunk, np.zeros(pad_len, dtype=np.float32)]
                )

            chat_items = [
                i["item"]
                for i in self.chat_buffer.items
                if i["pts"] >= self._pts
            ]

            if self.stt_worker.enabled:
                transcript_result = self.stt_worker.transcribe_chunk(
                    audio_chunk, chunk_start_pts=self._pts
                )
                self.transcript_buffer.add_item(transcript_result, pts=self._pts)

            transcript_items = [
                i for i in self.transcript_buffer.items if i["pts"] >= self._pts
            ]

            self._process_chunk(
                audio_chunk, chat_items, transcript_items, clip_source
            )

        return resolution_pts, iterations

    def run(self) -> None:
        """Main loop: starts ingestion and feeds chunks to pipeline."""
        self._running = True
        self.recorder.start()
        self.collector.start()
        logger.info("StreamWorker started for %s (@%s)", self.url, self.username)

        reconnect_attempts = 0
        backoff_delays = [1, 2, 4, 8, 16, 30]
        iterations = 0

        try:
            while self._running:
                if self.max_iterations is not None and iterations >= self.max_iterations:
                    break

                # Check health
                if not self.recorder.is_running:
                    if reconnect_attempts >= self.max_reconnect_attempts:
                        logger.error("Max reconnect attempts reached. Stopping worker.")
                        break
                    
                    delay = backoff_delays[min(reconnect_attempts, len(backoff_delays) - 1)]
                    logger.warning("Recorder stopped. Reconnecting in %ds...", delay)
                    time.sleep(delay)
                    self.recorder.start()
                    reconnect_attempts += 1
                    continue
                else:
                    reconnect_attempts = 0 # Reset on healthy loop

                # Wait for next chunk interval
                time.sleep(self.chunk_duration_s)

                # Fetch audio chunk
                audio_chunk = self.audio_buffer.read(
                    start_pts=self._pts, duration_sec=self.chunk_duration_s
                )
                
                # If audio is empty or not enough, pipeline will handle or skip
                if len(audio_chunk) < self.chunk_duration_s * 16000:
                   logger.debug("Short audio chunk, padded with zeros")
                   pad_len = int(self.chunk_duration_s * 16000) - len(audio_chunk)
                   audio_chunk = np.concatenate([audio_chunk, np.zeros(pad_len, dtype=np.float32)])

                # Fetch chat
                # Extract actual items from dict {"item": dict, "pts": pts}
                chat_items = [i["item"] for i in self.chat_buffer.items if i["pts"] >= self._pts]

                if self.stt_worker.enabled:
                    transcript_result = self.stt_worker.transcribe_chunk(
                        audio_chunk, chunk_start_pts=self._pts
                    )
                    self.transcript_buffer.add_item(transcript_result, pts=self._pts)

                transcript_items = [
                    i for i in self.transcript_buffer.items if i["pts"] >= self._pts
                ]

                clip_source = self.recorder.video_path or ""

                closed_info = self._process_chunk(
                    audio_chunk, chat_items, transcript_items, clip_source
                )

                if closed_info is not None:
                    resolution_pts, iterations = self._blocking_look_forward(
                        closed_info,
                        clip_source,
                        chat_items,
                        transcript_items,
                        audio_chunk,
                        iterations,
                    )
                    self.highlight_processor.on_event_closed(
                        event=closed_info.event,
                        history=self.pipeline.signal_history,
                        transcript=self.transcript_buffer,
                        clip_source=clip_source,
                        resolution_pts=resolution_pts,
                        current_pts=self._pts,
                    )
                    self.pipeline.state_machine.current_event = EventCandidate()

                self._pts += self.chunk_duration_s
                iterations += 1

        finally:
            self.stop()

    def stop(self) -> None:
        """Stops the worker and all ingestion subprocesses."""
        self._running = False
        self.recorder.stop()
        self.collector.stop()
        logger.info("StreamWorker stopped")
