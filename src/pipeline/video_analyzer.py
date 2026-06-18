from typing import Optional

import numpy as np

try:
    import cv2
except ImportError:  # pragma: no cover - optional dependency
    cv2 = None  # type: ignore[assignment,misc]


class VideoAnalyzer:
    SCENE_CHANGE_THRESHOLD = 0.35

    def __init__(self, enabled: bool = True):
        self.enabled = bool(enabled and cv2 is not None)

    def sample_frame(self, video_path: str, pts: float) -> Optional[np.ndarray]:
        if not self.enabled or not video_path:
            return None

        cap = cv2.VideoCapture(video_path)
        try:
            cap.set(cv2.CAP_PROP_POS_MSEC, pts * 1000.0)
            ok, frame = cap.read()
        finally:
            cap.release()

        if not ok or frame is None:
            return None
        return frame

    def analyze(
        self, frame: np.ndarray, prev_frame: Optional[np.ndarray]
    ) -> dict:
        if not self.enabled or prev_frame is None:
            return {"video_scene_change": 0.0, "video_motion": 0.0}

        scene_change = self._histogram_diff(prev_frame, frame)
        motion = self._pixel_motion(prev_frame, frame)

        return {
            "video_scene_change": scene_change,
            "video_motion": motion,
        }

    def _histogram_diff(self, prev_frame: np.ndarray, frame: np.ndarray) -> float:
        gray_prev = self._to_gray(prev_frame)
        gray_curr = self._to_gray(frame)

        hist_prev = cv2.calcHist([gray_prev], [0], None, [64], [0, 256])
        hist_curr = cv2.calcHist([gray_curr], [0], None, [64], [0, 256])
        cv2.normalize(hist_prev, hist_prev)
        cv2.normalize(hist_curr, hist_curr)

        correlation = cv2.compareHist(hist_prev, hist_curr, cv2.HISTCMP_CORREL)
        return float(max(0.0, min(1.0, 1.0 - correlation)))

    def _pixel_motion(self, prev_frame: np.ndarray, frame: np.ndarray) -> float:
        prev = prev_frame.astype(np.float32)
        curr = frame.astype(np.float32)
        if prev.shape != curr.shape:
            curr = cv2.resize(curr, (prev.shape[1], prev.shape[0]))
        diff = np.abs(curr - prev)
        return float(max(0.0, min(1.0, np.mean(diff) / 255.0)))

    def _to_gray(self, frame: np.ndarray) -> np.ndarray:
        if frame.ndim == 2:
            return frame
        return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
