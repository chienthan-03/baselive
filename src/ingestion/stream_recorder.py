"""
StreamRecorder: Pulls a livestream via yt-dlp piped through FFmpeg,
reads raw PCM float32 audio from stdout, and feeds it into an AudioRingBuffer.
"""
import os
import shutil
import subprocess
import sys
import threading
import logging
import numpy as np
from typing import Optional

from src.buffer.circular_buffer import AudioRingBuffer

logger = logging.getLogger(__name__)

_YTDLP_FORMAT = "hls-pull"


def _ytdlp_resolve_command() -> list[str]:
    """Build yt-dlp command that prints a direct stream URL (-g)."""
    if shutil.which("yt-dlp"):
        base = ["yt-dlp"]
    else:
        base = [sys.executable, "-m", "yt_dlp"]
    return base + ["--no-live-from-start", "-g", "-f", _YTDLP_FORMAT]


# Backwards-compatible alias used in tests.
def _ytdlp_command() -> list[str]:
    return _ytdlp_resolve_command()


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
        stream_id: str = "default",
        video_output_dir: str = "output/streams",
        max_video_duration_s: float = 1800.0,
        max_video_size_mb: float = 500.0,
    ):
        self.url = url
        self.audio_buffer = audio_buffer
        self.segment_dir = segment_dir
        self.chunk_duration_s = chunk_duration_s
        self.sample_rate = sample_rate
        self.stream_id = stream_id
        self.video_output_dir = video_output_dir
        self.max_video_duration_s = max_video_duration_s
        self.max_video_size_mb = max_video_size_mb

        os.makedirs(os.path.join(video_output_dir, stream_id), exist_ok=True)
        self.video_path = os.path.join(video_output_dir, stream_id, "live.mp4")
        self.pts_offset: float = 0.0

        self._ffmpeg_proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._pts: float = 0.0  # running PTS based on samples written
        self._video_start_pts: float = 0.0
        self._file_index: int = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Resolve stream URL, launch ffmpeg, and start reader thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("StreamRecorder already running")
            return

        self._stop_event.clear()
        self._pts = 0.0
        self._video_start_pts = 0.0
        self._file_index = 0
        self._launch_ffmpeg()
        if self._ffmpeg_proc is None:
            logger.error("StreamRecorder failed to start for %s", self.url)
            return
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()
        logger.info("StreamRecorder started for %s -> %s", self.url, self.video_path)

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
            and self._ffmpeg_proc is not None
            and self._ffmpeg_proc.poll() is None
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_stream_url(self) -> Optional[str]:
        cmd = _ytdlp_resolve_command() + [self.url]
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as exc:
            logger.error("yt-dlp not found: %s", exc)
            return None

        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            logger.error("yt-dlp resolve failed for %s: %s", self.url, err[-500:])
            return None

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            logger.error("yt-dlp returned no stream URL for %s", self.url)
            return None

        stream_url = lines[-1]
        logger.info("Resolved live stream URL for %s", self.url)
        return stream_url

    def _ffmpeg_command(self, stream_url: str) -> list[str]:
        return [
            "ffmpeg",
            "-loglevel", "error",
            "-i", stream_url,
            "-map", "0:a?",
            "-ar", str(self.sample_rate),
            "-ac", "1",
            "-f", "f32le",
            "pipe:1",
            "-map", "0:v?",
            "-c:v", "copy",
            "-movflags", "+frag_keyframe+empty_moov",
            self.video_path,
        ]

    def _launch_ffmpeg(self) -> None:
        stream_url = self._resolve_stream_url()
        if not stream_url:
            self._ffmpeg_proc = None
            return
        try:
            self._ffmpeg_proc = subprocess.Popen(
                self._ffmpeg_command(stream_url),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            logger.error("Failed to launch ffmpeg: %s", exc)
            self._ffmpeg_proc = None

    def _log_ffmpeg_stderr(self) -> None:
        if self._ffmpeg_proc is None or self._ffmpeg_proc.stderr is None:
            return
        try:
            err = self._ffmpeg_proc.stderr.read().decode("utf-8", errors="replace").strip()
        except Exception:
            return
        if err:
            logger.error("ffmpeg failed for %s: %s", self.url, err[-500:])

    def _reader_loop(self) -> None:
        """Continuous loop: read PCM chunks from ffmpeg stdout."""
        while not self._stop_event.is_set():
            if self._ffmpeg_proc is None or self._ffmpeg_proc.poll() is not None:
                self._log_ffmpeg_stderr()
                logger.warning("FFmpeg process ended unexpectedly for %s", self.url)
                break
            self._read_one_chunk()

    def _rotate_video_file(self) -> None:
        """Start a new video segment file and accumulate PTS offset."""
        elapsed = self._pts - self._video_start_pts
        self.pts_offset += elapsed
        self._file_index += 1
        self._video_start_pts = self._pts

        stream_dir = os.path.join(self.video_output_dir, self.stream_id)
        filename = f"live_{self._file_index:03d}.mp4"
        self.video_path = os.path.join(stream_dir, filename)
        logger.info(
            "Rotated video to %s (pts_offset=%.2f)",
            self.video_path,
            self.pts_offset,
        )

    def _should_rotate_video(self) -> bool:
        """Return True when duration or file-size threshold is exceeded."""
        if self._pts - self._video_start_pts >= self.max_video_duration_s:
            return True
        if os.path.exists(self.video_path):
            size_mb = os.path.getsize(self.video_path) / (1024 * 1024)
            if size_mb >= self.max_video_size_mb:
                return True
        return False

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
        self.audio_buffer.write(audio, start_pts=self._pts + self.pts_offset)
        self._pts += samples_read / self.sample_rate
        logger.debug("Pushed %d audio samples to buffer (pts=%.2f)", len(audio), self._pts)

        if self._should_rotate_video():
            self._rotate_video_file()
