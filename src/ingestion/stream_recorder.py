"""
StreamRecorder: Pulls a livestream via yt-dlp piped through FFmpeg,
reads raw PCM float32 audio from stdout, and feeds it into an AudioRingBuffer.
"""
import subprocess
import threading
import logging
import numpy as np
from typing import Optional

from src.buffer.circular_buffer import AudioRingBuffer

logger = logging.getLogger(__name__)

# FFmpeg command template — reads stdin (from yt-dlp pipe) and outputs
# raw float32 PCM to stdout at 16kHz mono.
_FFMPEG_CMD = [
    "ffmpeg",
    "-loglevel", "error",
    "-i", "pipe:0",         # stdin from yt-dlp
    "-vn",                  # no video
    "-ar", "16000",         # 16kHz sample rate
    "-ac", "1",             # mono
    "-f", "f32le",          # float32 little-endian PCM
    "pipe:1",               # stdout
]

_YTDLP_CMD_TEMPLATE = [
    "yt-dlp",
    "--live-from-start",
    "--no-part",
    "-o", "pipe:1",         # pipe video to stdout
    "-f", "best[ext=mp4]/best",
]


class StreamRecorder:
    """
    Pulls a TikTok Live (or any yt-dlp-compatible) stream and feeds
    decoded audio PCM into an AudioRingBuffer.

    Usage:
        recorder = StreamRecorder(url, audio_buffer)
        recorder.start()       # starts background thread
        ...
        recorder.stop()
    """

    def __init__(
        self,
        url: str,
        audio_buffer: AudioRingBuffer,
        segment_dir: str = "output/segments",
        chunk_duration_s: float = 5.0,
        sample_rate: int = 16000,
    ):
        self.url = url
        self.audio_buffer = audio_buffer
        self.segment_dir = segment_dir
        self.chunk_duration_s = chunk_duration_s
        self.sample_rate = sample_rate

        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pts: float = 0.0  # running PTS based on samples written

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Launch yt-dlp | ffmpeg subprocesses and start reader thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("StreamRecorder already running")
            return

        self._stop_event.clear()
        self._pts = 0.0
        self._launch_ffmpeg()
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()
        logger.info("StreamRecorder started for %s", self.url)

    def stop(self) -> None:
        """Signal the reader loop to stop and terminate subprocesses."""
        self._stop_event.set()
        if self._ffmpeg_proc:
            self._ffmpeg_proc.terminate()
            logger.info("StreamRecorder stopped")

    @property
    def is_running(self) -> bool:
        return (
            self._thread is not None
            and self._thread.is_alive()
            and not self._stop_event.is_set()
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _launch_ffmpeg(self) -> None:
        """Start the FFmpeg subprocess (reading from yt-dlp pipe or direct URL)."""
        try:
            ytdlp_proc = subprocess.Popen(
                _YTDLP_CMD_TEMPLATE + [self.url],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            self._ffmpeg_proc = subprocess.Popen(
                _FFMPEG_CMD,
                stdin=ytdlp_proc.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            # Allow yt-dlp process to receive SIGPIPE when ffmpeg exits
            if ytdlp_proc.stdout:
                ytdlp_proc.stdout.close()
        except FileNotFoundError as e:
            logger.error("Failed to launch recorder process: %s", e)
            self._ffmpeg_proc = None

    def _reader_loop(self) -> None:
        """Continuous loop: read PCM chunks from ffmpeg stdout."""
        while not self._stop_event.is_set():
            if self._ffmpeg_proc is None or self._ffmpeg_proc.poll() is not None:
                logger.warning("FFmpeg process ended unexpectedly")
                break
            self._read_one_chunk()

    def _read_one_chunk(self) -> None:
        """Read exactly `chunk_duration_s` seconds of float32 PCM and push to buffer."""
        if self._ffmpeg_proc is None or self._ffmpeg_proc.stdout is None:
            return

        num_samples = int(self.sample_rate * self.chunk_duration_s)
        num_bytes = num_samples * 4  # float32 = 4 bytes per sample

        raw = self._ffmpeg_proc.stdout.read(num_bytes)
        if not raw:
            return

        # Handle partial read (end of stream)
        samples_read = len(raw) // 4
        if samples_read == 0:
            return

        audio = np.frombuffer(raw[: samples_read * 4], dtype=np.float32)
        self.audio_buffer.write(audio, start_pts=self._pts)
        self._pts += samples_read / self.sample_rate
        logger.debug("Pushed %d audio samples to buffer (pts=%.2f)", len(audio), self._pts)

