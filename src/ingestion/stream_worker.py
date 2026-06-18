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
from src.buffer.circular_buffer import AudioRingBuffer, ChatBuffer

logger = logging.getLogger(__name__)


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

                # Process chunk
                self.pipeline.process_chunk(
                    pts=self._pts, audio_data=audio_chunk, chat_messages=chat_items
                )

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
