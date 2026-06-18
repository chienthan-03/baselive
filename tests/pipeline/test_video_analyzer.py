import numpy as np
import pytest
from unittest.mock import patch, MagicMock

from src.pipeline.video_analyzer import VideoAnalyzer


@pytest.fixture
def synthetic_video_frames():
    frame_a = np.zeros((64, 64, 3), dtype=np.uint8)
    frame_b = np.ones((64, 64, 3), dtype=np.uint8) * 255
    return frame_a, frame_b


def test_analyze_detects_scene_change(synthetic_video_frames):
    frame_a, frame_b = synthetic_video_frames
    va = VideoAnalyzer(enabled=True)
    if not va.enabled:
        pytest.skip("opencv not installed")

    result = va.analyze(frame_b, frame_a)
    assert result["video_scene_change"] > 0.3
    assert result["video_motion"] > 0.0


def test_analyze_no_prev_frame_returns_zeros():
    va = VideoAnalyzer(enabled=True)
    if not va.enabled:
        pytest.skip("opencv not installed")

    frame = np.zeros((64, 64, 3), dtype=np.uint8)
    result = va.analyze(frame, None)
    assert result["video_scene_change"] == 0.0
    assert result["video_motion"] == 0.0


@patch("src.pipeline.video_analyzer.cv2")
def test_sample_frame_returns_array(mock_cv2):
    mock_cap = MagicMock()
    mock_cap.read.return_value = (True, np.zeros((64, 64, 3), dtype=np.uint8))
    mock_cv2.VideoCapture.return_value = mock_cap
    mock_cv2.CAP_PROP_POS_MSEC = 0

    va = VideoAnalyzer(enabled=True)
    frame = va.sample_frame("/tmp/fake.mp4", pts=10.0)

    assert frame is not None
    mock_cv2.VideoCapture.assert_called_once_with("/tmp/fake.mp4")
    mock_cap.set.assert_called_once_with(mock_cv2.CAP_PROP_POS_MSEC, 10000.0)
