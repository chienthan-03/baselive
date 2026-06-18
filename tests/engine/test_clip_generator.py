import pytest
from unittest.mock import patch, MagicMock
from src.engine.clip_generator import ClipGenerator
from src.core.models import EventCandidate

def test_clip_generation_calls_ffmpeg():
    gen = ClipGenerator(source_file="dummy.mp4", output_dir="output/clips")
    event = EventCandidate(
        state="CLOSED",
        start_pts=60.0,
        end_pts=90.0,
        peak_pts=75.0,
        peak_score=0.88
    )

    with patch("src.engine.clip_generator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        output_path = gen.generate(event)

    # FFmpeg must have been called
    mock_run.assert_called_once()
    call_args = mock_run.call_args[0][0]
    
    # Should contain -ss (seek) and -t (duration) flags
    assert "-ss" in call_args
    assert "-t" in call_args
    assert output_path.endswith(".mp4")

def test_clip_includes_pre_post_roll():
    gen = ClipGenerator(source_file="dummy.mp4", output_dir="output/clips", pre_roll=10.0, post_roll=5.0)
    event = EventCandidate(state="CLOSED", start_pts=60.0, end_pts=90.0)

    with patch("src.engine.clip_generator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        gen.generate(event)

    call_args = mock_run.call_args[0][0]
    
    # Start should be 60.0 - 10.0 = 50.0
    ss_index = call_args.index("-ss")
    assert float(call_args[ss_index + 1]) == pytest.approx(50.0)

    # Duration should be (90.0 - 60.0) + 10.0 + 5.0 = 45.0
    t_index = call_args.index("-t")
    assert float(call_args[t_index + 1]) == pytest.approx(45.0)


def test_clip_generator_applies_pts_offset():
    gen = ClipGenerator(
        source_file="live.mp4",
        output_dir="out",
        pts_offset=100.0,
        pre_roll=10.0,
    )
    event = EventCandidate(start_pts=120.0, end_pts=130.0, peak_score=0.8)
    cmd = gen.build_ffmpeg_cmd(event, "out/test.mp4")
    ss_index = cmd.index("-ss")
    assert float(cmd[ss_index + 1]) == pytest.approx(10.0)
