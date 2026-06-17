import pytest
from src.engine.aggregator import SignalAggregator
from src.core.models import SignalSnapshot

def test_aggregator_weights():
    agg = SignalAggregator()
    snapshot = SignalSnapshot(
        pts=10.0,
        audio_energy_spike=True, # 1.0 * weight 0.2
        sentiment_shift=0.8,     # 0.8 * weight 0.4
        chat_volume_spike=1.0    # 1.0 * weight 0.4
    )
    result = agg.compute_score(snapshot)
    # Expected: 1.0*0.2 + 0.8*0.4 + 1.0*0.4 = 0.2 + 0.32 + 0.4 = 0.92
    assert result == pytest.approx(0.92)
