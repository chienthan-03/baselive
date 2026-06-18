import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

from src.core.models import ThresholdSet

_DEFAULT_PRIOR_PATH = Path(__file__).resolve().parents[2] / "config" / "global_prior.json"

PHASE0_END_SEC = 60.0
PHASE1_END_SEC = 300.0
PHASE0_CLOSE_THR = 0.25


@dataclass
class GlobalPrior:
    open_thr: float = 0.5
    confirm_thr: float = 0.65
    close_thr: float = 0.25
    peak_thr: float = 0.8
    audio_energy_mean: float = 0.05
    audio_energy_std: float = 0.02
    chat_volume_mean: float = 8.0
    chat_volume_std: float = 3.0
    speaking_rate_mean: float = 3.5
    speaking_rate_std: float = 0.8


def _lerp(a: float, b: float, weight: float) -> float:
    return a + (b - a) * weight


def _percentile(values: List[float], p: float) -> float:
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    lower = int(math.floor(k))
    upper = int(math.ceil(k))
    if lower == upper:
        return sorted_vals[lower]
    return sorted_vals[lower] + (k - lower) * (sorted_vals[upper] - sorted_vals[lower])


class RollingStats:
    def __init__(self, window_sec: int = 300):
        self.window_sec = window_sec
        self._entries: List[Tuple[float, float]] = []

    def append(self, pts: float, composite_score: float) -> None:
        self._entries.append((pts, composite_score))
        self._prune(pts)

    def _prune(self, current_pts: float) -> None:
        self._entries = [
            (pts, score)
            for pts, score in self._entries
            if current_pts - pts <= self.window_sec
        ]

    @property
    def composite_scores(self) -> List[float]:
        return [score for _, score in self._entries]

    def mean(self) -> float:
        scores = self.composite_scores
        if not scores:
            return 0.0
        return sum(scores) / len(scores)

    def std(self) -> float:
        scores = self.composite_scores
        if len(scores) < 2:
            return 0.0
        avg = self.mean()
        variance = sum((s - avg) ** 2 for s in scores) / len(scores)
        return math.sqrt(variance)

    def percentile(self, p: float) -> float:
        return _percentile(self.composite_scores, p)


class BaselineCalibrator:
    PHASE0_OPEN_FACTOR = 0.8
    PHASE0_CONFIRM_FACTOR = 0.85
    PHASE0_PEAK_FACTOR = 0.85

    def __init__(self, prior_path: Optional[Path] = None):
        path = prior_path or _DEFAULT_PRIOR_PATH
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.global_prior = GlobalPrior(**data)

    def _phase0_thresholds(self) -> ThresholdSet:
        return ThresholdSet(
            open_thr=self.global_prior.open_thr * self.PHASE0_OPEN_FACTOR,
            confirm_thr=self.global_prior.confirm_thr * self.PHASE0_CONFIRM_FACTOR,
            close_thr=PHASE0_CLOSE_THR,
            peak_thr=self.global_prior.peak_thr * self.PHASE0_PEAK_FACTOR,
        )

    def _calibrated_thresholds(self, rolling_stats: RollingStats) -> ThresholdSet:
        scores = rolling_stats.composite_scores
        if not scores:
            return ThresholdSet(
                open_thr=self.global_prior.open_thr,
                confirm_thr=self.global_prior.confirm_thr,
                close_thr=self.global_prior.close_thr,
                peak_thr=self.global_prior.peak_thr,
            )
        return ThresholdSet(
            open_thr=rolling_stats.percentile(80),
            confirm_thr=rolling_stats.percentile(90),
            close_thr=rolling_stats.percentile(30),
            peak_thr=rolling_stats.percentile(95),
        )

    def _blend_weight(self, elapsed_sec: float) -> float:
        return (elapsed_sec - PHASE0_END_SEC) / (PHASE1_END_SEC - PHASE0_END_SEC)

    def _blend_thresholds(
        self, phase0: ThresholdSet, calibrated: ThresholdSet, weight: float
    ) -> ThresholdSet:
        return ThresholdSet(
            open_thr=_lerp(phase0.open_thr, calibrated.open_thr, weight),
            confirm_thr=_lerp(phase0.confirm_thr, calibrated.confirm_thr, weight),
            close_thr=_lerp(phase0.close_thr, calibrated.close_thr, weight),
            peak_thr=_lerp(phase0.peak_thr, calibrated.peak_thr, weight),
        )

    def get_thresholds(
        self, elapsed_sec: float, rolling_stats: RollingStats
    ) -> ThresholdSet:
        if elapsed_sec < PHASE0_END_SEC:
            return self._phase0_thresholds()

        calibrated = self._calibrated_thresholds(rolling_stats)

        if elapsed_sec >= PHASE1_END_SEC:
            return calibrated

        phase0 = self._phase0_thresholds()
        weight = self._blend_weight(elapsed_sec)
        return self._blend_thresholds(phase0, calibrated, weight)

    def detect_activity_change(
        self, stats_1min: RollingStats, stats_5min: RollingStats
    ) -> bool:
        mean_1min = stats_1min.mean()
        mean_5min = stats_5min.mean()
        std_5min = stats_5min.std()
        return abs(mean_1min - mean_5min) > 2 * std_5min

    def recalibrate(self) -> None:
        pass
