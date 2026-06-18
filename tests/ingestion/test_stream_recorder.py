import pytest
import numpy as np
import threading
import time
from unittest.mock import patch, MagicMock
from io import BytesIO

from src.ingestion.stream_recorder import StreamRecorder
from src.buffer.circular_buffer import AudioRingBuffer


def _make_fake_pcm(num_samples: int) -> bytes:
    """Generate fake float32 PCM bytes."""
    arr = np.zeros(num_samples, dtype=np.float32)
    return arr.tobytes()


def test_stream_recorder_reads_pcm_into_buffer():
    """StreamRecorder should read PCM stdout and push audio into AudioRingBuffer."""
    sample_rate = 16000
    chunk_duration = 1.0  # 1 second chunks for test speed
    num_samples_per_chunk = int(sample_rate * chunk_duration)

    # 3 chunks of fake PCM
    fake_pcm = _make_fake_pcm(num_samples_per_chunk * 3)
    fake_stdout = BytesIO(fake_pcm)

    # Mock the ffmpeg process
    mock_proc = MagicMock()
    mock_proc.stdout = fake_stdout
    mock_proc.poll.return_value = None  # process still running

    audio_buffer = AudioRingBuffer(capacity_sec=60, sample_rate=sample_rate)

    recorder = StreamRecorder(
        url="https://tiktok.com/@test/live",
        audio_buffer=audio_buffer,
        chunk_duration_s=chunk_duration,
        sample_rate=sample_rate,
    )
    # Inject mock proc directly — bypasses _launch_ffmpeg subprocess chain
    recorder._ffmpeg_proc = mock_proc

    recorder._read_one_chunk()
    recorder._read_one_chunk()

    # Buffer should have received samples (write_pos advances past 0)
    assert audio_buffer.write_pos > 0


def test_stream_recorder_stop_terminates_process():
    """stop() should terminate the ffmpeg subprocess."""
    mock_proc = MagicMock()
    mock_proc.stdout = BytesIO(b"")
    mock_proc.poll.return_value = None

    audio_buffer = AudioRingBuffer(capacity_sec=60, sample_rate=16000)

    with patch("src.ingestion.stream_recorder.subprocess.Popen", return_value=mock_proc):
        recorder = StreamRecorder(
            url="https://tiktok.com/@test/live",
            audio_buffer=audio_buffer,
        )
        recorder._ffmpeg_proc = mock_proc  # simulate that start() was called
        recorder.stop()

    mock_proc.terminate.assert_called_once()


def test_stream_recorder_exposes_video_path(tmp_path):
    audio_buffer = AudioRingBuffer(capacity_sec=60, sample_rate=16000)
    recorder = StreamRecorder(
        url="https://tiktok.com/@test/live",
        audio_buffer=audio_buffer,
        stream_id="test_stream",
        video_output_dir=str(tmp_path),
    )
    assert recorder.video_path.endswith("live.mp4")
    assert str(tmp_path) in recorder.video_path


def test_stream_recorder_is_running_false_before_start():
    """StreamRecorder should report is_running=False before start() is called."""
    audio_buffer = AudioRingBuffer(capacity_sec=60, sample_rate=16000)
    recorder = StreamRecorder(
        url="https://tiktok.com/@test/live",
        audio_buffer=audio_buffer,
    )
    assert recorder.is_running is False


def test_stream_recorder_rotates_video_file(tmp_path):
    recorder = StreamRecorder(
        url="https://tiktok.com/@test/live",
        audio_buffer=AudioRingBuffer(capacity_sec=60, sample_rate=16000),
        stream_id="rot_test",
        video_output_dir=str(tmp_path),
        max_video_duration_s=1.0,  # short for test
    )
    recorder._rotate_video_file()
    assert "live_001.mp4" in recorder.video_path or recorder.pts_offset > 0


def test_ytdlp_command_uses_no_live_from_start():
    from src.ingestion.stream_recorder import _ytdlp_resolve_command

    cmd = _ytdlp_resolve_command()
    assert "--no-live-from-start" in cmd
    assert "--live-from-start" not in cmd
    assert "-g" in cmd
    assert "hls-pull" in cmd
