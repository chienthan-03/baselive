import pytest

from src.engine.baseline_calibrator import BaselineCalibrator, RollingStats


@pytest.fixture
def empty_stats():
    return RollingStats()


@pytest.fixture
def rolling_stats_with_scores():
    stats = RollingStats()
    for i, score in enumerate(
        [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0], start=1
    ):
        stats.append(float(i * 10), score)
    return stats


def test_phase0_lower_open_threshold(empty_stats):
    cal = BaselineCalibrator()
    thresholds = cal.get_thresholds(elapsed_sec=30.0, rolling_stats=empty_stats)
    assert thresholds.open_thr < cal.global_prior.open_thr
    assert thresholds.open_thr == pytest.approx(cal.global_prior.open_thr * 0.8)
    assert thresholds.close_thr == 0.25


def test_phase2_uses_percentiles(rolling_stats_with_scores):
    cal = BaselineCalibrator()
    thresholds = cal.get_thresholds(
        elapsed_sec=400.0, rolling_stats=rolling_stats_with_scores
    )
    assert thresholds.open_thr > thresholds.close_thr
    assert thresholds.open_thr == pytest.approx(
        rolling_stats_with_scores.percentile(80), rel=1e-3
    )
    assert thresholds.confirm_thr == pytest.approx(
        rolling_stats_with_scores.percentile(90), rel=1e-3
    )
    assert thresholds.close_thr == pytest.approx(
        rolling_stats_with_scores.percentile(30), rel=1e-3
    )
    assert thresholds.peak_thr == pytest.approx(
        rolling_stats_with_scores.percentile(95), rel=1e-3
    )


def test_phase1_blend_between_tiers(rolling_stats_with_scores):
    cal = BaselineCalibrator()
    phase0 = cal.get_thresholds(elapsed_sec=30.0, rolling_stats=rolling_stats_with_scores)
    phase2 = cal.get_thresholds(
        elapsed_sec=400.0, rolling_stats=rolling_stats_with_scores
    )
    phase1 = cal.get_thresholds(
        elapsed_sec=180.0, rolling_stats=rolling_stats_with_scores
    )

    assert phase0.open_thr < phase1.open_thr < phase2.open_thr
    assert phase1.open_thr == pytest.approx(
        (phase0.open_thr + phase2.open_thr) / 2, rel=1e-3
    )
